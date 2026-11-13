#!/usr/bin/env python3
"""
Synthetic dryland hillslope erosion and deposition teaching simulation.

Couples four geomorphic processes through surface elevation z(x, y, t):
1. Hillslope creep (vegetation-modulated soil diffusion).
2. Overland flow erosion, transport, and deposition (MFD routing + Davy-Lague flux).
3. Stochastic rainstorms (Poisson arrivals, Gamma depths, intensity-duration scaling).
4. Patchy vegetation cover (infiltration, soil armoring, critical threshold, trapping, creep damping).
"""

import argparse
import base64
import csv
import heapq
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.ndimage import gaussian_filter


# Domain & time configuration
GRID_ROWS = 120
GRID_COLS = 120
CELL_SIZE_M = 2.0
CELL_AREA_M2 = CELL_SIZE_M * CELL_SIZE_M
YEARS_SIMULATED = 200.0
BASE_DT_MAX_YR = 0.25
SNAPSHOT_COUNT = 11  # Every 20 years from t=0 to t=200

# Geomorphic & hydrologic parameters
CREEP_D0_M2_YR = 0.015       # Bare-ground low-slope soil diffusivity (m^2/yr)
CREEP_VEG_DAMP = 0.70        # Fractional creep reduction at full vegetation cover
STORM_RATE_PER_YR = 10.0     # Mean storm arrival rate (storms/yr)
STORM_GAMMA_SHAPE = 0.85     # Gamma shape parameter for storm depth
STORM_GAMMA_SCALE_MM = 30.0  # Gamma scale parameter (mean depth = 25.5 mm)
INFIL_BARE_MM_HR = 8.0       # Bare crusted dryland infiltration capacity (mm/hr)
INFIL_VEG_ADD_MM_HR = 24.0   # Extra infiltration capacity under full cover (32 mm/hr total)
RUNON_LOSS_BARE = 0.002      # Per-cell run-on transmission loss fraction on bare soil
RUNON_LOSS_VEG_ADD = 0.068   # Extra per-cell transmission loss under vegetation (0.070 total)
ERODIBILITY_K0 = 2.8e-3      # Bare-ground overland detachment coefficient (m/s per unit shear)
ERODIBILITY_VEG_EXP = 3.0    # Exponential vegetation armoring exponent
TAU_C0 = 1.8e-5              # Bare-ground critical flow-slope threshold
TAU_C_VEG_MULT = 3.0         # Vegetation multiplier on critical threshold
SETTLING_VS0_M_S = 2.0e-3    # Bare-ground effective sediment settling velocity (m/s)
SETTLING_VEG_MULT = 2.5      # Vegetation trapping multiplier on settling velocity
MFD_EXPONENT = 1.25          # Multiple flow direction slope weighting exponent

# 8-neighbor offsets: (dr, dc, distance_multiplier)
NEIGHBOR_OFFSETS = (
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, np.sqrt(2.0)), (-1, 1, np.sqrt(2.0)),
    (1, -1, np.sqrt(2.0)), (1, 1, np.sqrt(2.0)),
)
R_ACTIVE = np.arange(GRID_ROWS - 1)
C_ACTIVE = np.arange(GRID_COLS)
SRC_FLAT = (R_ACTIVE[:, None] * GRID_COLS + C_ACTIVE[None, :]).ravel()
N_CELLS = GRID_ROWS * GRID_COLS


def generate_initial_surface(rng: np.random.Generator) -> np.ndarray:
    """Create a synthetic dryland hillslope-to-piedmont elevation grid (metres)."""
    y = np.arange(GRID_ROWS, dtype=np.float64) * CELL_SIZE_M
    x = np.arange(GRID_COLS, dtype=np.float64) * CELL_SIZE_M
    Y, X = np.meshgrid(y, x, indexing="ij")
    domain_len = (GRID_ROWS - 1) * CELL_SIZE_M
    s = Y / domain_len

    # Convex upper crest -> steep midslope escarpment -> gentle 4% piedmont
    profile = 24.0 * (1.0 - 1.0 / (1.0 + np.exp(-8.0 * (s - 0.38)))) + 6.0 * (1.0 - s)
    profile -= profile[-1, 0]

    # Broad central hollow and subtle spurs to focus midslope gullies and footslope fans
    lateral = 0.70 * np.cos(2.0 * np.pi * (X - 0.5 * domain_len) / domain_len) * np.exp(
        -((s - 0.32) / 0.28) ** 2
    )
    lateral += 0.30 * np.sin(3.0 * np.pi * X / domain_len) * np.sin(np.pi * s)

    # Correlated micro-topographic roughness from the RNG seed
    raw_noise = rng.normal(0.0, 1.0, (GRID_ROWS, GRID_COLS))
    smooth_noise = gaussian_filter(raw_noise, sigma=1.6, mode="reflect")
    noise = 0.16 * smooth_noise / (np.std(smooth_noise) + 1e-12) * np.sin(np.pi * s)

    z0 = profile + lateral + noise
    z0[-1, :] = 0.0
    return z0.astype(np.float64)


def generate_vegetation(rng: np.random.Generator, veg_scale: float) -> np.ndarray:
    """Create patchy dryland shrub/grass cover in [0, 1] from the seed, scaled by veg_scale."""
    n_fine = gaussian_filter(rng.normal(0.0, 1.0, (GRID_ROWS, GRID_COLS)), sigma=2.2, mode="reflect")
    n_coarse = gaussian_filter(rng.normal(0.0, 1.0, (GRID_ROWS, GRID_COLS)), sigma=5.5, mode="reflect")
    field = 0.65 * n_fine / (np.std(n_fine) + 1e-12) + 0.35 * n_coarse / (np.std(n_coarse) + 1e-12)
    veg_base = 1.0 / (1.0 + np.exp(-2.2 * (field - 0.20)))
    veg_base = np.clip((veg_base - 0.15) / 0.78, 0.0, 1.0)
    return np.clip(veg_base * veg_scale, 0.0, 1.0).astype(np.float64)


def generate_storms(rng: np.random.Generator, years: float) -> tuple[np.ndarray, np.ndarray]:
    """Generate Poisson storm arrival times (years) and Gamma storm depths (mm)."""
    t = 0.0
    times = []
    depths = []
    while True:
        t += rng.exponential(1.0 / STORM_RATE_PER_YR)
        if t >= years:
            break
        depth_mm = rng.gamma(shape=STORM_GAMMA_SHAPE, scale=STORM_GAMMA_SCALE_MM)
        times.append(t)
        depths.append(depth_mm)
    return np.array(times, dtype=np.float64), np.array(depths, dtype=np.float64)


def fill_depressions_if_needed(z: np.ndarray) -> np.ndarray:
    """Return an epsilon-filled routing surface draining to the bottom row if pits exist."""
    zp = np.empty((GRID_ROWS + 2, GRID_COLS + 2), dtype=np.float64)
    zp[1:-1, 1:-1] = z
    zp[0, :] = np.inf
    zp[:, 0] = np.inf
    zp[:, -1] = np.inf
    zp[-1, :] = -np.inf
    min_nb = np.minimum.reduce([
        zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:],
        zp[1:-1, :-2],               zp[1:-1, 2:],
        zp[2:, :-2],  zp[2:, 1:-1],  zp[2:, 2:],
    ])
    if not np.any(min_nb[:-1, :] >= z[:-1, :]):
        return z

    zf = z.copy()
    visited = np.zeros((GRID_ROWS, GRID_COLS), dtype=bool)
    pq = []
    for c in range(GRID_COLS):
        visited[GRID_ROWS - 1, c] = True
        heapq.heappush(pq, (float(zf[GRID_ROWS - 1, c]), GRID_ROWS - 1, c))

    eps = 1e-6
    while pq:
        elev, r, c = heapq.heappop(pq)
        for dr, dc, _ in NEIGHBOR_OFFSETS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS and not visited[nr, nc]:
                visited[nr, nc] = True
                if zf[nr, nc] <= elev + eps:
                    zf[nr, nc] = elev + eps
                heapq.heappush(pq, (float(zf[nr, nc]), nr, nc))
    return zf


