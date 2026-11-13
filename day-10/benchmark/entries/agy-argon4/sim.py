#!/usr/bin/env python3
"""
sim.py — Interactive Dryland Hillslope Erosion & Deposition Simulator

Simulates the coupled geomorphic evolution of a synthetic dryland escarpment and
piedmont bajada (120 x 120 cells, 5 m grid spacing, 4,000 years across 160 timesteps)
driven by:
  1. Non-local conservative soil creep (hillslope diffusion modulated by vegetation).
  2. Overland flow routing (Priority-Flood depression filling + two-receiver multiple
     flow direction partitioning) with coupled detachment-transport-deposition (Davy &
     Lague 2009 / Tucker & Bras 2000 framework).
  3. Stochastic dryland convective storm arrivals (compound Poisson-Weibull rainfall).
  4. Patchy ecohydrological vegetation cover (banded and clumped dryland shrubland
     that increases critical shear resistance, reduces runoff generation, and responds
     to erosion/burial disturbance).

Usage:
    python3 sim.py --seed 42 --out OUTDIR
"""

import argparse
import base64
import heapq
import json
import os
import time
import zlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np
from scipy.ndimage import gaussian_filter


def build_neighbor_tables(ny: int, nx: int, dx: float):
    """Precompute 8-neighbor flat indices, distances, and contour weights."""
    dy_list = [-1, 1, 0, 0, -1, -1, 1, 1]
    dx_list = [0, 0, -1, 1, -1, 1, -1, 1]
    dist_list = [
        dx, dx, dx, dx,
        dx * np.sqrt(2.0), dx * np.sqrt(2.0),
        dx * np.sqrt(2.0), dx * np.sqrt(2.0),
    ]
    contour_w = [0.5, 0.5, 0.5, 0.5, 0.354, 0.354, 0.354, 0.354]

    n_cells = ny * nx
    grid_idx = np.arange(n_cells, dtype=np.int32).reshape(ny, nx)
    nbr_idx = np.full((8, n_cells), -1, dtype=np.int32)
    nbr_dist = np.array(dist_list, dtype=np.float64)[:, None]
    nbr_cw = np.array(contour_w, dtype=np.float64)[:, None]

    for k, (ddy, ddx) in enumerate(zip(dy_list, dx_list)):
        r_src = np.arange(max(0, -ddy), min(ny, ny - ddy))
        c_src = np.arange(max(0, -ddx), min(nx, nx - ddx))
        rr, cc = np.meshgrid(r_src, c_src, indexing="ij")
        nbr_idx[k, grid_idx[rr, cc].ravel()] = grid_idx[rr + ddy, cc + ddx].ravel()

    return nbr_idx, nbr_dist, nbr_cw


def route_and_fill(z: np.ndarray, nbr_idx: np.ndarray, ny: int, nx: int):
    """
    Priority-Flood depression filling and topological sorting (Barnes et al., 2014).
    Seeds the open southern boundary (row ny - 1) and floods inward, ensuring
    every cell has a strictly decreasing path to the southern outlet.
    Returns (z_fill_flat, topological_order_top_to_bottom).
    """
    n_cells = ny * nx
    z_flat = z.ravel()
    z_fill = z_flat.copy()
    visited = np.zeros(n_cells, dtype=bool)
    pq = []
    order = np.empty(n_cells, dtype=np.int32)
    out_ptr = 0

    start_idx = (ny - 1) * nx
    for idx in range(start_idx, n_cells):
        visited[idx] = True
        heapq.heappush(pq, (float(z_flat[idx]), idx))

    eps = 1e-4
    while pq:
        elev, idx = heapq.heappop(pq)
        order[out_ptr] = idx
        out_ptr += 1
        for k in range(8):
            nidx = nbr_idx[k, idx]
            if nidx >= 0 and not visited[nidx]:
                visited[nidx] = True
                nelev = float(z_flat[nidx])
                if nelev <= elev + eps:
                    nelev = elev + eps
                    z_fill[nidx] = nelev
                heapq.heappush(pq, (nelev, nidx))

    return z_fill, order[::-1]


def generate_initial_state(seed: int, ny: int, nx: int, dx: float, n_steps: int):
    """
    Deterministically generate initial dryland escarpment + piedmont topography,
    patchy shrubland vegetation, and stochastic storm series from a single seed.
    """
    rng = np.random.default_rng(seed)

    y = np.arange(ny, dtype=np.float64)[:, None] * dx
    x = np.arange(nx, dtype=np.float64)[None, :] * dx
    l_y = (ny - 1) * dx
    l_x = (nx - 1) * dx
    y_norm = y / l_y
    x_norm = x / l_x

    # Steep fault-bounded mountain front in upper 54% transitioning to gentle piedmont bajada
    s_upper = np.clip(1.0 - y_norm / 0.54, 0.0, 1.0)
    z_base = 88.0 * (s_upper ** 1.45) + 7.5 * ((1.0 - y_norm) ** 1.15)

    # Subtle structural embayments on the escarpment that focus runoff into three canyon-fan systems
    hollow_env = np.sin(np.pi * np.clip(y_norm / 0.56, 0.0, 1.0)) ** 1.35
    hollows = -6.5 * hollow_env * (
        1.05 * np.exp(-((x_norm - 0.22) / 0.085) ** 2)
        + 1.20 * np.exp(-((x_norm - 0.52) / 0.095) ** 2)
        + 0.95 * np.exp(-((x_norm - 0.80) / 0.085) ** 2)
    )

    # Multi-scale correlated surface roughness
    n1 = gaussian_filter(rng.standard_normal((ny, nx)), sigma=1.2)
    n2 = gaussian_filter(rng.standard_normal((ny, nx)), sigma=3.5)
    n3 = rng.standard_normal((ny, nx))
    rough = (
        0.55 * n1 / np.std(n1)
        + 0.95 * n2 / np.std(n2)
        + 0.10 * n3
    ) * (0.18 + 0.82 * s_upper)

    z0 = np.maximum(z_base + hollows + rough, 0.0).astype(np.float64)

    # Patchy dryland vegetation (banded tiger-bush / contour shrub clumps + random patches)
    v_raw1 = gaussian_filter(rng.standard_normal((ny, nx)), sigma=3.2)
    v_raw2 = gaussian_filter(rng.standard_normal((ny, nx)), sigma=1.1)
    bands = 0.35 * np.sin(2.0 * np.pi * y_norm * 9.0 + 1.5 * v_raw1 / np.std(v_raw1))
    v_field = 0.60 * (v_raw1 / np.std(v_raw1)) + 0.40 * (v_raw2 / np.std(v_raw2)) + bands
    veg0 = np.clip(1.0 / (1.0 + np.exp(-1.4 * (v_field - 0.15))), 0.02, 0.92).astype(np.float64)

    # Stochastic convective storm sequence: Poisson storm count + heavy-tailed Weibull storm depths
    storm_counts = rng.poisson(lam=4.5, size=n_steps)
    storm_intensity = np.zeros(n_steps, dtype=np.float64)
    max_single_storm_mm = np.zeros(n_steps, dtype=np.float64)
    for t in range(n_steps):
        k_storms = int(storm_counts[t])
        if k_storms > 0:
            depths = rng.weibull(0.75, size=k_storms)
            storm_intensity[t] = float(np.mean(depths ** 1.35) * (k_storms / 4.5))
            max_single_storm_mm[t] = float(np.max(depths) * 28.0)
        else:
            storm_intensity[t] = 0.05
            max_single_storm_mm[t] = 2.0

    return z0, veg0, storm_counts, storm_intensity, max_single_storm_mm