def build_flow_routing(z: np.ndarray) -> tuple[sp.csc_matrix, np.ndarray]:
    """
    Build the sparse Multiple Flow Direction (MFD) routing matrix W and true local slopes.

    W[dst, src] gives the fraction of water/sediment routed from cell src to cell dst.
    The bottom row (row GRID_ROWS - 1) is the open outlet and has no outgoing edges.
    """
    zf = fill_depressions_if_needed(z)
    z_act = z[:-1, :]
    zf_act = zf[:-1, :]
    max_slope_true = np.zeros((GRID_ROWS - 1, GRID_COLS), dtype=np.float64)
    total_w = np.zeros((GRID_ROWS - 1, GRID_COLS), dtype=np.float64)
    raw_ws = []
    dsts = []

    for dr, dc, dist_mult in NEIGHBOR_OFFSETS:
        dist = dist_mult * CELL_SIZE_M
        r_valid = (R_ACTIVE + dr >= 0) & (R_ACTIVE + dr < GRID_ROWS)
        c_valid = (C_ACTIVE + dc >= 0) & (C_ACTIVE + dc < GRID_COLS)
        valid = r_valid[:, None] & c_valid[None, :]
        nr = np.clip(R_ACTIVE + dr, 0, GRID_ROWS - 1)[:, None]
        nc = np.clip(C_ACTIVE + dc, 0, GRID_COLS - 1)[None, :]

        z_nb = z[nr, nc]
        dz_true = np.where(valid, z_act - z_nb, 0.0)
        max_slope_true = np.maximum(max_slope_true, np.maximum(0.0, dz_true) / dist)

        dz_route = np.where(valid, zf_act - zf[nr, nc], 0.0)
        s_route = np.maximum(0.0, dz_route) / dist
        w_raw = np.where(dz_route > 0.0, s_route ** MFD_EXPONENT, 0.0)
        total_w += w_raw
        raw_ws.append(w_raw)
        dsts.append((nr * GRID_COLS + nc).ravel())

    inv_total = np.where(total_w > 0.0, 1.0 / np.maximum(total_w, 1e-30), 0.0)
    src_list, dst_list, w_list = [], [], []
    for w_raw, dst_flat in zip(raw_ws, dsts):
        w_norm = (w_raw * inv_total).ravel()
        nz = w_norm > 0.0
        src_list.append(SRC_FLAT[nz])
        dst_list.append(dst_flat[nz])
        w_list.append(w_norm[nz])

    W = sp.csc_matrix(
        (np.concatenate(w_list), (np.concatenate(dst_list), np.concatenate(src_list))),
        shape=(N_CELLS, N_CELLS),
    )
    return W, max_slope_true


def compute_contributing_area(z: np.ndarray) -> np.ndarray:
    """Compute upslope contributing area (m^2) at every cell via (I - W) A = cell_area."""
    W, _ = build_flow_routing(z)
    A_mat = sp.eye(N_CELLS, format="csc") - W
    rhs = np.full(N_CELLS, CELL_AREA_M2, dtype=np.float64)
    area = spla.spsolve(A_mat, rhs, permc_spec="NATURAL").reshape(GRID_ROWS, GRID_COLS)
    return np.maximum(CELL_AREA_M2, area)


def step_hillslope_creep(z: np.ndarray, veg: np.ndarray, dt_yr: float) -> float:
    """
    Process 1: Vegetation-modulated diffusive hillslope creep over dt_yr years.

    Top, left, and right edges are closed (zero flux). The bottom row is held at
    fixed base level and receives diffusive flux exported out of the active grid.
    Returns sediment volume exported across the bottom boundary (m^3).
    """
    if dt_yr <= 0.0:
        return 0.0

    # Enforce explicit diffusion CFL <= 0.20 via internal sub-stepping if dt_yr is large
    cfl = CREEP_D0_M2_YR * dt_yr / CELL_AREA_M2
    n_cfl = max(1, int(np.ceil(cfl / 0.20)))
    sub_dt = dt_yr / n_cfl

    D = CREEP_D0_M2_YR * (1.0 - CREEP_VEG_DAMP * veg)
    Dx = 0.5 * (D[:-1, :-1] + D[:-1, 1:])
    Dy = 0.5 * (D[:-1, :] + D[1:, :])

    exported_m3 = 0.0
    dz_dt = np.zeros((GRID_ROWS - 1, GRID_COLS), dtype=np.float64)
    for _ in range(n_cfl):
        qx = -Dx * (z[:-1, 1:] - z[:-1, :-1]) / CELL_SIZE_M
        qy = -Dy * (z[1:, :] - z[:-1, :]) / CELL_SIZE_M

        dz_dt.fill(0.0)
        dz_dt[:, :-1] -= qx / CELL_SIZE_M
        dz_dt[:, 1:] += qx / CELL_SIZE_M
        dz_dt -= qy / CELL_SIZE_M
        dz_dt[1:, :] += qy[:-1, :] / CELL_SIZE_M

        z[:-1, :] += dz_dt * sub_dt
        exported_m3 += float(np.sum(qy[-1, :])) * CELL_SIZE_M * sub_dt

    return exported_m3


def step_overland_flow(
    z: np.ndarray, veg: np.ndarray, depth_mm: float, dt_frac: float = 1.0
) -> float:
    """
    Processes 2, 3 & 4: Storm-driven Hortonian runoff, overland erosion, and deposition.

    Intensity-duration storm scaling ensures halving dt_frac yields consistent runoff.
    Sediment flux is routed and deposited via an implicit Davy-Lague M-matrix solve
    that conserves mass exactly and exports sediment arriving at the bottom row.
    """
    if depth_mm <= 0.0:
        return 0.0

    p_m = depth_mm * 1.0e-3
    # Storm duration scales sub-linearly with depth (1 hr at 20 mm), giving realistic intensity
    t_storm_s = 3600.0 * (p_m / 0.020) ** 0.4
    i_rain_m_s = p_m / t_storm_s
    dt_s = t_storm_s * dt_frac

    # Vegetation increases infiltration capacity (mm/hr -> m/s)
    f_inf_m_s = (INFIL_BARE_MM_HR + INFIL_VEG_ADD_MM_HR * veg) * (1.0e-3 / 3600.0)
    r_local = np.maximum(0.0, i_rain_m_s - f_inf_m_s)
    r_local[-1, :] = 0.0
    if np.max(r_local) <= 0.0:
        return 0.0

    W, slope_act = build_flow_routing(z)

    # Vegetation increases run-on transmission loss along flow paths
    lam = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.float64)
    lam[:-1, :] = RUNON_LOSS_BARE + RUNON_LOSS_VEG_ADD * veg[:-1, :]
    A_water = sp.diags(1.0 + lam.ravel(), format="csc") - W
    Q_out = spla.spsolve(A_water, (r_local * CELL_AREA_M2).ravel(), permc_spec="NATURAL").reshape(
        GRID_ROWS, GRID_COLS
    )
    Q_out = np.maximum(0.0, Q_out)

    # Overland detachment E [m/s]: vegetation reduces erodibility and raises threshold
    q_unit = Q_out[:-1, :] / CELL_SIZE_M
    k_eff = ERODIBILITY_K0 * np.exp(-ERODIBILITY_VEG_EXP * veg[:-1, :])
    tau_c = TAU_C0 * (1.0 + TAU_C_VEG_MULT * veg[:-1, :])
    shear = (q_unit ** 0.6) * slope_act
    E_act = k_eff * np.maximum(0.0, shear - tau_c)

    E_full = np.zeros(N_CELLS, dtype=np.float64)
    E_full[: (GRID_ROWS - 1) * GRID_COLS] = (E_act * CELL_AREA_M2).ravel()

    # Implicit sediment transport & deposition: (1 + alpha) Qs_out - W Qs_out = E * cell_area
    v_s = SETTLING_VS0_M_S * (1.0 + SETTLING_VEG_MULT * veg)
    alpha = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.float64)
    Q_act = Q_out[:-1, :]
    alpha[:-1, :] = np.where(
        Q_act > 1.0e-12, v_s[:-1, :] * CELL_AREA_M2 / np.maximum(Q_act, 1.0e-12), 1.0e12
    )
    A_sed = sp.diags(1.0 + alpha.ravel(), format="csc") - W
    Qs_out = spla.spsolve(A_sed, E_full, permc_spec="NATURAL").reshape(GRID_ROWS, GRID_COLS)
    Qs_out = np.maximum(0.0, Qs_out)

    Qs_in = (W @ Qs_out.ravel()).reshape(GRID_ROWS, GRID_COLS)
    z[:-1, :] += ((Qs_in[:-1, :] - Qs_out[:-1, :]) / CELL_AREA_M2) * dt_s
    exported_m3 = float(np.sum(Qs_in[-1, :])) * dt_s
    return exported_m3


def run_simulation(
    seed: int,
    z0_path: str | None,
    rain_scale: float,
    veg_scale: float,
    dt_scale: float,
    capture_snapshots: bool,
) -> dict:
    """Execute the coupled dryland hillslope evolution simulation."""
    ss = np.random.SeedSequence(seed)
    rng_z, rng_veg, rng_storms = [np.random.default_rng(s) for s in ss.spawn(3)]

    if z0_path is not None:
        z_initial = np.load(z0_path).astype(np.float64)
        if z_initial.shape != (GRID_ROWS, GRID_COLS):
            raise ValueError(
                f"--z0 array must have shape {(GRID_ROWS, GRID_COLS)}, got {z_initial.shape}"
            )
    else:
        z_initial = generate_initial_surface(rng_z)

    veg = generate_vegetation(rng_veg, veg_scale)
    storm_times, storm_depths_unscaled = generate_storms(rng_storms, YEARS_SIMULATED)
    storm_depths_scaled = storm_depths_unscaled * rain_scale

    z = z_initial.copy()
    dt_max_yr = BASE_DT_MAX_YR * dt_scale
    n_storm_sub = max(1, int(round(1.0 / dt_scale))) if dt_scale < 1.0 else 1

    snapshot_targets = np.linspace(0.0, YEARS_SIMULATED, SNAPSHOT_COUNT)
    snapshots = []
    next_snap_idx = 0
    if capture_snapshots:
        snapshots.append({
            "year": 0.0,
            "z": z.astype(np.float32).copy(),
            "flow_area": compute_contributing_area(z).astype(np.float32),
            "exported_m3": 0.0,
            "storms_so_far": 0,
            "rain_mm_so_far": 0.0,
        })
        next_snap_idx = 1

    exported_total_m3 = 0.0
    t_cur = 0.0
    timesteps = 0
    max_dt_used_yr = 0.0
    storms_done = 0
    rain_done_mm = 0.0

    def advance_creep(t_start: float, t_end: float) -> None:
        nonlocal exported_total_m3, timesteps, max_dt_used_yr, next_snap_idx
        rem = t_end - t_start
        if rem <= 1.0e-12:
            return
        n_base = max(1, int(np.ceil(rem / BASE_DT_MAX_YR)))
        if dt_scale <= 1.0:
            n_c = n_base * n_storm_sub
        else:
            n_c = max(1, int(np.ceil(rem / dt_max_yr)))
        dt_c = rem / n_c
        max_dt_used_yr = max(max_dt_used_yr, dt_c)
        for step_i in range(n_c):
            exported_total_m3 += step_hillslope_creep(z, veg, dt_c)
            timesteps += 1
            t_now = t_start + (step_i + 1) * dt_c
            if (
                capture_snapshots
                and next_snap_idx < len(snapshot_targets) - 1
                and t_now >= snapshot_targets[next_snap_idx]
            ):
                snapshots.append({
                    "year": float(t_now),
                    "z": z.astype(np.float32).copy(),
                    "flow_area": compute_contributing_area(z).astype(np.float32),
                    "exported_m3": float(exported_total_m3),
                    "storms_so_far": int(storms_done),
                    "rain_mm_so_far": float(rain_done_mm),
                })
                next_snap_idx += 1

    for t_s, d_s in zip(storm_times, storm_depths_scaled):
        advance_creep(t_cur, float(t_s))
        t_cur = float(t_s)

        for _ in range(n_storm_sub):
            exported_total_m3 += step_overland_flow(z, veg, float(d_s), dt_frac=1.0 / n_storm_sub)
            timesteps += 1

        storms_done += 1
        rain_done_mm += float(d_s)

    advance_creep(t_cur, YEARS_SIMULATED)
    t_cur = YEARS_SIMULATED

    if capture_snapshots:
        snapshots.append({
            "year": float(YEARS_SIMULATED),
            "z": z.astype(np.float32).copy(),
            "flow_area": compute_contributing_area(z).astype(np.float32),
            "exported_m3": float(exported_total_m3),
            "storms_so_far": int(storms_done),
            "rain_mm_so_far": float(rain_done_mm),
        })

    if max_dt_used_yr == 0.0:
        max_dt_used_yr = dt_max_yr

    dz = z - z_initial
    net_vol_change_m3 = float(np.sum(dz)) * CELL_AREA_M2
    uplift_m3 = 0.0
    residual_m3 = abs(net_vol_change_m3 + exported_total_m3 - uplift_m3)
    denom_m3 = max(1.0e-12, float(np.sum(np.abs(dz))) * CELL_AREA_M2 + abs(exported_total_m3))
    mass_balance_error_pct = (residual_m3 / denom_m3) * 100.0

    telemetry = {
        "seed": int(seed),
        "grid_shape": [GRID_ROWS, GRID_COLS],
        "cell_size_m": float(CELL_SIZE_M),
        "years_simulated": float(YEARS_SIMULATED),
        "timesteps": int(timesteps),
        "dt_years": float(max_dt_used_yr),
        "storm_count": int(len(storm_times)),
        "mean_annual_rain_mm": float(np.sum(storm_depths_scaled) / YEARS_SIMULATED),
        "creep_diffusivity_m2_per_yr": float(CREEP_D0_M2_YR),
        "open_boundaries": ["bottom"],
        "sediment_exported_m3": float(exported_total_m3),
        "uplift_or_baselevel_m3": float(uplift_m3),
        "mass_balance_error_pct": float(mass_balance_error_pct),
    }

    return {
        "z_initial": z_initial,
        "z_final": z,
        "veg": veg,
        "storm_times": storm_times,
        "storm_depths_unscaled": storm_depths_unscaled,
        "telemetry": telemetry,
        "snapshots": snapshots,
    }