def run_simulation(
    z0: np.ndarray,
    veg0: np.ndarray,
    storm_intensity: np.ndarray,
    nbr_idx: np.ndarray,
    nbr_dist: np.ndarray,
    nbr_cw: np.ndarray,
    dx: float = 5.0,
    dt: float = 25.0,
    veg_scale: float = 1.0,
    rain_scale: float = 1.0,
    snapshot_steps=None,
):
    """
    Execute the coupled hillslope creep + overland flow erosion-deposition simulation.
    Maintains strict finite-volume conservation across the grid and open southern boundary.
    """
    ny, nx = z0.shape
    n_cells = ny * nx
    cell_area = dx * dx
    n_steps = len(storm_intensity)

    if snapshot_steps is None:
        snapshot_steps = set()
    else:
        snapshot_steps = set(snapshot_steps)

    z = z0.copy().astype(np.float64)
    veg_eq = np.clip(veg0 * veg_scale, 0.01, 0.95).astype(np.float64)
    veg = veg_eq.copy()

    # Physical parameters (calibrated to semiarid southwest US / Mediterranean badland-bajada rates)
    d0_creep = 0.0045       # Bare-soil hillslope diffusivity (m^2 / yr)
    alpha_veg = 0.45        # Root-cohesion reduction of soil creep
    k_detach = 0.0022       # Overland flow detachment coefficient (m / yr)
    k_trans = 0.052         # Sediment transport capacity coefficient
    beta_veg = 2.6          # Exponential vegetation shear protection factor
    m_exp = 1.30            # Discharge exponent for detachment
    n_exp = 1.35            # Slope exponent for detachment
    l_dep = 12.0            # Characteristic deposition length scale (m)
    exp_dep_fac = 1.0 - np.exp(-dx / l_dep)

    south_mask = np.zeros(n_cells, dtype=bool)
    south_mask[(ny - 1) * nx:] = True

    y_norm = (np.arange(ny, dtype=np.float64)[:, None] * dx) / ((ny - 1) * dx)
    # Alluvial fan transmission loss (infiltration into coarse piedmont gravels)
    trans_loss = np.broadcast_to(
        np.where(y_norm > 0.54, np.exp(-0.08 * (y_norm - 0.54) * 20.0), 1.0),
        (ny, nx),
    ).ravel()

    sed_exported_m3 = 0.0
    cum_eroded_m3_hist = [0.0]
    cum_deposited_m3_hist = [0.0]
    cum_exported_m3_hist = [0.0]

    snapshots = {}
    q_water_last = np.zeros((ny, nx), dtype=np.float64)

    if 0 in snapshot_steps:
        snapshots[0] = {
            "year": 0,
            "z": z.copy(),
            "dz": np.zeros_like(z),
            "veg": veg.copy(),
            "flow": np.ones_like(z) * cell_area,
        }

    # Routing cache variables
    z_fill = z.ravel().copy()
    order = np.argsort(z_fill)[::-1]
    r0 = np.full(n_cells, -1, dtype=np.int32)
    r1 = np.full(n_cells, -1, dtype=np.int32)
    w0 = np.zeros(n_cells, dtype=np.float64)
    w1 = np.zeros(n_cells, dtype=np.float64)
    part_idx = np.zeros((2, n_cells), dtype=np.int32)

    for step in range(n_steps):
        r_t = float(storm_intensity[step]) * rain_scale

        # 1. Conservative finite-volume hillslope creep (no-flux N/S/E/W boundaries)
        d_eff = d0_creep * (1.0 - alpha_veg * veg)
        d_x = 0.5 * (d_eff[:, :-1] + d_eff[:, 1:])
        flux_x = -d_x * (z[:, 1:] - z[:, :-1]) / dx
        d_y = 0.5 * (d_eff[:-1, :] + d_eff[1:, :])
        flux_y = -d_y * (z[1:, :] - z[:-1, :]) / dx

        z[:, :-1] -= (flux_x / dx) * dt
        z[:, 1:] += (flux_x / dx) * dt
        z[:-1, :] -= (flux_y / dx) * dt
        z[1:, :] += (flux_y / dx) * dt

        # 2. Priority-Flood depression filling & two-receiver MFD routing weights
        if step % 3 == 0:
            z_fill, order = route_and_fill(z, nbr_idx, ny, nx)
            z_nbr_fill = np.where(nbr_idx >= 0, z_fill[np.maximum(nbr_idx, 0)], np.inf)
            slopes_fill = np.maximum(0.0, (z_fill[None, :] - z_nbr_fill) / nbr_dist)
            raw_w = (slopes_fill ** 1.1) * nbr_cw
            raw_w[:, south_mask] = 0.0
            w_sum = np.sum(raw_w, axis=0)
            mfd_w = np.where(w_sum[None, :] > 0.0, raw_w / np.maximum(w_sum[None, :], 1e-30), 0.0)

            part_idx = np.argpartition(mfd_w, -2, axis=0)[-2:]
            r0 = nbr_idx[part_idx[1], np.arange(n_cells)]
            r1 = nbr_idx[part_idx[0], np.arange(n_cells)]
            w0 = mfd_w[part_idx[1], np.arange(n_cells)]
            w1 = mfd_w[part_idx[0], np.arange(n_cells)]
            w_tot = w0 + w1
            w0 = np.where(w_tot > 0.0, w0 / np.maximum(w_tot, 1e-30), 0.0)
            w1 = np.where(w_tot > 0.0, w1 / np.maximum(w_tot, 1e-30), 0.0)
            r0 = np.where(w0 > 0.0, r0, -1)
            r1 = np.where(w1 > 0.0, r1, -1)

        z_flat = z.ravel()
        z_r0 = np.where(r0 >= 0, z_flat[np.maximum(r0, 0)], z_flat)
        z_r1 = np.where(r1 >= 0, z_flat[np.maximum(r1, 0)], z_flat)
        d0 = nbr_dist[part_idx[1], 0]
        d1 = nbr_dist[part_idx[0], 0]
        s0 = np.maximum(0.0, (z_flat - z_r0) / d0)
        s1 = np.maximum(0.0, (z_flat - z_r1) / d1)
        s_eff = w0 * s0 + w1 * s1
        s_eff[south_mask] = np.maximum(
            0.003, (z_flat[(ny - 2) * nx : (ny - 1) * nx] - z_flat[(ny - 1) * nx : n_cells]) / dx
        )
        s_eff = np.where(z_fill > z_flat + 1e-5, 0.0005, np.maximum(s_eff, 0.0005))

        min_rec_z = np.minimum(
            np.where(r0 >= 0, z_r0, np.inf),
            np.where(r1 >= 0, z_r1, np.inf),
        )
        max_drop = np.where(np.isfinite(min_rec_z), np.maximum(0.0, (z_flat - min_rec_z) * 0.40), 0.15)

        # 3. Overland water routing (Hortonian infiltration excess modulated by vegetation & fan gravels)
        runoff_coeff = np.clip(1.0 - 0.35 * veg.ravel(), 0.25, 1.0)
        q_water = r_t * runoff_coeff * cell_area
        for idx in order:
            qw = q_water[idx]
            rec0 = r0[idx]
            if rec0 >= 0:
                q_water[rec0] += qw * w0[idx] * trans_loss[rec0]
                rec1 = r1[idx]
                if rec1 >= 0:
                    q_water[rec1] += qw * w1[idx] * trans_loss[rec1]

        q_water_last = (q_water / max(r_t, 1e-6)).reshape(ny, nx)
        a_norm = q_water / (cell_area * 10.0)
        veg_flat = veg.ravel()
        veg_factor = np.exp(-beta_veg * veg_flat)

        # 4. Coupled sediment detachment, transport capacity, and deposition
        e_pot = k_detach * veg_factor * (a_norm ** m_exp) * (s_eff ** n_exp)
        q_c = k_trans * (1.0 - 0.55 * veg_flat) * (a_norm ** 1.35) * (s_eff ** 1.85) * cell_area

        q_sed_in = np.zeros(n_cells, dtype=np.float64)
        dz_flow = np.zeros(n_cells, dtype=np.float64)

        for idx in order:
            q_in = q_sed_in[idx]
            q_cap = q_c[idx]
            if q_cap >= q_in:
                erode_m = min(
                    e_pot[idx] * (1.0 - q_in / (q_cap + 1e-12)) * dt,
                    max_drop[idx],
                    z_flat[idx],
                )
                dz_flow[idx] = -erode_m
                q_out = q_in + erode_m * cell_area / dt
            else:
                dep_vol = (q_in - q_cap) * dt * exp_dep_fac
                cap_m = max(0.03, (z_fill[idx] - z_flat[idx]) + 0.15)
                dep_m = min(dep_vol / cell_area, cap_m)
                dz_flow[idx] = +dep_m
                q_out = q_in - dep_m * cell_area / dt

            rec0 = r0[idx]
            if rec0 >= 0:
                q_sed_in[rec0] += q_out * w0[idx]
                rec1 = r1[idx]
                if rec1 >= 0:
                    q_sed_in[rec1] += q_out * w1[idx]
            else:
                sed_exported_m3 += q_out * dt

        z += dz_flow.reshape(ny, nx)

        # 5. Ecohydrological vegetation disturbance & moisture-assisted recovery
        dz_step = dz_flow.reshape(ny, nx)
        veg_disturb = np.exp(-2.8 * np.abs(dz_step))
        moisture_boost = 0.04 * np.clip(np.log10(np.maximum(q_water_last / cell_area, 1.0)) / 2.5, 0.0, 1.0)
        veg = np.clip(0.90 * veg * veg_disturb + 0.10 * (veg_eq + moisture_boost), 0.01, 0.95)

        dz_now = z - z0
        cum_eroded_m3_hist.append(float(-np.sum(dz_now[dz_now < 0.0]) * cell_area))
        cum_deposited_m3_hist.append(float(np.sum(dz_now[dz_now > 0.0]) * cell_area))
        cum_exported_m3_hist.append(float(sed_exported_m3))

        step_num = step + 1
        if step_num in snapshot_steps:
            snapshots[step_num] = {
                "year": int(step_num * dt),
                "z": z.copy(),
                "dz": dz_now.copy(),
                "veg": veg.copy(),
                "flow": q_water_last.copy(),
            }

    vol_init = float(np.sum(z0) * cell_area)
    vol_final = float(np.sum(z) * cell_area)
    dz_total = z - z0
    max_erosion_m = float(max(0.0, -np.min(dz_total)))
    max_deposition_m = float(max(0.0, np.max(dz_total)))
    mass_balance_error_pct = float(abs((vol_init - vol_final) - sed_exported_m3) / vol_init * 100.0)

    return {
        "z_final": z,
        "dz_total": dz_total,
        "veg_final": veg,
        "flow_final": q_water_last,
        "sediment_exported_m3": float(sed_exported_m3),
        "max_erosion_m": max_erosion_m,
        "max_deposition_m": max_deposition_m,
        "mass_balance_error_pct": mass_balance_error_pct,
        "vol_init_m3": vol_init,
        "vol_final_m3": vol_final,
        "cum_eroded_m3_hist": cum_eroded_m3_hist,
        "cum_deposited_m3_hist": cum_deposited_m3_hist,
        "cum_exported_m3_hist": cum_exported_m3_hist,
        "snapshots": snapshots,
    }


def compute_hillshade(z: np.ndarray, dx: float, azim_deg: float = 315.0, elev_deg: float = 42.0):
    """Compute analytical Lambertian hillshade in [0, 1] from NW sun illumination."""
    dz_dy, dz_dx = np.gradient(z, dx)
    # Note: row index increases southward, so north-up normal has +dz_dy
    azim = np.deg2rad(azim_deg)
    elev = np.deg2rad(elev_deg)
    lx = np.sin(azim) * np.cos(elev)
    ly = np.cos(azim) * np.cos(elev)
    lz = np.sin(elev)

    nx_v = -dz_dx
    ny_v = dz_dy
    nz_v = np.ones_like(z)
    norm = np.sqrt(nx_v ** 2 + ny_v ** 2 + nz_v ** 2)
    shade = (nx_v * lx + ny_v * ly + nz_v * lz) / norm
    return np.clip(0.55 * shade + 0.45, 0.0, 1.0)