def compute_hillshade(z: np.ndarray, ve: float = 2.5, az_deg: float = 315.0, alt_deg: float = 45.0) -> np.ndarray:
    """Compute Lambertian terrain hillshade in [0, 1] with vertical exaggeration ve."""
    dz_dy, dz_dx = np.gradient(z * ve, CELL_SIZE_M, CELL_SIZE_M)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dx, dz_dy)
    az = np.deg2rad(az_deg)
    alt = np.deg2rad(alt_deg)
    zenith = 0.5 * np.pi - alt
    hs = np.cos(zenith) * np.cos(slope) + np.sin(zenith) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(hs, 0.0, 1.0)


def write_static_map(out_dir: Path, res: dict) -> None:
    """Render static dryland hillslope teaching map (map.png)."""
    z0 = res["z_initial"]
    zf = res["z_final"]
    veg = res["veg"]
    dz = zf - z0
    flow_final = res["snapshots"][-1]["flow_area"]
    ve = 2.5
    hs = compute_hillshade(zf, ve=ve)

    # Custom dryland palettes (no default colormaps)
    dryland_terrain_cmap = LinearSegmentedColormap.from_list(
        "dryland_terrain",
        ["#e8dcb9", "#d8be89", "#c79658", "#ae6b3f", "#8a482d", "#5e3326"],
    )
    dryland_change_cmap = LinearSegmentedColormap.from_list(
        "dryland_change",
        ["#8c1d18", "#d95f3b", "#f6f2e8", "#5ea38c", "#1b5e63"],
    )
    dryland_veg_cmap = LinearSegmentedColormap.from_list(
        "dryland_veg",
        ["#eadec9", "#c8c68d", "#7fa059", "#3b6b35", "#1c4021"],
    )
    dryland_flow_cmap = LinearSegmentedColormap.from_list(
        "dryland_flow",
        ["#e7dcc8", "#c2b69c", "#6ca09d", "#287687", "#0d3d56"],
    )

    fig, axes = plt.subplots(2, 2, figsize=(13, 11), dpi=160, constrained_layout=True)
    fig.patch.set_facecolor("#f7f3eb")
    extent = [0.0, GRID_COLS * CELL_SIZE_M, GRID_ROWS * CELL_SIZE_M, 0.0]

    def blend_hillshade(rgb_img: np.ndarray, shade: np.ndarray, strength: float = 0.55) -> np.ndarray:
        factor = (1.0 - strength) + strength * (0.35 + 0.95 * shade)
        return np.clip(rgb_img[:, :, :3] * factor[:, :, None], 0.0, 1.0)

    # Panel 1: Final Terrain + Hillshade
    ax = axes[0, 0]
    z_norm = plt.Normalize(vmin=float(zf.min()), vmax=float(zf.max()))
    terrain_rgb = blend_hillshade(dryland_terrain_cmap(z_norm(zf)), hs, strength=0.60)
    ax.imshow(terrain_rgb, extent=extent, aspect="equal")
    sm1 = plt.cm.ScalarMappable(norm=z_norm, cmap=dryland_terrain_cmap)
    cb1 = fig.colorbar(sm1, ax=ax, fraction=0.046, pad=0.03)
    cb1.set_label("Elevation (m)", fontsize=9)
    ax.set_title(f"Final Terrain (t = {YEARS_SIMULATED:.0f} yr) | Hillshade VE = {ve:.1f}x", fontsize=10.5, fontweight="bold")

    # Panel 2: Elevation Change centered on zero
    ax = axes[0, 1]
    lim = max(0.05, float(np.percentile(np.abs(dz), 99.5)))
    dz_norm = TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)
    change_rgb = blend_hillshade(dryland_change_cmap(dz_norm(dz)), hs, strength=0.42)
    ax.imshow(change_rgb, extent=extent, aspect="equal")
    sm2 = plt.cm.ScalarMappable(norm=dz_norm, cmap=dryland_change_cmap)
    cb2 = fig.colorbar(sm2, ax=ax, fraction=0.046, pad=0.03)
    cb2.set_label("Elevation Change Δz (m) [<0 Erosion, >0 Deposition]", fontsize=9)
    ax.set_title("Cumulative Erosion & Deposition (centred on 0)", fontsize=10.5, fontweight="bold")

    # Panel 3: Vegetation Cover
    ax = axes[1, 0]
    v_norm = plt.Normalize(vmin=0.0, vmax=1.0)
    veg_rgb = blend_hillshade(dryland_veg_cmap(v_norm(veg)), hs, strength=0.35)
    ax.imshow(veg_rgb, extent=extent, aspect="equal")
    sm3 = plt.cm.ScalarMappable(norm=v_norm, cmap=dryland_veg_cmap)
    cb3 = fig.colorbar(sm3, ax=ax, fraction=0.046, pad=0.03)
    cb3.set_label("Vegetation Cover Fraction (0–1)", fontsize=9)
    ax.set_title("Patchy Dryland Vegetation Cover", fontsize=10.5, fontweight="bold")

    # Panel 4: Upslope Contributing Area (log10 m^2)
    ax = axes[1, 1]
    log_flow = np.log10(flow_final)
    f_norm = plt.Normalize(vmin=float(log_flow.min()), vmax=float(log_flow.max()))
    flow_rgb = blend_hillshade(dryland_flow_cmap(f_norm(log_flow)), hs, strength=0.38)
    ax.imshow(flow_rgb, extent=extent, aspect="equal")
    sm4 = plt.cm.ScalarMappable(norm=f_norm, cmap=dryland_flow_cmap)
    cb4 = fig.colorbar(sm4, ax=ax, fraction=0.046, pad=0.03)
    cb4.set_label("Upslope Contributing Area (log10 m²)", fontsize=9)
    ax.set_title("Routed Overland Flow Network", fontsize=10.5, fontweight="bold")

    for r_i in range(2):
        for c_i in range(2):
            cur = axes[r_i, c_i]
            cur.set_xlabel("Distance across slope (m)", fontsize=8.5)
            cur.set_ylabel("Distance downslope (m)", fontsize=8.5)
            # Draw 50 m scale bar in lower-left corner
            sb_x0, sb_y0 = 14.0, GRID_ROWS * CELL_SIZE_M - 14.0
            cur.plot([sb_x0, sb_x0 + 50.0], [sb_y0, sb_y0], color="#1c1917", lw=3.0)
            cur.plot([sb_x0, sb_x0 + 50.0], [sb_y0, sb_y0], color="#faf6ee", lw=1.2)
            cur.text(sb_x0 + 25.0, sb_y0 - 5.0, "50 m", color="#1c1917", fontsize=8,
                     ha="center", va="bottom", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.15", facecolor="#faf6ee", alpha=0.82, edgecolor="none"))

    tel = res["telemetry"]
    fig.suptitle(
        f"Dryland Hillslope Evolution (Seed {tel['seed']}, {tel['years_simulated']:.0f} yr, "
        f"{tel['storm_count']} storms, {tel['mean_annual_rain_mm']:.0f} mm/yr, "
        f"Exported: {tel['sediment_exported_m3']:.1f} m³)",
        fontsize=12.5,
        fontweight="bold",
        color="#2c221a",
    )
    fig.savefig(out_dir / "map.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def write_interactive_map(out_dir: Path, res: dict) -> None:
    """Generate a self-contained offline interactive HTML teaching tool (map.html)."""
    snaps = res["snapshots"]
    tel = res["telemetry"]
    def b64_f32(arr: np.ndarray) -> str:
        return base64.b64encode(np.ascontiguousarray(arr, dtype="<f4").tobytes()).decode("ascii")

    dz_final = res["z_final"] - res["z_initial"]
    dz_abs_max = max(0.05, float(np.percentile(np.abs(dz_final), 99.5)))
    z_min = float(min(s["z"].min() for s in snaps))
    z_max = float(max(s["z"].max() for s in snaps))
    log_flow_min = float(min(np.log10(s["flow_area"]).min() for s in snaps))
    log_flow_max = float(max(np.log10(s["flow_area"]).max() for s in snaps))

    payload = {
        "rows": GRID_ROWS,
        "cols": GRID_COLS,
        "dx": CELL_SIZE_M,
        "telemetry": tel,
        "zMin": z_min,
        "zMax": z_max,
        "dzLim": dz_abs_max,
        "flowMin": log_flow_min,
        "flowMax": log_flow_max,
        "veg": b64_f32(res["veg"]),
        "snapshots": [
            {
                "year": round(s["year"], 2),
                "exported_m3": round(s["exported_m3"], 2),
                "storms": s["storms_so_far"],
                "rain_mm": round(s["rain_mm_so_far"], 1),
                "z": b64_f32(s["z"]),
                "log_flow": b64_f32(np.log10(s["flow_area"])),
            }
            for s in snaps
        ],
    }

    data_json = json.dumps(payload, separators=(",", ":"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dryland Hillslope Erosion &amp; Deposition Lab</title>
<style>
  :root {{
    --bg: #f5efe4;
    --panel: #fcf9f2;
    --ink: #2a2118;
    --muted: #6b5b4b;
    --border: #d8cbb8;
    --accent: #a64b2a;
    --accent-soft: #efe1d1;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--ink);
    line-height: 1.45;
  }}
  header {{
    background: #33261b;
    color: #f8f2e7;
    padding: 14px 22px;
    border-bottom: 3px solid #b56538;
  }}
  header h1 {{
    margin: 0 0 4px 0;
    font-size: 1.35rem;
    letter-spacing: 0.01em;
  }}
  header p {{
    margin: 0;
    font-size: 0.88rem;
    color: #dfcfb9;
  }}
  .layout {{
    display: grid;
    grid-template-columns: minmax(420px, 640px) minmax(320px, 1fr);
    gap: 18px;
    padding: 18px 22px 28px;
    max-width: 1320px;
    margin: 0 auto;
  }}
  @media (max-width: 940px) {{
    .layout {{ grid-template-columns: 1fr; }}
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    box-shadow: 0 1px 4px rgba(42, 33, 24, 0.06);
  }}
  .map-wrap {{
    position: relative;
    width: 100%;
    aspect-ratio: 1 / 1;
    background: #e6dac8;
    border: 1px solid #b8a792;
    border-radius: 4px;
    overflow: hidden;
  }}
  canvas#map-canvas {{
    width: 100%;
    height: 100%;
    display: block;
    cursor: crosshair;
    image-rendering: pixelated;
  }}
  .map-badge {{
    position: absolute;
    background: rgba(252, 249, 242, 0.9);
    border: 1px solid #bfa98e;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--ink);
    pointer-events: none;
  }}
  #ve-badge {{ top: 10px; left: 10px; }}
  #boundary-top {{ top: 10px; right: 10px; font-weight: 500; }}
  #boundary-bottom {{
    bottom: 10px; right: 10px;
    background: rgba(166, 75, 42, 0.9);
    color: #fffaf2;
    border-color: #7d3318;
  }}
  #scale-bar {{
    position: absolute;
    bottom: 10px;
    left: 10px;
    background: rgba(252, 249, 242, 0.9);
    border: 1px solid #bfa98e;
    border-radius: 4px;
    padding: 5px 9px;
    pointer-events: none;
    font-size: 0.78rem;
    font-weight: 600;
  }}
  .scale-line {{
    height: 6px;
    border: 1px solid #2a2118;
    border-top: none;
    background: linear-gradient(90deg, #2a2118 50%, #faf6ee 50%);
    margin-bottom: 2px;
  }}
  .legend-box {{
    margin-top: 12px;
  }}
  .legend-title {{
    font-size: 0.85rem;
    font-weight: 700;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
  }}
  canvas#legend-canvas {{
    width: 100%;
    height: 16px;
    border: 1px solid #a89782;
    border-radius: 3px;
    display: block;
  }}
  .legend-ticks {{
    display: flex;
    justify-content: space-between;
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 3px;
    font-variant-numeric: tabular-nums;
  }}
  .controls-grid {{
    display: flex;
    flex-direction: column;
    gap: 14px;
  }}
  .control-group h2 {{
    font-size: 0.92rem;
    margin: 0 0 8px 0;
    color: #4f3a29;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .btn-row {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 7px;
  }}
  button {{
    font: inherit;
    font-size: 0.85rem;
    padding: 7px 10px;
    border-radius: 5px;
    border: 1px solid #b9a68f;
    background: #f3eadc;
    color: var(--ink);
    cursor: pointer;
    font-weight: 600;
  }}
  button:hover {{ background: #eadcc7; }}
  button.active {{
    background: var(--accent);
    color: #fff9f0;
    border-color: #7d3318;
  }}
  .slider-row {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .slider-row input[type="range"] {{
    flex: 1;
    accent-color: var(--accent);
  }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin-top: 8px;
    font-size: 0.83rem;
  }}
  .stat-item {{
    background: #f4ede1;
    border: 1px solid #dfd3c1;
    border-radius: 5px;
    padding: 6px 8px;
  }}
  .stat-item span {{
    display: block;
    font-size: 0.72rem;
    color: var(--muted);
  }}
  .stat-item strong {{
    font-size: 0.95rem;
    font-variant-numeric: tabular-nums;
  }}
  .toggle-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.86rem;
    margin-top: 6px;
  }}
  canvas#profile-canvas {{
    width: 100%;
    height: 135px;
    border: 1px solid #d5c8b6;
    border-radius: 4px;
    background: #fffdf9;
    display: block;
    margin-top: 8px;
  }}
  .explain-box h3 {{
    margin: 10px 0 4px 0;
    font-size: 0.92rem;
    color: #5c3a21;
  }}
  .explain-box ul {{
    margin: 4px 0 8px 18px;
    padding: 0;
    font-size: 0.84rem;
  }}
  .explain-box li {{ margin-bottom: 4px; }}
  .probe-line {{
    font-size: 0.82rem;
    color: var(--muted);
    margin-top: 6px;
    min-height: 1.3em;
    font-variant-numeric: tabular-nums;
  }}
</style>
</head>
<body>
<header>
  <h1>Dryland Hillslope Erosion &amp; Deposition Lab</h1>
  <p>Explore how rainstorms, soil creep, overland flow, and patchy desert vegetation sculpt a synthetic hillslope over {tel['years_simulated']:.0f} years.</p>
</header>

<main class="layout">
  <section class="card">
    <div class="map-wrap">
      <canvas id="map-canvas" width="{GRID_COLS}" height="{GRID_ROWS}"></canvas>
      <div id="ve-badge" class="map-badge">Vertical Exaggeration: <span id="ve-val">2.5</span>&times; (NW sun)</div>
      <div id="boundary-top" class="map-badge">Top/Sides: Closed</div>
      <div id="boundary-bottom" class="map-badge">Bottom Edge: Open Outlet</div>
      <div id="scale-bar">
        <div id="scale-line" class="scale-line" style="width: 80px;"></div>
        <span id="scale-label">40 m</span>
      </div>
    </div>

    <div class="legend-box">
      <div class="legend-title">
        <span id="legend-name">Terrain Elevation (m)</span>
        <span id="legend-units">m</span>
      </div>
      <canvas id="legend-canvas" width="256" height="16"></canvas>
      <div class="legend-ticks">
        <span id="tick-min">0.0</span>
        <span id="tick-mid">15.0</span>
        <span id="tick-max">30.0</span>
      </div>
    </div>

    <div class="probe-line" id="probe-readout">Click or move cursor over the map to inspect elevation, change, vegetation, and upslope area.</div>

    <div style="margin-top: 10px;">
      <strong style="font-size: 0.85rem;">Downslope Cross-Section Profile (along clicked column <span id="prof-col">{GRID_COLS // 2}</span>)</strong>
      <canvas id="profile-canvas" width="520" height="135"></canvas>
    </div>
  </section>

  <aside class="controls-grid">
    <div class="card control-group">
      <h2>1. Map Layer</h2>
      <div class="btn-row">
        <button type="button" class="layer-btn active" data-layer="terrain" data-bench>Terrain</button>
        <button type="button" class="layer-btn" data-layer="change" data-bench>Change (Erosion / Dep.)</button>
        <button type="button" class="layer-btn" data-layer="vegetation" data-bench>Vegetation Cover</button>
        <button type="button" class="layer-btn" data-layer="flow" data-bench>Overland Flow Area</button>
      </div>
    </div>

    <div class="card control-group">
      <h2>2. Time Evolution (Before &rarr; After)</h2>
      <div class="slider-row">
        <button type="button" id="play-btn" data-bench>Play</button>
        <input type="range" id="time-slider" min="0" max="{len(snaps) - 1}" step="1" value="{len(snaps) - 1}" data-bench>
        <strong id="time-readout" style="min-width: 68px; text-align: right;">{YEARS_SIMULATED:.0f} yr</strong>
      </div>
      <div class="stats-grid">
        <div class="stat-item"><span>Cumulative Storms</span><strong id="stat-storms">{tel['storm_count']}</strong></div>
        <div class="stat-item"><span>Cumulative Rainfall</span><strong id="stat-rain">0 mm</strong></div>
        <div class="stat-item"><span>Sediment Exported</span><strong id="stat-export">0 m&sup3;</strong></div>
        <div class="stat-item"><span>Max Erosion / Dep.</span><strong id="stat-minmax">0 / 0 m</strong></div>
      </div>
    </div>

    <div class="card control-group">
      <h2>3. Shading &amp; Overlays</h2>
      <div class="slider-row">
        <label for="ve-slider" style="font-size:0.85rem; min-width: 130px;">Vertical Exaggeration</label>
        <input type="range" id="ve-slider" min="1.0" max="5.0" step="0.5" value="2.5" data-bench>
        <strong id="ve-slider-val" style="min-width: 34px; text-align: right;">2.5&times;</strong>
      </div>
      <label class="toggle-row">
        <input type="checkbox" id="contour-toggle" data-bench>
        <span>Show 2 m elevation contours</span>
      </label>
      <label class="toggle-row">
        <input type="checkbox" id="veg-overlay-toggle" data-bench>
        <span>Highlight dense vegetation patches (&gt;50% cover)</span>
      </label>
    </div>

    <div class="card explain-box">
      <h2>How the Model Works &amp; What to Look For</h2>
      <h3>Model Assumptions</h3>
      <ul>
        <li><strong>Hillslope creep:</strong> Soil slowly diffuses downslope everywhere, smoothing ridges and filling hollows. Vegetation roots reduce creep rate.</li>
        <li><strong>Stochastic rainstorms:</strong> Rain arrives as discrete storms of random size. Only storms intense enough to exceed soil infiltration create overland runoff.</li>
        <li><strong>Overland flow &amp; deposition:</strong> Water routes downslope across multiple flow paths. Where flow discharge and slope are large, it erodes soil; where the slope flattens or water infiltrates, carried sediment deposits.</li>
        <li><strong>Patchy vegetation:</strong> Shrub/grass clumps absorb more rain (reducing runoff), armor the soil against erosion, and slow flow so sediment settles behind/inside patches.</li>
        <li><strong>Boundaries:</strong> Top and side edges are closed (no inflow or outflow). The bottom edge is an open channel outlet; every cubic metre exported is tracked.</li>
      </ul>
      <h3>Landforms to Spot</h3>
      <ul>
        <li><strong>Convex ridge crest (top):</strong> Gentle rounded summit shaped mainly by slow soil creep where contributing area is too small for runoff erosion.</li>
        <li><strong>Incised rills &amp; gullies (midslope):</strong> Linear red erosion channels in <em>Change</em> and bright streaks in <em>Flow</em> that carve through bare soil gaps between vegetation clumps.</li>
        <li><strong>Vegetated mounds / terracettes:</strong> Elevated green patches that resist erosion and trap sediment arriving from bare upslope interspaces.</li>
        <li><strong>Alluvial apron / fans (footslope):</strong> Teal/green depositional lobes near the lower third of the slope where the gradient flattens and flow drops its sediment load.</li>
      </ul>
    </div>
  </aside>
</main>

<script>
(function() {{
  const DATA = {data_json};
  const ROWS = DATA.rows;
  const COLS = DATA.cols;
  const DX = DATA.dx;
  const N = ROWS * COLS;

  function decodeF32(b64) {{
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Float32Array(bytes.buffer);
  }}

  const veg = decodeF32(DATA.veg);
  const snaps = DATA.snapshots.map(s => ({{
    year: s.year,
    exported_m3: s.exported_m3,
    storms: s.storms,
    rain_mm: s.rain_mm,
    z: decodeF32(s.z),
    log_flow: decodeF32(s.log_flow)
  }}));
  const z0 = snaps[0].z;

  // Dryland color ramps: [t, r, g, b]
  const RAMPS = {{
    terrain: [
      [0.00, 232, 220, 185],
      [0.20, 216, 190, 137],
      [0.45, 199, 150, 88],
      [0.70, 174, 107, 63],
      [0.88, 138, 72, 45],
      [1.00, 94, 51, 38]
    ],
    change: [
      [0.00, 140, 29, 24],
      [0.25, 217, 95, 59],
      [0.50, 246, 242, 232],
      [0.75, 94, 163, 140],
      [1.00, 27, 94, 99]
    ],
    vegetation: [
      [0.00, 234, 222, 201],
      [0.25, 200, 198, 141],
      [0.55, 127, 160, 89],
      [0.80, 59, 107, 53],
      [1.00, 28, 64, 33]
    ],
    flow: [
      [0.00, 231, 220, 200],
      [0.25, 194, 182, 156],
      [0.55, 108, 160, 157],
      [0.80, 40, 118, 135],
      [1.00, 13, 61, 86]
    ]
  }};

  function sampleRamp(ramp, t) {{
    if (t <= 0) return [ramp[0][1], ramp[0][2], ramp[0][3]];
    const last = ramp[ramp.length - 1];
    if (t >= 1) return [last[1], last[2], last[3]];
    for (let i = 0; i < ramp.length - 1; i++) {{
      const a = ramp[i], b = ramp[i + 1];
      if (t >= a[0] && t <= b[0]) {{
        const f = (t - a[0]) / (b[0] - a[0]);
        return [
          a[1] + f * (b[1] - a[1]),
          a[2] + f * (b[2] - a[2]),
          a[3] + f * (b[3] - a[3])
        ];
      }}
    }}
    return [last[1], last[2], last[3]];
  }}

  const mapCanvas = document.getElementById("map-canvas");
  const ctx = mapCanvas.getContext("2d");
  const imgData = ctx.createImageData(COLS, ROWS);
  const legCanvas = document.getElementById("legend-canvas");
  const legCtx = legCanvas.getContext("2d");
  const profCanvas = document.getElementById("profile-canvas");
  const profCtx = profCanvas.getContext("2d");

  let activeLayer = "terrain";
  let snapIdx = snaps.length - 1;
  let ve = 2.5;
  let showContours = false;
  let showVegOverlay = false;
  let profileCol = Math.floor(COLS / 2);
  let playTimer = null;

  function computeShade(z, veVal) {{
    const shade = new Float32Array(N);
    const az = 315 * Math.PI / 180;
    const alt = 45 * Math.PI / 180;
    const zen = 0.5 * Math.PI - alt;
    const cosZ = Math.cos(zen), sinZ = Math.sin(zen);
    for (let r = 0; r < ROWS; r++) {{
      const r0 = Math.max(0, r - 1), r1 = Math.min(ROWS - 1, r + 1);
      const dySpan = (r1 - r0) * DX;
      for (let c = 0; c < COLS; c++) {{
        const c0 = Math.max(0, c - 1), c1 = Math.min(COLS - 1, c + 1);
        const dxSpan = (c1 - c0) * DX;
        const dzdx = (z[r * COLS + c1] - z[r * COLS + c0]) * veVal / dxSpan;
        const dzdy = (z[r1 * COLS + c] - z[r0 * COLS + c]) * veVal / dySpan;
        const slope = Math.atan(Math.hypot(dzdx, dzdy));
        const aspect = Math.atan2(-dzdx, dzdy);
        let hs = cosZ * Math.cos(slope) + sinZ * Math.sin(slope) * Math.cos(az - aspect);
        shade[r * COLS + c] = Math.max(0, Math.min(1, hs));
      }}
    }}
    return shade;
  }}

  function drawLegend() {{
    const ramp = RAMPS[activeLayer];
    const w = legCanvas.width, h = legCanvas.height;
    const lImg = legCtx.createImageData(w, h);
    for (let x = 0; x < w; x++) {{
      const rgb = sampleRamp(ramp, x / (w - 1));
      for (let y = 0; y < h; y++) {{
        const p = (y * w + x) * 4;
        lImg.data[p] = rgb[0];
        lImg.data[p + 1] = rgb[1];
        lImg.data[p + 2] = rgb[2];
        lImg.data[p + 3] = 255;
      }}
    }}
    legCtx.putImageData(lImg, 0, 0);

    const nameEl = document.getElementById("legend-name");
    const unitEl = document.getElementById("legend-units");
    const tMin = document.getElementById("tick-min");
    const tMid = document.getElementById("tick-mid");
    const tMax = document.getElementById("tick-max");
    if (activeLayer === "terrain") {{
      nameEl.textContent = "Terrain Elevation";
      unitEl.textContent = "m";
      tMin.textContent = DATA.zMin.toFixed(1) + " m";
      tMid.textContent = ((DATA.zMin + DATA.zMax) * 0.5).toFixed(1) + " m";
      tMax.textContent = DATA.zMax.toFixed(1) + " m";
    }} else if (activeLayer === "change") {{
      nameEl.textContent = "Elevation Change (Erosion < 0, Deposition > 0)";
      unitEl.textContent = "m (centred on 0)";
      tMin.textContent = "-" + DATA.dzLim.toFixed(2) + " m";
      tMid.textContent = "0.00 m";
      tMax.textContent = "+" + DATA.dzLim.toFixed(2) + " m";
    }} else if (activeLayer === "vegetation") {{
      nameEl.textContent = "Vegetation Cover Fraction";
      unitEl.textContent = "0 to 1";
      tMin.textContent = "0.0 (bare)";
      tMid.textContent = "0.5";
      tMax.textContent = "1.0 (full cover)";
    }} else {{
      nameEl.textContent = "Upslope Contributing Area (log10)";
      unitEl.textContent = "log10(m^2)";
      tMin.textContent = Math.pow(10, DATA.flowMin).toFixed(0) + " m^2";
      tMid.textContent = Math.pow(10, 0.5 * (DATA.flowMin + DATA.flowMax)).toFixed(0) + " m^2";
      tMax.textContent = Math.pow(10, DATA.flowMax).toFixed(0) + " m^2";
    }}
  }}

  function drawProfile() {{
    const s = snaps[snapIdx];
    const zCur = s.z;
    const w = profCanvas.width, h = profCanvas.height;
    profCtx.clearRect(0, 0, w, h);
    const padL = 40, padR = 12, padT = 12, padB = 22;
    const pw = w - padL - padR, ph = h - padT - padB;
    const yMin = DATA.zMin - 0.5, yMax = DATA.zMax + 0.5;

    profCtx.strokeStyle = "#e4d8c8";
    profCtx.lineWidth = 1;
    for (let g = 0; g <= 3; g++) {{
      const gy = padT + (ph * g) / 3;
      profCtx.beginPath();
      profCtx.moveTo(padL, gy);
      profCtx.lineTo(w - padR, gy);
      profCtx.stroke();
    }}

    // Initial elevation (dashed)
    profCtx.strokeStyle = "#8a7968";
    profCtx.setLineDash([4, 3]);
    profCtx.lineWidth = 1.6;
    profCtx.beginPath();
    for (let r = 0; r < ROWS; r++) {{
      const px = padL + (r / (ROWS - 1)) * pw;
      const py = padT + (1 - (z0[r * COLS + profileCol] - yMin) / (yMax - yMin)) * ph;
      if (r === 0) profCtx.moveTo(px, py); else profCtx.lineTo(px, py);
    }}
    profCtx.stroke();

    // Current elevation (solid)
    profCtx.setLineDash([]);
    profCtx.strokeStyle = "#a64b2a";
    profCtx.lineWidth = 2.2;
    profCtx.beginPath();
    for (let r = 0; r < ROWS; r++) {{
      const px = padL + (r / (ROWS - 1)) * pw;
      const py = padT + (1 - (zCur[r * COLS + profileCol] - yMin) / (yMax - yMin)) * ph;
      if (r === 0) profCtx.moveTo(px, py); else profCtx.lineTo(px, py);
    }}
    profCtx.stroke();

    profCtx.fillStyle = "#4f3a29";
    profCtx.font = "11px sans-serif";
    profCtx.fillText(yMax.toFixed(0) + "m", 4, padT + 8);
    profCtx.fillText(yMin.toFixed(0) + "m", 4, h - padB);
    profCtx.fillText("Crest (0 m)", padL, h - 5);
    profCtx.fillText("Outlet (" + ((ROWS - 1) * DX).toFixed(0) + " m)", w - 82, h - 5);
    profCtx.fillStyle = "#8a7968";
    profCtx.fillText("-- Initial", w - 125, padT + 11);
    profCtx.fillStyle = "#a64b2a";
    profCtx.fillText("— t=" + s.year.toFixed(0) + " yr", w - 68, padT + 11);
    document.getElementById("prof-col").textContent = String(profileCol);
  }}

  function updateScaleBar() {{
    const rect = mapCanvas.getBoundingClientRect();
    const pxPerM = (rect.width > 0 ? rect.width : 500) / (COLS * DX);
    const barM = 50;
    document.getElementById("scale-line").style.width = Math.round(barM * pxPerM) + "px";
    document.getElementById("scale-label").textContent = barM + " m";
  }}

  function render() {{
    const s = snaps[snapIdx];
    const zCur = s.z;
    const flowCur = s.log_flow;
    const shade = computeShade(zCur, ve);
    const ramp = RAMPS[activeLayer];
    const shadeStrength = activeLayer === "terrain" ? 0.60 : (activeLayer === "change" ? 0.42 : 0.36);

    let minDz = 0, maxDz = 0;
    for (let i = 0; i < N; i++) {{
      const dz = zCur[i] - z0[i];
      if (dz < minDz) minDz = dz;
      if (dz > maxDz) maxDz = dz;
      let t = 0.0;
      if (activeLayer === "terrain") {{
        t = (zCur[i] - DATA.zMin) / Math.max(1e-6, DATA.zMax - DATA.zMin);
      }} else if (activeLayer === "change") {{
        t = 0.5 + 0.5 * (dz / DATA.dzLim);
      }} else if (activeLayer === "vegetation") {{
        t = veg[i];
      }} else {{
        t = (flowCur[i] - DATA.flowMin) / Math.max(1e-6, DATA.flowMax - DATA.flowMin);
      }}
      let rgb = sampleRamp(ramp, t);
      if (showVegOverlay && veg[i] > 0.5 && activeLayer !== "vegetation") {{
        rgb = [0.65 * rgb[0] + 0.35 * 45, 0.65 * rgb[1] + 0.35 * 102, 0.65 * rgb[2] + 0.35 * 42];
      }}
      if (showContours) {{
        const cBand = Math.floor(zCur[i] / 2.0);
        const r = Math.floor(i / COLS), c = i % COLS;
        if ((r + 1 < ROWS && Math.floor(zCur[i + COLS] / 2.0) !== cBand) ||
            (c + 1 < COLS && Math.floor(zCur[i + 1] / 2.0) !== cBand)) {{
          rgb = [rgb[0] * 0.45, rgb[1] * 0.45, rgb[2] * 0.45];
        }}
      }}
      const factor = (1.0 - shadeStrength) + shadeStrength * (0.35 + 0.95 * shade[i]);
      const p = i * 4;
      imgData.data[p] = Math.min(255, Math.max(0, rgb[0] * factor));
      imgData.data[p + 1] = Math.min(255, Math.max(0, rgb[1] * factor));
      imgData.data[p + 2] = Math.min(255, Math.max(0, rgb[2] * factor));
      imgData.data[p + 3] = 255;
    }}
    ctx.putImageData(imgData, 0, 0);

    // Draw subtle vertical column indicator for profile
    ctx.fillStyle = "rgba(166, 75, 42, 0.45)";
    ctx.fillRect(profileCol, 0, 1, ROWS);

    document.getElementById("time-readout").textContent = s.year.toFixed(0) + " yr";
    document.getElementById("stat-storms").textContent = String(s.storms);
    document.getElementById("stat-rain").textContent = s.rain_mm.toFixed(0) + " mm";
    document.getElementById("stat-export").textContent = s.exported_m3.toFixed(1) + " m3";
    document.getElementById("stat-minmax").textContent = minDz.toFixed(2) + " / +" + maxDz.toFixed(2) + " m";
    document.getElementById("ve-val").textContent = ve.toFixed(1);
    document.getElementById("ve-slider-val").textContent = ve.toFixed(1) + "x";

    drawLegend();
    drawProfile();
    updateScaleBar();
  }}

  document.querySelectorAll(".layer-btn").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".layer-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeLayer = btn.getAttribute("data-layer");
      render();
    }});
  }});

  const timeSlider = document.getElementById("time-slider");
  timeSlider.addEventListener("input", () => {{
    snapIdx = parseInt(timeSlider.value, 10);
    render();
  }});

  const playBtn = document.getElementById("play-btn");
  playBtn.addEventListener("click", () => {{
    if (playTimer !== null) {{
      clearInterval(playTimer);
      playTimer = null;
      playBtn.textContent = "Play";
    }} else {{
      if (snapIdx >= snaps.length - 1) snapIdx = 0;
      playBtn.textContent = "Pause";
      playTimer = setInterval(() => {{
        snapIdx = (snapIdx + 1) % snaps.length;
        timeSlider.value = String(snapIdx);
        render();
      }}, 550);
    }}
  }});

  const veSlider = document.getElementById("ve-slider");
  veSlider.addEventListener("input", () => {{
    ve = parseFloat(veSlider.value);
    render();
  }});

  document.getElementById("contour-toggle").addEventListener("change", (e) => {{
    showContours = e.target.checked;
    render();
  }});
  document.getElementById("veg-overlay-toggle").addEventListener("change", (e) => {{
    showVegOverlay = e.target.checked;
    render();
  }});

  function inspectAtEvent(ev) {{
    const rect = mapCanvas.getBoundingClientRect();
    const c = Math.max(0, Math.min(COLS - 1, Math.floor(((ev.clientX - rect.left) / rect.width) * COLS)));
    const r = Math.max(0, Math.min(ROWS - 1, Math.floor(((ev.clientY - rect.top) / rect.height) * ROWS)));
    const i = r * COLS + c;
    const s = snaps[snapIdx];
    const dz = s.z[i] - z0[i];
    const area = Math.pow(10, s.log_flow[i]);
    document.getElementById("probe-readout").textContent =
      `x=${{(c * DX).toFixed(0)}} m, y=${{(r * DX).toFixed(0)}} m | ` +
      `z=${{s.z[i].toFixed(2)}} m | Δz=${{dz >= 0 ? "+" : ""}}${{dz.toFixed(3)}} m | ` +
      `veg=${{(veg[i] * 100).toFixed(0)}}% | area=${{area.toFixed(0)}} m^2`;
    return c;
  }}

  mapCanvas.addEventListener("mousemove", inspectAtEvent);
  mapCanvas.addEventListener("click", (ev) => {{
    profileCol = inspectAtEvent(ev);
    render();
  }});

  window.addEventListener("resize", updateScaleBar);
  render();
}})();
</script>
</body>
</html>
"""
    (out_dir / "map.html").write_text(html, encoding="utf-8")


def write_outputs(out_dir: Path, res: dict, no_map: bool) -> None:
    """Create output directory and write simulation arrays, storms, telemetry, and maps."""
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "z_initial.npy", res["z_initial"].astype(np.float64))
    np.save(out_dir / "z_final.npy", res["z_final"].astype(np.float64))
    np.save(out_dir / "vegetation.npy", res["veg"].astype(np.float64))

    with (out_dir / "storms.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "depth_mm"])
        for t_yr, d_mm in zip(res["storm_times"], res["storm_depths_unscaled"]):
            writer.writerow([f"{t_yr:.6f}", f"{d_mm:.4f}"])

    with (out_dir / "telemetry.json").open("w", encoding="utf-8") as f:
        json.dump(res["telemetry"], f, indent=2)

    if not no_map:
        write_static_map(out_dir, res)
        write_interactive_map(out_dir, res)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dryland hillslope erosion and deposition simulator.")
    parser.add_argument("--seed", type=int, required=True, help="Random seed.")
    parser.add_argument("--out", type=str, required=True, help="Output directory.")
    parser.add_argument("--z0", type=str, default=None, help="Optional initial elevation .npy file.")
    parser.add_argument("--rain-scale", type=float, default=1.0, help="Multiplier for storm depths.")
    parser.add_argument("--veg-scale", type=float, default=1.0, help="Multiplier for vegetation cover.")
    parser.add_argument("--dt-scale", type=float, default=1.0, help="Time step scaling factor.")
    parser.add_argument("--no-map", action="store_true", help="Skip generating map.png and map.html.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.dt_scale <= 0.0:
        raise ValueError("--dt-scale must be positive.")
    if args.rain_scale < 0.0 or args.veg_scale < 0.0:
        raise ValueError("--rain-scale and --veg-scale must be non-negative.")

    res = run_simulation(
        seed=args.seed,
        z0_path=args.z0,
        rain_scale=args.rain_scale,
        veg_scale=args.veg_scale,
        dt_scale=args.dt_scale,
        capture_snapshots=not args.no_map,
    )
    write_outputs(Path(args.out), res, no_map=args.no_map)
    print(json.dumps(res["telemetry"], indent=2))


if __name__ == "__main__":
    main()