def render_static_map(
    out_path: str,
    z0: np.ndarray,
    res: dict,
    dx: float,
    years: float,
    seed: int,
):
    """Render a multi-panel static teaching summary figure (map.png)."""
    z_final = res["z_final"]
    dz = res["dz_total"]
    veg = res["veg_final"]
    flow = res["flow_final"]
    ny, nx = z_final.shape
    extent = [0, nx * dx, 0, ny * dx]

    # Custom dryland terrain palette (playa sand -> desert ochre -> terracotta cliff -> sunlit limestone crest)
    dryland_colors = [
        (0.00, "#e9dcc4"),
        (0.14, "#d8bd8e"),
        (0.32, "#c69660"),
        (0.55, "#a86c43"),
        (0.78, "#824d34"),
        (0.92, "#9a7b69"),
        (1.00, "#f2ece1"),
    ]
    dryland_cmap = LinearSegmentedColormap.from_list("dryland_relief", dryland_colors, N=256)

    # Custom diverging erosion-deposition palette centered strictly at zero
    # Deep canyon rust-red (erosion) -> warm neutral parchment (0) -> rich alluvial teal-blue (deposition)
    erodep_colors = [
        (0.00, "#7a160c"),
        (0.25, "#c94a29"),
        (0.45, "#f0b799"),
        (0.50, "#f7f4ed"),
        (0.55, "#a6d8d4"),
        (0.75, "#2b8cbe"),
        (1.00, "#084081"),
    ]
    erodep_cmap = LinearSegmentedColormap.from_list("dryland_erodep", erodep_colors, N=256)

    # Dryland shrubland palette (bare desert crust -> sage/creosote shrub green)
    veg_colors = [
        (0.00, "#e5d5b7"),
        (0.30, "#c8bc8a"),
        (0.60, "#7fa053"),
        (1.00, "#2d5a27"),
    ]
    veg_cmap = LinearSegmentedColormap.from_list("dryland_veg", veg_colors, N=256)

    fig = plt.figure(figsize=(14.5, 10.5), dpi=160, facecolor="#faf6ee")
    gs = fig.add_gridspec(2, 2, left=0.06, right=0.95, top=0.89, bottom=0.07, wspace=0.22, hspace=0.25)

    fig.suptitle(
        f"Dryland Escarpment & Alluvial Bajada Evolution ({int(years):,d} Years | Seed {seed})",
        fontsize=15.5,
        fontweight="bold",
        color="#2b2118",
        y=0.96,
    )
    fig.text(
        0.5,
        0.925,
        "Coupled Hillslope Creep, Stochastic Convective Storms, Patchy Shrubland & Overland Sediment Routing",
        ha="center",
        fontsize=10.5,
        color="#5c4b3b",
    )

    # Panel A: Shaded Dryland Topography
    ax1 = fig.add_subplot(gs[0, 0])
    shade = compute_hillshade(z_final, dx, azim_deg=315.0, elev_deg=38.0)
    z_norm = np.clip((z_final - z_final.min()) / max(1e-6, z_final.max() - z_final.min()), 0.0, 1.0)
    rgb_terr = dryland_cmap(z_norm)[..., :3]
    # Blend colour relief with analytical hillshade
    rgb_shaded = np.clip(rgb_terr * (0.55 + 0.60 * shade[..., None]), 0.0, 1.0)
    ax1.imshow(rgb_shaded, extent=extent, origin="upper", aspect="equal")
    sm1 = plt.cm.ScalarMappable(
        cmap=dryland_cmap,
        norm=plt.Normalize(vmin=float(z_final.min()), vmax=float(z_final.max())),
    )
    cbar1 = fig.colorbar(sm1, ax=ax1, fraction=0.044, pad=0.03)
    cbar1.set_label("Elevation z (m)", fontsize=9, color="#2b2118")
    # Add contour lines
    y_coords = np.linspace((ny - 0.5) * dx, 0.5 * dx, ny)
    x_coords = np.linspace(0.5 * dx, (nx - 0.5) * dx, nx)
    ax1.contour(
        x_coords,
        y_coords,
        z_final,
        levels=np.arange(10, 95, 10),
        colors="#3a2818",
        linewidths=0.55,
        alpha=0.45,
    )
    ax1.set_title("A. Final Dryland Shaded Relief & Contours", fontsize=11, fontweight="bold", color="#2b2118")
    ax1.set_xlabel("Distance East (m)", fontsize=9)
    ax1.set_ylabel("Distance North (m)", fontsize=9)

    # Annotate key landforms on Panel A
    ax1.annotate(
        "Incised Feeder\nCanyons",
        xy=(310, 420),
        xytext=(430, 510),
        arrowprops=dict(arrowstyle="->", color="#2b2118", lw=1.2),
        fontsize=8.5,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.25", fc="#fff9ef", ec="#8c6d46", alpha=0.9),
    )
    ax1.annotate(
        "Coalescing Alluvial\nFans (Bajada)",
        xy=(310, 170),
        xytext=(415, 70),
        arrowprops=dict(arrowstyle="->", color="#2b2118", lw=1.2),
        fontsize=8.5,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.25", fc="#fff9ef", ec="#8c6d46", alpha=0.9),
    )

    # Panel B: Net Elevation Change (Erosion vs. Deposition centered on zero)
    ax2 = fig.add_subplot(gs[0, 1])
    vlim = max(float(np.percentile(np.abs(dz), 99.2)), 4.5)
    norm_dz = TwoSlopeNorm(vmin=-vlim, vcenter=0.0, vmax=vlim)
    im2 = ax2.imshow(dz, cmap=erodep_cmap, norm=norm_dz, extent=extent, origin="upper", aspect="equal")
    # Subtle hillshade overlay for topographic context
    ax2.imshow(shade, cmap="gray", extent=extent, origin="upper", aspect="equal", alpha=0.16)
    cbar2 = fig.colorbar(im2, ax=ax2, fraction=0.044, pad=0.03)
    cbar2.set_label("Net Elevation Change Δz (m)  [Erosion < 0 < Deposition]", fontsize=9, color="#2b2118")
    ax2.axhline(ny * dx * (1.0 - 0.54), color="#3a2818", ls="--", lw=0.9, alpha=0.65)
    ax2.text(
        15,
        ny * dx * (1.0 - 0.54) + 12,
        "Piedmont Slope Break (Canyon Mouths)",
        fontsize=8,
        color="#3a2818",
        fontstyle="italic",
    )
    ax2.set_title("B. Cumulative Erosion & Deposition (Zero-Centred)", fontsize=11, fontweight="bold", color="#2b2118")
    ax2.set_xlabel("Distance East (m)", fontsize=9)
    ax2.set_ylabel("Distance North (m)", fontsize=9)

    # Panel C: Patchy Dryland Shrubland & Overland Flow Network
    ax3 = fig.add_subplot(gs[1, 0])
    im3 = ax3.imshow(veg * 100.0, cmap=veg_cmap, vmin=0, vmax=95, extent=extent, origin="upper", aspect="equal")
    ax3.imshow(shade, cmap="gray", extent=extent, origin="upper", aspect="equal", alpha=0.18)
    # Overlay major overland flow paths where drainage area concentrates
    flow_log = np.log10(np.maximum(flow / (dx * dx), 1.0))
    flow_mask = np.ma.masked_where(flow_log < 1.15, flow_log)
    ax3.imshow(flow_mask, cmap="Blues", vmin=0.8, vmax=3.2, extent=extent, origin="upper", aspect="equal", alpha=0.72)
    cbar3 = fig.colorbar(im3, ax=ax3, fraction=0.044, pad=0.03)
    cbar3.set_label("Shrub / Grass Cover (%) + Blue Flow Network", fontsize=9, color="#2b2118")
    ax3.set_title("C. Patchy Vegetation Cover & Routed Drainage Network", fontsize=11, fontweight="bold", color="#2b2118")
    ax3.set_xlabel("Distance East (m)", fontsize=9)
    ax3.set_ylabel("Distance North (m)", fontsize=9)

    # Panel D: Topographic Swath Profile & Cumulative Mass Budget
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor("#fdfbf7")
    y_dist_from_ridge = np.arange(ny) * dx
    z0_mean = np.mean(z0, axis=1)
    zf_mean = np.mean(z_final, axis=1)
    zf_min = np.min(z_final, axis=1)
    zf_max = np.max(z_final, axis=1)

    ax4.fill_between(
        y_dist_from_ridge,
        zf_min,
        zf_max,
        color="#d8bd8e",
        alpha=0.38,
        label="Final Elevation Envelope (Canyon Floor to Interfluve)",
    )
    ax4.plot(y_dist_from_ridge, z0_mean, "--", color="#6e5a47", lw=1.8, label="Initial Mean Profile (t = 0 yr)")
    ax4.plot(y_dist_from_ridge, zf_mean, "-", color="#9e2f1b", lw=2.3, label=f"Final Mean Profile (t = {int(years):,d} yr)")
    ax4.axvline(0.54 * (ny - 1) * dx, color="#3a2818", ls=":", lw=1.1, alpha=0.7)
    ax4.text(0.54 * (ny - 1) * dx - 10, 26, "Mountain Front /\nFan Apex", fontsize=8, color="#3a2818", ha="right")

    eroded_m3 = res["cum_eroded_m3_hist"][-1]
    deposited_m3 = res["cum_deposited_m3_hist"][-1]
    exported_m3 = res["sediment_exported_m3"]
    err_pct = res["mass_balance_error_pct"]
    budget_txt = (
        f"Sediment Mass Budget ({int(years):,d} yr):\n"
        f"• Total Eroded Upslope:  {eroded_m3:,.0f} m³\n"
        f"• Deposited on Bajada:   {deposited_m3:,.0f} m³ ({deposited_m3/max(1.0, eroded_m3)*100:.1f}%)\n"
        f"• Exported (South Edge): {exported_m3:,.0f} m³ ({exported_m3/max(1.0, eroded_m3)*100:.1f}%)\n"
        f"• Max Canyon Incision:   {res['max_erosion_m']:.2f} m\n"
        f"• Max Fan Aggradation:   {res['max_deposition_m']:.2f} m\n"
        f"• Mass Balance Error:    {err_pct:.2e} %"
    )
    ax4.text(
        0.46,
        0.44,
        budget_txt,
        transform=ax4.transAxes,
        fontsize=8.2,
        family="monospace",
        bbox=dict(boxstyle="round,pad=0.45", fc="#f6efe2", ec="#b59b78", alpha=0.95),
    )

    ax4.set_title("D. North–South Longitudinal Swath Profile & Mass Balance", fontsize=11, fontweight="bold", color="#2b2118")
    ax4.set_xlabel("Distance Downslope from Northern Divide (m)", fontsize=9)
    ax4.set_ylabel("Elevation (m)", fontsize=9)
    ax4.set_xlim(0, (ny - 1) * dx)
    ax4.set_ylim(0, max(98.0, float(z0.max()) + 4.0))
    ax4.grid(True, ls=":", alpha=0.45, color="#8c7862")
    ax4.legend(loc="upper right", fontsize=8, framealpha=0.92)

    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def quantize_array_b64(arr: np.ndarray, decimals: int = 2) -> list:
    """Round 2D array to compact Python nested list of floats for JSON embedding."""
    return np.round(arr, decimals).tolist()


def build_interactive_html(
    out_path: str,
    z0: np.ndarray,
    veg0: np.ndarray,
    storm_counts: np.ndarray,
    storm_intensity: np.ndarray,
    max_single_storm_mm: np.ndarray,
    baseline_res: dict,
    param_scenarios: dict,
    telemetry: dict,
    dx: float,
    dt: float,
):
    """
    Build a self-contained offline interactive HTML5 teaching laboratory (map.html).
    Lets students explore:
      1. Time evolution (0 to 4,000 years across 9 saved time snapshots + play/pause).
      2. Surface layers (Dryland Shaded Relief, Erosion/Deposition Δz, Patchy Vegetation,
         Overland Flow Drainage Area, and Combined Terrain + Δz).
      3. Parameter experiments (Climate Storminess x0.5 / x1.0 / x1.8 and Shrub Cover
         Sparse x0.4 / Baseline x1.0 / Dense x1.6) precomputed from the exact same physical solver.
      4. Interactive cross-section profiler (hover/click any row/column to inspect cell
         elevation, Δz, slope, vegetation, discharge, and longitudinal/transverse profiles).
    """
    ny, nx = z0.shape
    snap_keys = sorted(baseline_res["snapshots"].keys())
    time_frames = []
    for k in snap_keys:
        s = baseline_res["snapshots"][k]
        time_frames.append({
            "step": int(k),
            "year": int(s["year"]),
            "z": quantize_array_b64(s["z"], 2),
            "dz": quantize_array_b64(s["dz"], 2),
            "veg": quantize_array_b64(s["veg"] * 100.0, 1),
            "flow": quantize_array_b64(np.log10(np.maximum(s["flow"] / (dx * dx), 1.0)), 2),
        })

    scenario_payload = {}
    for key, sres in param_scenarios.items():
        scenario_payload[key] = {
            "label": sres["label"],
            "subtitle": sres["subtitle"],
            "z": quantize_array_b64(sres["z_final"], 2),
            "dz": quantize_array_b64(sres["dz_total"], 2),
            "veg": quantize_array_b64(sres["veg_final"] * 100.0, 1),
            "flow": quantize_array_b64(np.log10(np.maximum(sres["flow_final"] / (dx * dx), 1.0)), 2),
            "max_erosion_m": round(sres["max_erosion_m"], 2),
            "max_deposition_m": round(sres["max_deposition_m"], 2),
            "exported_m3": round(sres["sediment_exported_m3"], 0),
            "eroded_m3": round(sres["cum_eroded_m3_hist"][-1], 0),
            "deposited_m3": round(sres["cum_deposited_m3_hist"][-1], 0),
            "mass_err_pct": sres["mass_balance_error_pct"],
        }

    embedded_data = {
        "meta": {
            "seed": telemetry["seed"],
            "ny": ny,
            "nx": nx,
            "dx": dx,
            "dt": dt,
            "years": telemetry["years_simulated"],
            "timesteps": telemetry["timesteps"],
            "max_erosion_m": round(telemetry["max_erosion_m"], 2),
            "max_deposition_m": round(telemetry["max_deposition_m"], 2),
            "sediment_exported_m3": round(telemetry["sediment_exported_m3"], 1),
            "mass_balance_error_pct": telemetry["mass_balance_error_pct"],
        },
        "z0": quantize_array_b64(z0, 2),
        "storms": {
            "years": [int((i + 1) * dt) for i in range(len(storm_intensity))],
            "intensity": [round(float(x), 3) for x in storm_intensity],
            "counts": [int(x) for x in storm_counts],
            "max_mm": [round(float(x), 1) for x in max_single_storm_mm],
            "cum_eroded": [round(float(x), 0) for x in baseline_res["cum_eroded_m3_hist"][1:]],
            "cum_deposited": [round(float(x), 0) for x in baseline_res["cum_deposited_m3_hist"][1:]],
            "cum_exported": [round(float(x), 0) for x in baseline_res["cum_exported_m3_hist"][1:]],
        },
        "frames": time_frames,
        "scenarios": scenario_payload,
    }

    data_json = json.dumps(embedded_data, separators=(",", ":"))

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dryland Hillslope Erosion &amp; Deposition — Interactive Geomorphology Lab</title>
<style>
  :root {{
    --bg: #f6f1e6;
    --panel: #fffcf5;
    --border: #d5c4a8;
    --ink: #2a2017;
    --muted: #655241;
    --accent: #a63a1f;
    --accent-teal: #1d6f8a;
    --accent-green: #3c6e31;
    --highlight: #efe4ce;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Georgia, sans-serif;
    background: var(--bg);
    color: var(--ink);
    line-height: 1.48;
  }}
  header {{
    background: linear-gradient(135deg, #3a2618 0%, #613d25 55%, #825332 100%);
    color: #fdf8ee;
    padding: 16px 24px;
    border-bottom: 3px solid #c69660;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }}
  header h1 {{
    margin: 0;
    font-size: 1.35rem;
    letter-spacing: 0.01em;
  }}
  header p {{
    margin: 4px 0 0 0;
    font-size: 0.9rem;
    color: #ebd9be;
  }}
  .badge-bar {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .badge {{
    background: rgba(255, 248, 234, 0.14);
    border: 1px solid rgba(255, 248, 234, 0.32);
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-family: monospace;
  }}
  .container {{
    max-width: 1460px;
    margin: 0 auto;
    padding: 16px 20px 32px 20px;
  }}
  .top-grid {{
    display: grid;
    grid-template-columns: 340px 1fr 370px;
    gap: 16px;
    align-items: start;
  }}
  @media (max-width: 1180px) {{
    .top-grid {{ grid-template-columns: 1fr; }}
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 2px 6px rgba(42, 32, 23, 0.05);
  }}
  .card h2 {{
    margin: 0 0 10px 0;
    font-size: 1.02rem;
    color: #3a2618;
    border-bottom: 1px solid #e6d9c3;
    padding-bottom: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .control-group {{
    margin-bottom: 14px;
  }}
  .control-group label {{
    display: block;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--muted);
    margin-bottom: 5px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  .btn-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  button {{
    cursor: pointer;
    border: 1px solid #bfaa8b;
    background: #f5ecdc;
    color: var(--ink);
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 0.83rem;
    font-weight: 600;
    transition: all 0.12s ease;
  }}
  button:hover {{
    background: #eadbc2;
  }}
  button.active {{
    background: var(--accent);
    color: #fff;
    border-color: #7d2812;
  }}
  button.scen-btn.active {{
    background: var(--accent-teal);
    border-color: #124d61;
    color: #fff;
  }}
  button.landform-btn {{
    text-align: left;
    width: 100%;
    padding: 7px 10px;
    margin-bottom: 5px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  button.landform-btn.active {{
    background: #5b3a22;
    border-color: #3a2618;
    color: #fff;
  }}
  input[type="range"] {{
    width: 100%;
    accent-color: var(--accent);
    cursor: pointer;
  }}
  .map-stage {{
    display: flex;
    flex-direction: column;
    align-items: center;
  }}
  .canvas-wrap {{
    position: relative;
    width: 100%;
    max-width: 580px;
    aspect-ratio: 1 / 1;
    border: 2px solid #6e5239;
    border-radius: 8px;
    overflow: hidden;
    background: #e5d5b7;
    cursor: crosshair;
  }}
  canvas.map-canvas {{
    width: 100%;
    height: 100%;
    display: block;
  }}
  .colorbar-box {{
    width: 100%;
    max-width: 580px;
    margin-top: 8px;
    padding: 6px 10px;
    background: #f8f1e3;
    border: 1px solid var(--border);
    border-radius: 6px;
  }}
  .colorbar-grad {{
    height: 12px;
    border-radius: 4px;
    border: 1px solid #8c765c;
    margin-bottom: 4px;
  }}
  .colorbar-labels {{
    display: flex;
    justify-content: space-between;
    font-size: 0.76rem;
    font-family: monospace;
    color: var(--ink);
  }}
  .stat-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-top: 8px;
  }}
  .stat-cell {{
    background: #f6efe2;
    border: 1px solid #dfd0b8;
    border-radius: 6px;
    padding: 7px 9px;
  }}
  .stat-cell .k {{
    font-size: 0.72rem;
    color: var(--muted);
    text-transform: uppercase;
  }}
  .stat-cell .v {{
    font-size: 0.96rem;
    font-weight: 700;
    font-family: monospace;
    margin-top: 2px;
  }}
  .inspect-box {{
    font-family: monospace;
    font-size: 0.8rem;
    background: #f5ede0;
    border: 1px solid #d8c6ab;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 10px;
  }}
  .chart-canvas {{
    width: 100%;
    height: 155px;
    border: 1px solid #dfd0b8;
    border-radius: 6px;
    background: #fdfaf3;
    display: block;
    margin-bottom: 10px;
  }}
  .guide-section {{
    margin-top: 18px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 16px;
  }}
  .guide-card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
  }}
  .guide-card h3 {{
    margin: 0 0 8px 0;
    font-size: 1rem;
    color: #4a2e1b;
  }}
  .guide-card p, .guide-card li {{
    font-size: 0.87rem;
    color: #362a1f;
  }}
  .guide-card ul {{
    margin: 6px 0;
    padding-left: 18px;
  }}
  .formula {{
    font-family: monospace;
    background: #f3ead8;
    padding: 6px 9px;
    border-radius: 5px;
    font-size: 0.81rem;
    margin: 6px 0;
    border-left: 3px solid var(--accent);
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Dryland Hillslope Erosion &amp; Deposition — Interactive Teaching Map</h1>
    <p>Explore how stochastic desert storms, patchy shrubland, soil creep, and overland flow sculpt canyons and alluvial fans</p>
  </div>
  <div class="badge-bar">
    <span class="badge">Grid: {ny}&times;{nx} ({dx:.0f}m cells)</span>
    <span class="badge">Span: {int(telemetry["years_simulated"]):,d} yr ({telemetry["timesteps"]} steps)</span>
    <span class="badge">Seed: {telemetry["seed"]}</span>
    <span class="badge">Mass Error: {telemetry["mass_balance_error_pct"]:.2e}%</span>
  </div>
</header>

<div class="container">
  <div class="top-grid">
    <!-- LEFT COLUMN: CONTROLS -->
    <div class="card">
      <h2>1. Map Layer &amp; Relief</h2>
      <div class="control-group">
        <label>Select Surface Layer</label>
        <div class="btn-row" id="layerButtons">
          <button data-layer="terrain" class="active">Dryland Terrain (z)</button>
          <button data-layer="dz">Erosion / Deposition (&Delta;z)</button>
          <button data-layer="combo">Shaded Terrain + &Delta;z</button>
          <button data-layer="veg">Patchy Shrub Cover</button>
          <button data-layer="flow">Overland Flow Network</button>
        </div>
      </div>

      <div class="control-group">
        <label>Sun Azimuth (<span id="azimVal">315</span>&deg;) &amp; Vertical Relief Shading</label>
        <input type="range" id="azimSlider" min="0" max="360" value="315" step="5">
        <div style="display:flex; gap:12px; margin-top:6px; font-size:0.81rem;">
          <label style="text-transform:none; font-weight:normal; margin:0;">
            <input type="checkbox" id="chkContours" checked> Elevation Contours (10m)
          </label>
          <label style="text-transform:none; font-weight:normal; margin:0;">
            <input type="checkbox" id="chkRivers"> Overlay Channels
          </label>
        </div>
      </div>

      <h2>2. Time Evolution (Before &rarr; After)</h2>
      <div class="control-group">
        <label>Simulation Time: <span id="yearLabel" style="color:var(--accent); font-weight:700;">{int(telemetry["years_simulated"]):,d} yr</span></label>
        <input type="range" id="timeSlider" min="0" max="{len(time_frames)-1}" value="{len(time_frames)-1}" step="1">
        <div class="btn-row" style="margin-top:6px;">
          <button id="btnPlay">&#9654; Play Evolution</button>
          <button id="btnBefore">t = 0 yr (Initial)</button>
          <button id="btnAfter">t = {int(telemetry["years_simulated"]):,d} yr (Final)</button>
        </div>
      </div>

      <h2>3. Parameter Experiments (Sensitivity)</h2>
      <div class="control-group">
        <label>Compare Coupled Climate &amp; Vegetation Runs</label>
        <div class="btn-row" id="scenarioButtons">
          <button class="scen-btn active" data-scen="baseline">Baseline Run</button>
          <button class="scen-btn" data-scen="arid_storms">Calm Arid (0.55&times; Rain)</button>
          <button class="scen-btn" data-scen="intense_storms">Intense Storms (1.65&times; Rain)</button>
          <button class="scen-btn" data-scen="sparse_veg">Degraded Shrubs (0.35&times; Veg)</button>
          <button class="scen-btn" data-scen="dense_veg">Dense Shrubs (1.55&times; Veg)</button>
        </div>
        <div id="scenDesc" style="font-size:0.79rem; color:var(--muted); margin-top:6px; background:#f6efe2; padding:6px 8px; border-radius:5px;">
          Baseline dryland climate and patchy shrub cover (time slider active).
        </div>
      </div>

      <h2>4. Landform Field Guide (Click to Locate)</h2>
      <div class="control-group" style="margin-bottom:0;">
        <button class="landform-btn" data-lf="divide">
          <span>&#9650; 1. Creep-Rounded Crest &amp; Spurs</span>
          <span style="font-size:0.74rem; opacity:0.8;">y &approx; 550m</span>
        </button>
        <button class="landform-btn" data-lf="canyons">
          <span>&#9660; 2. Incised Feeder Canyons</span>
          <span style="font-size:0.74rem; opacity:0.8;">y &approx; 410m</span>
        </button>
        <button class="landform-btn" data-lf="apices">
          <span>&#9670; 3. Canyon Mouths &amp; Fan Apices</span>
          <span style="font-size:0.74rem; opacity:0.8;">y &approx; 270m</span>
        </button>
        <button class="landform-btn" data-lf="bajada">
          <span>&#9679; 4. Coalescing Alluvial Bajada</span>
          <span style="font-size:0.74rem; opacity:0.8;">y &approx; 145m</span>
        </button>
        <button class="landform-btn" data-lf="shrubs">
          <span>&#10047; 5. Vegetation-Protected Islands</span>
          <span style="font-size:0.74rem; opacity:0.8;">y &approx; 350m</span>
        </button>
      </div>
    </div>

    <!-- CENTER COLUMN: INTERACTIVE MAP CANVAS -->
    <div class="card map-stage">
      <h2 style="width:100%;">
        <span id="mapTitleText">Final Dryland Shaded Relief (t = 4,000 yr)</span>
        <span style="font-size:0.78rem; font-weight:normal; color:var(--muted);">Hover or click map to slice profiles</span>
      </h2>
      <div class="canvas-wrap" id="canvasWrap">
        <canvas id="mapCanvas" class="map-canvas" width="480" height="480"></canvas>
      </div>
      <div class="colorbar-box">
        <div id="cbarGrad" class="colorbar-grad"></div>
        <div class="colorbar-labels">
          <span id="cbarMin">0.0 m</span>
          <span id="cbarMid">45.0 m</span>
          <span id="cbarMax">95.0 m</span>
        </div>
      </div>

      <div class="stat-grid" style="width:100%; max-width:580px;">
        <div class="stat-cell">
          <div class="k">Max Canyon Erosion</div>
          <div class="v" id="statErosion" style="color:#9e2412;">-16.77 m</div>
        </div>
        <div class="stat-cell">
          <div class="k">Max Fan Deposition</div>
          <div class="v" id="statDeposition" style="color:#155d82;">+4.72 m</div>
        </div>
        <div class="stat-cell">
          <div class="k">Deposited on Bajada</div>
          <div class="v" id="statBajadaVol">0 m&sup3;</div>
        </div>
        <div class="stat-cell">
          <div class="k">Exported (South Edge)</div>
          <div class="v" id="statExportVol">0 m&sup3;</div>
        </div>
      </div>
    </div>

    <!-- RIGHT COLUMN: CROSS-SECTIONS & STORM TELEMETRY -->
    <div class="card">
      <h2>Cell Inspector &amp; Cross-Sections</h2>
      <div class="inspect-box" id="inspectBox">
        Move cursor over the map or click to lock a cross-section coordinate.
      </div>

      <label style="font-size:0.78rem; font-weight:700; color:var(--muted); display:block; margin-bottom:4px;">
        NORTH&ndash;SOUTH PROFILE (ALONG SELECTED X COLUMN)
      </label>
      <canvas id="nsProfileCanvas" class="chart-canvas" width="340" height="150"></canvas>

      <label style="font-size:0.78rem; font-weight:700; color:var(--muted); display:block; margin-bottom:4px;">
        WEST&ndash;EAST TRANSECT (ACROSS SELECTED Y ROW: CANYONS &amp; FANS)
      </label>
      <canvas id="weProfileCanvas" class="chart-canvas" width="340" height="150"></canvas>

      <label style="font-size:0.78rem; font-weight:700; color:var(--muted); display:block; margin-bottom:4px;">
        RANDOM CONVECTIVE STORMS &amp; CUMULATIVE SEDIMENT BUDGET
      </label>
      <canvas id="stormCanvas" class="chart-canvas" width="340" height="145"></canvas>
    </div>
  </div>

  <!-- STUDENT EXPLANATION & GEOMORPHOLOGY GUIDE -->
  <div class="guide-section">
    <div class="guide-card">
      <h3>What This Model Assumes (Plain-Language Physics)</h3>
      <p>
        Dryland landscapes evolve through a tug-of-war between slow diffusive soil movement on hillslopes and episodic, flash-flood sediment transport during convective desert storms:
      </p>
      <div class="formula">
        &part;z/&part;t = &nabla;&middot;[D(V)&nabla;z] &minus; E<sub>flow</sub> + D<sub>flow</sub>
      </div>
      <ul>
        <li><strong>1. Hillslope Creep (Soil Diffusion):</strong> Freeze-thaw, wetting-drying, and burrowing organisms slowly nudge soil grains downslope at a rate proportional to local slope (&nabla;z). Root networks in shrub patches bind the regolith and reduce creep diffusivity <em>D(V)</em>.</li>
        <li><strong>2. Stochastic Desert Storms:</strong> Instead of steady drizzle, dryland rain arrives as random convective storm clusters (modeled via a Poisson storm-arrival process with heavy-tailed Weibull storm depths). Rare, intense cloudbursts generate Hortonian overland flow that does most of the geomorphic work.</li>
        <li><strong>3. Overland Flow &amp; Sediment Routing:</strong> Runoff routes downslope across the surface, accumulating upslope contributing area <em>A</em>. Where transport capacity <em>Q<sub>c</sub> &propto; A<sup>1.35</sup>S<sup>1.85</sup></em> exceeds incoming sediment flux <em>Q<sub>in</sub></em>, flow detaches sediment and carves canyons. Where slope <em>S</em> drops at the mountain front, <em>Q<sub>c</sub></em> plummets below <em>Q<sub>in</sub></em> and sediment is deposited—never deleted!</li>
        <li><strong>4. Patchy Vegetation Feedback:</strong> Semiarid shrubs grow in banded and spotted patches that shield the soil from grain detachment (exponentially reducing erodibility) and absorb runoff, while intense canyon incision or rapid fan burial disturbs plant cover.</li>
      </ul>
    </div>

    <div class="guide-card">
      <h3>Which Landforms to Look For on the Map</h3>
      <ul>
        <li><strong>Creep-Rounded Interfluves &amp; Ridge Spurs (North, y &gt; 480 m):</strong> Near the top divide, contributing area <em>A</em> is tiny so overland flow cannot incise. Soil creep dominates, smoothing sharp roughness into convex, rounded ridge crests.</li>
        <li><strong>V-Shaped Feeder Canyons (Escarpment, y = 280&ndash;480 m):</strong> Three subtle structural hollows collect overland flow. Positive feedback between drainage area and incision carves deep, steep-walled feeder canyons (deep rust-red on the <em>&Delta;z</em> layer, losing up to 16+ m of rock/regolith).</li>
        <li><strong>Alluvial Fan Apices at the Slope Break (y &approx; 270 m):</strong> As confined canyon floods exit the steep escarpment onto the gentle piedmont plain, slope <em>S</em> drops abruptly and water infiltrates into coarse gravels. Transport capacity collapses, dumping coarse sediment right at the canyon mouths.</li>
        <li><strong>Coalescing Alluvial Bajada (South Piedmont, y = 0&ndash;260 m):</strong> Over thousands of years, sediment cones radiating from adjacent canyon mouths spread laterally via multiple-flow-direction avulsions and merge into a continuous depositional apron (<em>bajada</em>, shown in rich teal-blue on the <em>&Delta;z</em> layer gaining +1 to +5 m).</li>
        <li><strong>Vegetation-Protected Micro-Highs:</strong> Toggle between <em>Patchy Shrub Cover</em> and <em>Erosion / Deposition</em>—dense shrub patches resist sheetwash erosion, leaving subtle raised islands and deflecting rills around root-bound mounds.</li>
      </ul>
    </div>

    <div class="guide-card">
      <h3>Suggested Student Exploration Activities</h3>
      <ul>
        <li><strong>Activity 1 — Track Conservation of Mass Over Time:</strong> Switch to the <em>Erosion / Deposition (&Delta;z)</em> layer and drag the <strong>Time Slider</strong> from 0 to 4,000 years. Watch canyons incise upslope while alluvial fans simultaneously build outward at their mouths. Compare the West&ndash;East transect at <em>y &approx; 400 m</em> (V-shaped canyon cutting down) against <em>y &approx; 160 m</em> (convex fan lenses building up).</li>
        <li><strong>Activity 2 — Degrade the Shrub Cover:</strong> Under <em>Parameter Experiments</em>, click <strong>Degraded Shrubs (0.35&times; Veg)</strong> versus <strong>Dense Shrubs (1.55&times; Veg)</strong>. Notice how stripping dryland shrubs accelerates upper-slope erosion and forces much larger sediment plumes onto the piedmont and out the southern boundary.</li>
        <li><strong>Activity 3 — Storm Intensity Sensitivity:</strong> Toggle between <strong>Calm Arid (0.55&times; Rain)</strong> and <strong>Intense Storms (1.65&times; Rain)</strong>. Because detachment and transport capacity scale non-linearly with discharge, doubling storm intensity more than doubles canyon incision depth and fan progradation distance.</li>
      </ul>
    </div>
  </div>
</div>

<script>
const SIM_DATA = {data_json};

// Colormaps
const CMAP_DRYLAND = [
  [0.00, [233, 220, 196]],
  [0.14, [216, 189, 142]],
  [0.32, [198, 150, 96]],
  [0.55, [168, 108, 67]],
  [0.78, [130, 77, 52]],
  [0.92, [154, 123, 105]],
  [1.00, [242, 236, 225]]
];

const CMAP_ERODEP = [
  [0.00, [122, 22, 12]],
  [0.25, [201, 74, 41]],
  [0.45, [240, 183, 153]],
  [0.50, [247, 244, 237]],
  [0.55, [166, 216, 212]],
  [0.75, [43, 140, 190]],
  [1.00, [8, 64, 129]]
];

const CMAP_VEG = [
  [0.00, [229, 213, 183]],
  [0.30, [200, 188, 138]],
  [0.60, [127, 160, 83]],
  [1.00, [45, 90, 39]]
];

const CMAP_FLOW = [
  [0.00, [244, 236, 220]],
  [0.30, [186, 218, 235]],
  [0.65, [58, 138, 191]],
  [1.00, [8, 48, 107]]
];

function sampleCmap(cmap, t) {{
  const u = Math.max(0, Math.min(1, t));
  for (let i = 0; i < cmap.length - 1; i++) {{
    const t0 = cmap[i][0], t1 = cmap[i+1][0];
    if (u >= t0 && u <= t1) {{
      const f = (u - t0) / Math.max(1e-9, t1 - t0);
      const c0 = cmap[i][1], c1 = cmap[i+1][1];
      return [
        Math.round(c0[0] + f * (c1[0] - c0[0])),
        Math.round(c0[1] + f * (c1[1] - c0[1])),
        Math.round(c0[2] + f * (c1[2] - c0[2]))
      ];
    }}
  }}
  return cmap[cmap.length - 1][1];
}}

const ny = SIM_DATA.meta.ny;
const nx = SIM_DATA.meta.nx;
const dx = SIM_DATA.meta.dx;

let state = {{
  layer: "terrain",
  frameIdx: SIM_DATA.frames.length - 1,
  scenario: "baseline",
  azimDeg: 315,
  showContours: true,
  showRivers: false,
  playing: false,
  playTimer: null,
  selRow: 52,
  selCol: 62,
  locked: false,
  activeLandform: null
}};

const LANDFORMS = {{
  divide: {{
    row: 10, col: 60,
    title: "Creep-Rounded Crest & Interfluves",
    radius: 8,
    points: [[10, 38], [10, 65], [10, 88]]
  }},
  canyons: {{
    row: 38, col: 62,
    title: "Incised V-Shaped Feeder Canyons",
    radius: 9,
    points: [[38, 26], [38, 62], [38, 96]]
  }},
  apices: {{
    row: 65, col: 62,
    title: "Canyon Mouths & Alluvial Fan Apices",
    radius: 8,
    points: [[65, 26], [65, 62], [65, 96]]
  }},
  bajada: {{
    row: 90, col: 62,
    title: "Coalescing Alluvial Bajada Apron",
    radius: 11,
    points: [[90, 28], [90, 62], [90, 95]]
  }},
  shrubs: {{
    row: 48, col: 44,
    title: "Vegetation-Protected Interfluve Islands",
    radius: 8,
    points: [[48, 44], [46, 78]]
  }}
}};

function getCurrentFieldSet() {{
  if (state.scenario === "baseline") {{
    const f = SIM_DATA.frames[state.frameIdx];
    const stepIdx = Math.max(0, f.step - 1);
    return {{
      z: f.z,
      dz: f.dz,
      veg: f.veg,
      flow: f.flow,
      year: f.year,
      subtitle: `Baseline Evolution — t = ${{f.year.toLocaleString()}} yr`,
      eroded_m3: f.step === 0 ? 0 : SIM_DATA.storms.cum_eroded[stepIdx],
      deposited_m3: f.step === 0 ? 0 : SIM_DATA.storms.cum_deposited[stepIdx],
      exported_m3: f.step === 0 ? 0 : SIM_DATA.storms.cum_exported[stepIdx]
    }};
  }} else {{
    const sc = SIM_DATA.scenarios[state.scenario];
    return {{
      z: sc.z,
      dz: sc.dz,
      veg: sc.veg,
      flow: sc.flow,
      year: SIM_DATA.meta.years,
      subtitle: `${{sc.label}} (t = ${{SIM_DATA.meta.years.toLocaleString()}} yr)`,
      eroded_m3: sc.eroded_m3,
      deposited_m3: sc.deposited_m3,
      exported_m3: sc.exported_m3
    }};
  }}
}}

function computeHillshadeGrid(z, azimDeg, elevDeg = 38.0) {{
  const az = (azimDeg * Math.PI) / 180.0;
  const el = (elevDeg * Math.PI) / 180.0;
  const lx = Math.sin(az) * Math.cos(el);
  const ly = Math.cos(az) * Math.cos(el);
  const lz = Math.sin(el);

  const shade = new Float32Array(ny * nx);
  for (let r = 0; r < ny; r++) {{
    const rUp = Math.max(0, r - 1);
    const rDn = Math.min(ny - 1, r + 1);
    const dy = (rDn - rUp) * dx || dx;
    for (let c = 0; c < nx; c++) {{
      const cLt = Math.max(0, c - 1);
      const cRt = Math.min(nx - 1, c + 1);
      const dxx = (cRt - cLt) * dx || dx;
      const dzdx = (z[r][cRt] - z[r][cLt]) / dxx;
      const dzdy = (z[rDn][c] - z[rUp][c]) / dy;
      const nxv = -dzdx;
      const nyv = dzdy;
      const norm = Math.sqrt(nxv * nxv + nyv * nyv + 1.0);
      const dot = (nxv * lx + nyv * ly + lz) / norm;
      shade[r * nx + c] = Math.max(0, Math.min(1, 0.55 * dot + 0.45));
    }}
  }}
  return shade;
}}

function renderMap() {{
  const canvas = document.getElementById("mapCanvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const fields = getCurrentFieldSet();
  const z = fields.z;
  const dz = fields.dz;
  const veg = fields.veg;
  const flow = fields.flow;
  const shade = computeHillshadeGrid(z, state.azimDeg);

  // Offscreen 120x120 image buffer scaled cleanly to 480x480
  const off = document.createElement("canvas");
  off.width = nx;
  off.height = ny;
  const offCtx = off.getContext("2d");
  const imgData = offCtx.createImageData(nx, ny);
  const data = imgData.data;

  const dzMaxAbs = 8.0;
  let minZ = 0.0, maxZ = 95.0;

  for (let r = 0; r < ny; r++) {{
    for (let c = 0; c < nx; c++) {{
      const idx = r * nx + c;
      const sh = shade[idx];
      let rgb;

      if (state.layer === "terrain") {{
        const zn = (z[r][c] - minZ) / (maxZ - minZ);
        const base = sampleCmap(CMAP_DRYLAND, zn);
        const factor = 0.52 + 0.62 * sh;
        rgb = [
          Math.min(255, base[0] * factor),
          Math.min(255, base[1] * factor),
          Math.min(255, base[2] * factor)
        ];
      }} else if (state.layer === "dz") {{
        // Zero-centered diverging scale [-dzMaxAbs, +dzMaxAbs]
        const u = 0.5 + 0.5 * Math.max(-1, Math.min(1, dz[r][c] / dzMaxAbs));
        const base = sampleCmap(CMAP_ERODEP, u);
        const factor = 0.72 + 0.36 * sh;
        rgb = [
          Math.min(255, base[0] * factor),
          Math.min(255, base[1] * factor),
          Math.min(255, base[2] * factor)
        ];
      }} else if (state.layer === "combo") {{
        const zn = (z[r][c] - minZ) / (maxZ - minZ);
        const terr = sampleCmap(CMAP_DRYLAND, zn);
        const u = 0.5 + 0.5 * Math.max(-1, Math.min(1, dz[r][c] / dzMaxAbs));
        const ed = sampleCmap(CMAP_ERODEP, u);
        const wEd = Math.min(0.82, Math.abs(dz[r][c]) / 2.5);
        const factor = 0.55 + 0.58 * sh;
        rgb = [
          Math.min(255, ((1 - wEd) * terr[0] + wEd * ed[0]) * factor),
          Math.min(255, ((1 - wEd) * terr[1] + wEd * ed[1]) * factor),
          Math.min(255, ((1 - wEd) * terr[2] + wEd * ed[2]) * factor)
        ];
      }} else if (state.layer === "veg") {{
        const vn = veg[r][c] / 95.0;
        const base = sampleCmap(CMAP_VEG, vn);
        const factor = 0.62 + 0.48 * sh;
        rgb = [
          Math.min(255, base[0] * factor),
          Math.min(255, base[1] * factor),
          Math.min(255, base[2] * factor)
        ];
      }} else {{
        const fn = flow[r][c] / 3.0;
        const base = sampleCmap(CMAP_FLOW, fn);
        const factor = 0.65 + 0.45 * sh;
        rgb = [
          Math.min(255, base[0] * factor),
          Math.min(255, base[1] * factor),
          Math.min(255, base[2] * factor)
        ];
      }}

      if (state.showRivers && state.layer !== "flow" && flow[r][c] > 1.28) {{
        const alpha = Math.min(0.75, (flow[r][c] - 1.28) / 1.6);
        rgb[0] = (1 - alpha) * rgb[0] + alpha * 20;
        rgb[1] = (1 - alpha) * rgb[1] + alpha * 105;
        rgb[2] = (1 - alpha) * rgb[2] + alpha * 175;
      }}

      const p = idx * 4;
      data[p] = rgb[0];
      data[p + 1] = rgb[1];
      data[p + 2] = rgb[2];
      data[p + 3] = 255;
    }}
  }}

  offCtx.putImageData(imgData, 0, 0);
  ctx.imageSmoothingEnabled = true;
  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(off, 0, 0, W, H);

  const scaleX = W / nx;
  const scaleY = H / ny;

  // Draw 10m elevation contours if enabled
  if (state.showContours) {{
    ctx.strokeStyle = "rgba(48, 32, 18, 0.35)";
    ctx.lineWidth = 1.0;
    const levels = [10, 20, 30, 40, 50, 60, 70, 80, 90];
    ctx.beginPath();
    for (let r = 0; r < ny - 1; r++) {{
      for (let c = 0; c < nx - 1; c++) {{
        const z00 = z[r][c], z10 = z[r][c+1], z01 = z[r+1][c];
        for (let lv of levels) {{
          if ((z00 < lv && z10 >= lv) || (z00 >= lv && z10 < lv)) {{
            const frac = (lv - z00) / (z10 - z00);
            ctx.moveTo((c + frac) * scaleX, (r + 0.5) * scaleY);
            ctx.lineTo((c + frac) * scaleX + 1.5, (r + 0.5) * scaleY + 1.5);
          }}
          if ((z00 < lv && z01 >= lv) || (z00 >= lv && z01 < lv)) {{
            const frac = (lv - z00) / (z01 - z00);
            ctx.moveTo((c + 0.5) * scaleX, (r + frac) * scaleY);
            ctx.lineTo((c + 0.5) * scaleX + 1.5, (r + frac) * scaleY + 1.5);
          }}
        }}
      }}
    }}
    ctx.stroke();
  }}

  // Draw piedmont slope break dashed line (y_norm = 0.54)
  const breakY = 0.54 * H;
  ctx.save();
  ctx.setLineDash([5, 5]);
  ctx.strokeStyle = "rgba(42, 32, 23, 0.55)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(0, breakY);
  ctx.lineTo(W, breakY);
  ctx.stroke();
  ctx.fillStyle = "rgba(255, 250, 240, 0.82)";
  ctx.fillRect(8, breakY - 17, 175, 14);
  ctx.fillStyle = "#2a2017";
  ctx.font = "600 10px sans-serif";
  ctx.fillText("Mountain Front / Piedmont Break", 12, breakY - 6);
  ctx.restore();

  // Draw active landform highlights if selected
  if (state.activeLandform && LANDFORMS[state.activeLandform]) {{
    const lf = LANDFORMS[state.activeLandform];
    ctx.save();
    for (const pt of lf.points) {{
      const cx = (pt[1] + 0.5) * scaleX;
      const cy = (pt[0] + 0.5) * scaleY;
      ctx.beginPath();
      ctx.arc(cx, cy, lf.radius * scaleX, 0, 2 * Math.PI);
      ctx.strokeStyle = "#ffea79";
      ctx.lineWidth = 3.0;
      ctx.stroke();
      ctx.strokeStyle = "#7a160c";
      ctx.lineWidth = 1.3;
      ctx.stroke();
    }}
    ctx.restore();
  }}

  // Draw selected crosshair lines for N-S and W-E profile slices
  const cx = (state.selCol + 0.5) * scaleX;
  const cy = (state.selRow + 0.5) * scaleY;
  ctx.save();
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = state.locked ? "#a63a1f" : "rgba(255, 255, 255, 0.85)";
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  ctx.moveTo(cx, 0); ctx.lineTo(cx, H);
  ctx.moveTo(0, cy); ctx.lineTo(W, cy);
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
  ctx.fillStyle = state.locked ? "#a63a1f" : "#ffffff";
  ctx.fill();
  ctx.strokeStyle = "#2a2017";
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.restore();

  updateColorbarAndStats(fields);
  updateInspectorAndProfiles(fields);
  drawStormChart(fields);
}}

function updateColorbarAndStats(fields) {{
  const grad = document.getElementById("cbarGrad");
  const cMin = document.getElementById("cbarMin");
  const cMid = document.getElementById("cbarMid");
  const cMax = document.getElementById("cbarMax");
  const titleEl = document.getElementById("mapTitleText");

  if (state.layer === "terrain") {{
    grad.style.background = "linear-gradient(90deg, #e9dcc4 0%, #d8bd8e 18%, #c69660 38%, #a86c43 60%, #824d34 80%, #f2ece1 100%)";
    cMin.textContent = "0 m (Piedmont Base)";
    cMid.textContent = "48 m (Escarpment Slope)";
    cMax.textContent = "95 m (Divide Crest)";
    titleEl.textContent = `Dryland Shaded Relief — ${{fields.subtitle}}`;
  }} else if (state.layer === "dz") {{
    grad.style.background = "linear-gradient(90deg, #7a160c 0%, #c94a29 25%, #f0b799 45%, #f7f4ed 50%, #a6d8d4 55%, #2b8cbe 75%, #084081 100%)";
    cMin.textContent = "-8.0 m (Canyon Erosion)";
    cMid.textContent = "0.0 m (No Net Change)";
    cMax.textContent = "+8.0 m (Alluvial Fan Deposition)";
    titleEl.textContent = `Net Elevation Change Δz (Zero-Centred) — ${{fields.subtitle}}`;
  }} else if (state.layer === "combo") {{
    grad.style.background = "linear-gradient(90deg, #7a160c 0%, #d8bd8e 50%, #084081 100%)";
    cMin.textContent = "Deep Incision (-Δz)";
    cMid.textContent = "Stable Dryland Slope (0 m)";
    cMax.textContent = "Bajada Aggradation (+Δz)";
    titleEl.textContent = `Shaded Relief + Erosion/Deposition — ${{fields.subtitle}}`;
  }} else if (state.layer === "veg") {{
    grad.style.background = "linear-gradient(90deg, #e5d5b7 0%, #c8bc8a 35%, #7fa053 68%, #2d5a27 100%)";
    cMin.textContent = "2% (Bare Desert Crust)";
    cMid.textContent = "45% (Patchy Shrub Steppe)";
    cMax.textContent = "92% (Dense Shrub Band)";
    titleEl.textContent = `Patchy Dryland Shrub Cover — ${{fields.subtitle}}`;
  }} else {{
    grad.style.background = "linear-gradient(90deg, #f4ecdc 0%, #badaeb 35%, #3a8abf 70%, #08306b 100%)";
    cMin.textContent = "25 m² (Local Sheetwash)";
    cMid.textContent = "1,000 m² (Concentrated Rill)";
    cMax.textContent = "25,000+ m² (Canyon Wash)";
    titleEl.textContent = `Routed Overland Flow Drainage Area — ${{fields.subtitle}}`;
  }}

  let minDz = 0.0, maxDz = 0.0;
  for (let r = 0; r < ny; r++) {{
    for (let c = 0; c < nx; c++) {{
      const v = fields.dz[r][c];
      if (v < minDz) minDz = v;
      if (v > maxDz) maxDz = v;
    }}
  }}
  document.getElementById("statErosion").textContent = `${{minDz.toFixed(2)}} m`;
  document.getElementById("statDeposition").textContent = `+${{maxDz.toFixed(2)}} m`;
  document.getElementById("statBajadaVol").textContent = `${{Math.round(fields.deposited_m3).toLocaleString()}} m³`;
  document.getElementById("statExportVol").textContent = `${{Math.round(fields.exported_m3).toLocaleString()}} m³`;
}}

function updateInspectorAndProfiles(fields) {{
  const r = state.selRow;
  const c = state.selCol;
  const xM = (c * dx).toFixed(0);
  const yM = ((ny - 1 - r) * dx).toFixed(0);
  const zNow = fields.z[r][c];
  const zInit = SIM_DATA.z0[r][c];
  const dzVal = fields.dz[r][c];
  const vegVal = fields.veg[r][c];
  const areaM2 = Math.round(Math.pow(10, fields.flow[r][c]) * dx * dx);

  const zone = (r / ny < 0.54) ? "Upper Escarpment / Canyon Zone" : "Lower Piedmont Bajada (Alluvial Fan Zone)";
  const lockTag = state.locked ? "[LOCKED — click map to unlock]" : "[Hovering — click map to lock]";

  document.getElementById("inspectBox").innerHTML =
    `<strong>Coord:</strong> East x=${{xM}}m, North y=${{yM}}m ${{lockTag}}<br>` +
    `<strong>Zone:</strong> ${{zone}}<br>` +
    `<strong>Elev z:</strong> ${{zNow.toFixed(2)}} m (Initial: ${{zInit.toFixed(2)}} m | <strong>&Delta;z: ${{dzVal >= 0 ? "+" : ""}}${{dzVal.toFixed(2)}} m</strong>)<br>` +
    `<strong>Shrub Cover:</strong> ${{vegVal.toFixed(1)}}% | <strong>Upslope Area:</strong> ${{areaM2.toLocaleString()}} m&sup2;`;

  drawNSProfile(fields, c, r);
  drawWEProfile(fields, r, c);
}}

function drawNSProfile(fields, col, markRow) {{
  const canvas = document.getElementById("nsProfileCanvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const padL = 34, padR = 10, padT = 14, padB = 22;
  const pw = W - padL - padR;
  const ph = H - padT - padB;
  const zMax = 98.0;

  // Grid & axes
  ctx.strokeStyle = "#e3d5be";
  ctx.lineWidth = 1;
  for (let zTick of [0, 30, 60, 90]) {{
    const y = padT + ph * (1 - zTick / zMax);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillStyle = "#655241";
    ctx.font = "10px monospace";
    ctx.fillText(`${{zTick}}m`, 4, y + 3);
  }}

  // Piedmont break vertical line
  const xBreak = padL + 0.54 * pw;
  ctx.save();
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = "#8c6d46";
  ctx.beginPath(); ctx.moveTo(xBreak, padT); ctx.lineTo(xBreak, padT + ph); ctx.stroke();
  ctx.restore();

  // Initial profile (dashed)
  ctx.beginPath();
  for (let r = 0; r < ny; r++) {{
    const x = padL + (r / (ny - 1)) * pw;
    const y = padT + ph * (1 - SIM_DATA.z0[r][col] / zMax);
    if (r === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.strokeStyle = "#8a7968";
  ctx.setLineDash([4, 3]);
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.setLineDash([]);

  // Current profile
  ctx.beginPath();
  for (let r = 0; r < ny; r++) {{
    const x = padL + (r / (ny - 1)) * pw;
    const y = padT + ph * (1 - fields.z[r][col] / zMax);
    if (r === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.strokeStyle = "#a63a1f";
  ctx.lineWidth = 2.0;
  ctx.stroke();

  // Marker for selected row
  const mx = padL + (markRow / (ny - 1)) * pw;
  const my = padT + ph * (1 - fields.z[markRow][col] / zMax);
  ctx.beginPath();
  ctx.arc(mx, my, 4, 0, 2 * Math.PI);
  ctx.fillStyle = "#1d6f8a";
  ctx.fill();

  ctx.fillStyle = "#2a2017";
  ctx.font = "10px sans-serif";
  ctx.fillText("North (Divide)", padL, H - 5);
  ctx.fillText("Fan Apex", xBreak - 18, H - 5);
  ctx.fillText("South (Outlet)", W - padR - 68, H - 5);
  ctx.fillText(`Column x = ${{col * dx}}m (Dashed = Initial, Red = Current)`, padL + 4, 11);
}}

function drawWEProfile(fields, row, markCol) {{
  const canvas = document.getElementById("weProfileCanvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const padL = 36, padR = 10, padT = 16, padB = 22;
  const pw = W - padL - padR;
  const ph = H - padT - padB;

  let minE = Infinity, maxE = -Infinity;
  for (let c = 0; c < nx; c++) {{
    minE = Math.min(minE, SIM_DATA.z0[row][c], fields.z[row][c]);
    maxE = Math.max(maxE, SIM_DATA.z0[row][c], fields.z[row][c]);
  }}
  minE = Math.floor(minE - 2);
  maxE = Math.ceil(maxE + 2);
  const span = Math.max(4, maxE - minE);

  ctx.strokeStyle = "#e3d5be";
  ctx.lineWidth = 1;
  for (let f of [0, 0.5, 1.0]) {{
    const val = minE + f * span;
    const y = padT + ph * (1 - f);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillStyle = "#655241";
    ctx.font = "10px monospace";
    ctx.fillText(`${{val.toFixed(0)}}m`, 2, y + 3);
  }}

  // Shade erosion (red) and deposition (blue) between z0 and z
  for (let c = 0; c < nx - 1; c++) {{
    const x0 = padL + (c / (nx - 1)) * pw;
    const x1 = padL + ((c + 1) / (nx - 1)) * pw;
    const y0_init = padT + ph * (1 - (SIM_DATA.z0[row][c] - minE) / span);
    const y1_init = padT + ph * (1 - (SIM_DATA.z0[row][c+1] - minE) / span);
    const y0_now = padT + ph * (1 - (fields.z[row][c] - minE) / span);
    const y1_now = padT + ph * (1 - (fields.z[row][c+1] - minE) / span);

    ctx.beginPath();
    ctx.moveTo(x0, y0_init);
    ctx.lineTo(x1, y1_init);
    ctx.lineTo(x1, y1_now);
    ctx.lineTo(x0, y0_now);
    ctx.closePath();
    ctx.fillStyle = (fields.dz[row][c] >= 0) ? "rgba(43, 140, 190, 0.42)" : "rgba(201, 74, 41, 0.42)";
    ctx.fill();
  }}

  // Initial W-E line
  ctx.beginPath();
  for (let c = 0; c < nx; c++) {{
    const x = padL + (c / (nx - 1)) * pw;
    const y = padT + ph * (1 - (SIM_DATA.z0[row][c] - minE) / span);
    if (c === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.strokeStyle = "#8a7968";
  ctx.setLineDash([4, 3]);
  ctx.lineWidth = 1.3;
  ctx.stroke();
  ctx.setLineDash([]);

  // Current W-E line
  ctx.beginPath();
  for (let c = 0; c < nx; c++) {{
    const x = padL + (c / (nx - 1)) * pw;
    const y = padT + ph * (1 - (fields.z[row][c] - minE) / span);
    if (c === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.strokeStyle = "#2a2017";
  ctx.lineWidth = 1.8;
  ctx.stroke();

  const mx = padL + (markCol / (nx - 1)) * pw;
  const my = padT + ph * (1 - (fields.z[row][markCol] - minE) / span);
  ctx.beginPath();
  ctx.arc(mx, my, 4, 0, 2 * Math.PI);
  ctx.fillStyle = "#a63a1f";
  ctx.fill();

  const yNorth = (ny - 1 - row) * dx;
  ctx.fillStyle = "#2a2017";
  ctx.font = "10px sans-serif";
  ctx.fillText(`Row y = ${{yNorth}}m (Red fill = Eroded Canyon, Blue fill = Deposited Fan)`, padL, 11);
  ctx.fillText("West (0m)", padL, H - 5);
  ctx.fillText("East (595m)", W - padR - 55, H - 5);
}}

function drawStormChart(fields) {{
  const canvas = document.getElementById("stormCanvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const padL = 36, padR = 10, padT = 16, padB = 20;
  const pw = W - padL - padR;
  const ph = H - padT - padB;

  const storms = SIM_DATA.storms.intensity;
  const nSteps = storms.length;
  const maxStorm = Math.max(...storms, 2.5);

  // Draw storm bars
  const barW = Math.max(1.2, pw / nSteps);
  for (let i = 0; i < nSteps; i++) {{
    const x = padL + (i / nSteps) * pw;
    const bh = (storms[i] / maxStorm) * (ph * 0.68);
    ctx.fillStyle = ( (i + 1) * SIM_DATA.meta.dt <= fields.year ) ? "#4a90b8" : "#d8cfc0";
    ctx.fillRect(x, padT + ph - bh, barW, bh);
  }}

  // Overlay cumulative eroded & deposited sediment curves
  const maxVol = Math.max(...SIM_DATA.storms.cum_eroded, 1.0);
  ctx.beginPath();
  for (let i = 0; i < nSteps; i++) {{
    const x = padL + (i / (nSteps - 1)) * pw;
    const y = padT + ph * (1 - 0.92 * (SIM_DATA.storms.cum_eroded[i] / maxVol));
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.strokeStyle = "#a63a1f";
  ctx.lineWidth = 1.8;
  ctx.stroke();

  ctx.beginPath();
  for (let i = 0; i < nSteps; i++) {{
    const x = padL + (i / (nSteps - 1)) * pw;
    const y = padT + ph * (1 - 0.92 * (SIM_DATA.storms.cum_deposited[i] / maxVol));
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.strokeStyle = "#15607a";
  ctx.lineWidth = 1.8;
  ctx.stroke();

  // Current time marker
  const tx = padL + (fields.year / SIM_DATA.meta.years) * pw;
  ctx.strokeStyle = "#2a2017";
  ctx.lineWidth = 1.4;
  ctx.beginPath(); ctx.moveTo(tx, padT); ctx.lineTo(tx, padT + ph); ctx.stroke();

  ctx.fillStyle = "#2a2017";
  ctx.font = "10px sans-serif";
  ctx.fillText("Bars: Storm Index | Curves: Cum. Eroded (Red) & Fan Deposited (Blue)", padL - 2, 11);
  ctx.fillText("0 yr", padL, H - 4);
  ctx.fillText(`${{SIM_DATA.meta.years}} yr`, W - padR - 42, H - 4);
}}

// Event Listeners
document.querySelectorAll("#layerButtons button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll("#layerButtons button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.layer = btn.getAttribute("data-layer");
    renderMap();
  }});
}});

document.getElementById("azimSlider").addEventListener("input", e => {{
  state.azimDeg = parseInt(e.target.value, 10);
  document.getElementById("azimVal").textContent = state.azimDeg;
  renderMap();
}});

document.getElementById("chkContours").addEventListener("change", e => {{
  state.showContours = e.target.checked;
  renderMap();
}});

document.getElementById("chkRivers").addEventListener("change", e => {{
  state.showRivers = e.target.checked;
  renderMap();
}});

const timeSlider = document.getElementById("timeSlider");
timeSlider.addEventListener("input", e => {{
  state.scenario = "baseline";
  document.querySelectorAll("#scenarioButtons button").forEach(b => {{
    b.classList.toggle("active", b.getAttribute("data-scen") === "baseline");
  }});
  state.frameIdx = parseInt(e.target.value, 10);
  const yr = SIM_DATA.frames[state.frameIdx].year;
  document.getElementById("yearLabel").textContent = `${{yr.toLocaleString()}} yr`;
  document.getElementById("scenDesc").textContent = "Baseline dryland climate and patchy shrub cover (time slider active).";
  renderMap();
}});

document.getElementById("btnBefore").addEventListener("click", () => {{
  stopPlay();
  timeSlider.value = 0;
  timeSlider.dispatchEvent(new Event("input"));
}});

document.getElementById("btnAfter").addEventListener("click", () => {{
  stopPlay();
  timeSlider.value = SIM_DATA.frames.length - 1;
  timeSlider.dispatchEvent(new Event("input"));
}});

function stopPlay() {{
  if (state.playing) {{
    clearInterval(state.playTimer);
    state.playing = false;
    document.getElementById("btnPlay").innerHTML = "&#9654; Play Evolution";
  }}
}}

document.getElementById("btnPlay").addEventListener("click", () => {{
  if (state.playing) {{
    stopPlay();
  }} else {{
    state.scenario = "baseline";
    if (state.frameIdx >= SIM_DATA.frames.length - 1) state.frameIdx = 0;
    state.playing = true;
    document.getElementById("btnPlay").innerHTML = "&#9208; Pause";
    state.playTimer = setInterval(() => {{
      state.frameIdx = (state.frameIdx + 1) % SIM_DATA.frames.length;
      timeSlider.value = state.frameIdx;
      const yr = SIM_DATA.frames[state.frameIdx].year;
      document.getElementById("yearLabel").textContent = `${{yr.toLocaleString()}} yr`;
      renderMap();
      if (state.frameIdx === SIM_DATA.frames.length - 1) stopPlay();
    }}, 550);
  }}
}});

document.querySelectorAll("#scenarioButtons button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    stopPlay();
    document.querySelectorAll("#scenarioButtons button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const sc = btn.getAttribute("data-scen");
    state.scenario = sc;
    if (sc === "baseline") {{
      state.frameIdx = SIM_DATA.frames.length - 1;
      timeSlider.value = state.frameIdx;
      document.getElementById("yearLabel").textContent = `${{SIM_DATA.meta.years.toLocaleString()}} yr`;
      document.getElementById("scenDesc").textContent = "Baseline dryland climate and patchy shrub cover (time slider active).";
    }} else {{
      const info = SIM_DATA.scenarios[sc];
      document.getElementById("yearLabel").textContent = `${{SIM_DATA.meta.years.toLocaleString()}} yr (${{info.label}})`;
      document.getElementById("scenDesc").textContent = info.subtitle;
    }}
    renderMap();
  }});
}});

document.querySelectorAll(".landform-btn").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const key = btn.getAttribute("data-lf");
    if (state.activeLandform === key) {{
      state.activeLandform = null;
      btn.classList.remove("active");
    }} else {{
      document.querySelectorAll(".landform-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeLandform = key;
      const lf = LANDFORMS[key];
      state.selRow = lf.row;
      state.selCol = lf.col;
      state.locked = true;
    }}
    renderMap();
  }});
}});

const mapCanvas = document.getElementById("mapCanvas");
function updateCoordFromMouse(e) {{
  const rect = mapCanvas.getBoundingClientRect();
  const xFrac = Math.max(0, Math.min(0.999, (e.clientX - rect.left) / rect.width));
  const yFrac = Math.max(0, Math.min(0.999, (e.clientY - rect.top) / rect.height));
  state.selCol = Math.floor(xFrac * nx);
  state.selRow = Math.floor(yFrac * ny);
  renderMap();
}}

mapCanvas.addEventListener("mousemove", e => {{
  if (!state.locked) updateCoordFromMouse(e);
}});

mapCanvas.addEventListener("click", e => {{
  state.locked = !state.locked;
  updateCoordFromMouse(e);
}});

// Initial render
renderMap();
</script>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def main():
    parser = argparse.ArgumentParser(
        description="Simulate dryland hillslope erosion and deposition and build interactive teaching map."
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for all stochastic processes")
    parser.add_argument("--out", type=str, required=True, help="Output directory for deliverable files")
    args = parser.parse_args()

    t_start = time.time()
    os.makedirs(args.out, exist_ok=True)

    # Grid & temporal configuration
    ny, nx = 120, 120
    dx = 5.0
    n_steps = 160
    dt = 25.0
    years_simulated = n_steps * dt  # 4,000 years

    nbr_idx, nbr_dist, nbr_cw = build_neighbor_tables(ny, nx, dx)
    z0, veg0, storm_counts, storm_intensity, max_single_storm_mm = generate_initial_state(
        args.seed, ny, nx, dx, n_steps
    )

    snapshot_steps = [0, 20, 40, 60, 80, 100, 120, 140, 160]
    baseline_res = run_simulation(
        z0=z0,
        veg0=veg0,
        storm_intensity=storm_intensity,
        nbr_idx=nbr_idx,
        nbr_dist=nbr_dist,
        nbr_cw=nbr_cw,
        dx=dx,
        dt=dt,
        veg_scale=1.0,
        rain_scale=1.0,
        snapshot_steps=snapshot_steps,
    )

    # Run 4 additional parameter sensitivity scenarios for interactive student exploration
    scenario_configs = [
        (
            "arid_storms",
            "Calm Arid Climate (0.55x Storminess)",
            "Weaker convective storms reduce canyon incision by ~45% and build smaller, steeper fan cones near canyon mouths.",
            1.0,
            0.55,
        ),
        (
            "intense_storms",
            "Intense Monsoonal Storms (1.65x Storminess)",
            "Stronger cloudbursts deeply incise feeder canyons and prograde a thick alluvial bajada across the piedmont.",
            1.0,
            1.65,
        ),
        (
            "sparse_veg",
            "Degraded Shrubland (0.35x Vegetation Cover)",
            "Overgrazing or drought strips protective shrubs, accelerating upper-hillslope sheetwash and doubling sediment export.",
            0.35,
            1.0,
        ),
        (
            "dense_veg",
            "Dense Shrub Steppe (1.55x Vegetation Cover)",
            "Dense root cohesion and canopy cover armour the hillslope, suppressing erosion and starving fans of sediment.",
            1.55,
            1.0,
        ),
    ]

    param_scenarios = {}
    for key, label, subtitle, v_scale, r_scale in scenario_configs:
        sres = run_simulation(
            z0=z0,
            veg0=veg0,
            storm_intensity=storm_intensity,
            nbr_idx=nbr_idx,
            nbr_dist=nbr_dist,
            nbr_cw=nbr_cw,
            dx=dx,
            dt=dt,
            veg_scale=v_scale,
            rain_scale=r_scale,
            snapshot_steps=None,
        )
        sres["label"] = label
        sres["subtitle"] = subtitle
        param_scenarios[key] = sres

    # 1. Save z_initial.npy and z_final.npy (2D float64)
    z_initial_out = np.asarray(z0, dtype=np.float64)
    z_final_out = np.asarray(baseline_res["z_final"], dtype=np.float64)
    np.save(os.path.join(args.out, "z_initial.npy"), z_initial_out)
    np.save(os.path.join(args.out, "z_final.npy"), z_final_out)

    # 2. Save telemetry.json
    telemetry = {
        "seed": int(args.seed),
        "grid_shape": [int(ny), int(nx)],
        "cell_size_m": float(dx),
        "years_simulated": float(years_simulated),
        "timesteps": int(n_steps),
        "open_boundaries": ["south"],
        "sediment_exported_m3": round(float(baseline_res["sediment_exported_m3"]), 6),
        "uplift_or_baselevel_m3": 0.0,
        "max_erosion_m": round(float(baseline_res["max_erosion_m"]), 6),
        "max_deposition_m": round(float(baseline_res["max_deposition_m"]), 6),
        "mass_balance_error_pct": float(baseline_res["mass_balance_error_pct"]),
    }
    telemetry_path = os.path.join(args.out, "telemetry.json")
    with open(telemetry_path, "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2)

    # 3. Render static map (map.png)
    render_static_map(
        out_path=os.path.join(args.out, "map.png"),
        z0=z_initial_out,
        res=baseline_res,
        dx=dx,
        years=years_simulated,
        seed=args.seed,
    )

    # 4. Build interactive offline HTML teaching tool (map.html)
    build_interactive_html(
        out_path=os.path.join(args.out, "map.html"),
        z0=z_initial_out,
        veg0=veg0,
        storm_counts=storm_counts,
        storm_intensity=storm_intensity,
        max_single_storm_mm=max_single_storm_mm,
        baseline_res=baseline_res,
        param_scenarios=param_scenarios,
        telemetry=telemetry,
        dx=dx,
        dt=dt,
    )

    elapsed = time.time() - t_start
    print(json.dumps(telemetry, indent=2))
    print(f"# Completed in {elapsed:.2f}s -> {args.out}")


if __name__ == "__main__":
    main()
