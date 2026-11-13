#!/usr/bin/env python3
"""Dryland hillslope erosion and deposition: a small teaching model.

Processes (all coupled through the elevation grid z):
  1. Hillslope creep: linear diffusion, dz/dt = div(D grad z).            -> creep_step()
  2. Overland-flow erosion and deposition: multiple-flow-direction routing
     of storm runoff, detachment E = K q^m S^n, deposition D = V Qs/Q
     (erosion-deposition model of Davy & Lague 2009), solved downslope so
     eroded sediment is carried and dropped where flow can no longer hold it.
                                                                           -> route_flow(), storm_pulse()
  3. Rain as discrete random storms (Poisson arrivals, exponential depths).-> make_storms(), run loop in run_model()
  4. Patchy vegetation: raises infiltration and run-on capture, lowers
     erodibility, raises sediment trapping and raises creep (bioturbation). -> make_vegetation(), veg_fields()

Run:  python3 sim.py --seed 42 --out OUTDIR [--z0 FILE] [--rain-scale F]
                     [--veg-scale F] [--dt-scale F] [--no-map]
"""
import argparse
import base64
import json
import os
import sys
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
from scipy.ndimage import gaussian_filter

# ----------------------------------------------------------------------------
# Fixed model parameters
# ----------------------------------------------------------------------------
NROWS, NCOLS = 100, 100      # grid shape (row 0 = top/crest, last row = foot)
DX = 2.0                     # cell size, m
CELL_AREA = DX * DX          # m2
YEARS = 600.0               # simulated span, years
DT_BASE = 1.0                # base time step, years

# Rain (storms): Poisson arrivals, exponentially distributed depths
STORM_RATE_PER_YR = 16.0     # storms per year
STORM_MEAN_MM = 12.0         # mean storm depth, mm  -> ~190 mm/yr

# Soil / infiltration (per-storm infiltration capacity, mm)
INFIL_BARE_MM = 6.0          # crusted bare soil
INFIL_VEG_MM = 25.0          # under full vegetation cover
RUNON_CAPTURE = 0.5          # fraction of run-on soaked up by a fully vegetated cell

# Overland flow erosion (detachment-limited law, per storm)
K_BARE = 2.0e-3             # erodibility on bare soil, m per storm per (m2)^m
M_EXP = 0.5                  # exponent on unit discharge q (m3 per m width per storm)
N_EXP = 1.0                  # exponent on slope
VEG_K_DECAY = 3.0            # K = K_BARE * exp(-VEG_K_DECAY * cover)
V_BARE = 0.02                # settling parameter on bare ground, m (Davy & Lague V)
VEG_V_GAIN = 9.0             # V = V_BARE * (1 + VEG_V_GAIN * cover)
MFD_EXP = 1.1                # Freeman (1991) multiple-flow-direction exponent
ERO_LIMIT = 0.5              # never erode more than this fraction of the drop to the lowest neighbour in one pulse

# Creep (linear diffusion)
D_BARE = 0.005               # m2/yr on bare ground
VEG_D_GAIN = 1.0             # D = D_BARE * (1 + VEG_D_GAIN * cover) (bioturbation)

OPEN_EDGES = ["bottom"]      # last row is a fixed-elevation outlet; other edges closed
N_FRAMES = 11                # snapshots kept for the time slider

OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
DIST = np.array([DX * np.hypot(a, b) for a, b in OFFS])
# Quinn et al. (1991) style contour-length weights: 0.5 cardinal, 0.354 diagonal
CLEN = np.array([0.354 if a and b else 0.5 for a, b in OFFS])


# ----------------------------------------------------------------------------
# Inputs: surface, vegetation, storms
# ----------------------------------------------------------------------------
def default_surface(rng):
    """Convex crest, steep midslope, concave footslope and a gentle plain."""
    s = np.arange(NROWS) * DX                 # distance down the slope, m
    x = np.arange(NCOLS) * DX
    Ls = 150.0                                # length of the hillslope proper
    g = np.where(s < Ls, 0.012 + 0.23 * np.sin(np.pi * np.clip(s / Ls, 0, 1)) ** 1.5, 0.012)
    prof = np.concatenate([[0.0], np.cumsum(0.5 * (g[1:] + g[:-1]) * DX)])
    z1d = prof[-1] - prof + 100.0             # base level 100 m at the foot
    taper = np.sin(np.pi * np.clip(s / Ls, 0, 1))  # undulation fades at crest and plain
    und = 0.8 * np.cos(2 * np.pi * (x - 30.0) / 90.0) + 0.3 * np.cos(2 * np.pi * x / 37.0)
    z = z1d[:, None] + taper[:, None] * und[None, :]
    rough = gaussian_filter(rng.normal(0.0, 1.0, z.shape), 1.0)
    rough *= 0.03 / rough.std()               # ~3 cm microtopography
    z = z + rough
    return z.astype(np.float64)


def make_vegetation(rng):
    """Patchy shrub/grass cover, patches slightly elongated along the contour."""
    n = gaussian_filter(rng.normal(0.0, 1.0, (NROWS, NCOLS)), sigma=(1.8, 3.5), mode="wrap")
    n = (n - n.mean()) / n.std()
    thr = np.quantile(n, 0.62)                # ~38 % of the ground in patches
    patch = np.clip((n - thr) / 0.6, 0.0, 1.0)
    veg = 0.05 + 0.85 * patch                 # sparse annuals between patches
    return np.clip(veg, 0.0, 1.0)


def make_storms(rng):
    """Poisson storm arrivals with exponential depths (unscaled)."""
    n = rng.poisson(STORM_RATE_PER_YR * YEARS)
    t = np.sort(rng.uniform(0.0, YEARS, n))
    d = rng.exponential(STORM_MEAN_MM, n)
    return t, d


def veg_fields(veg):
    """How vegetation sets each process parameter (see module docstring)."""
    return dict(
        infil=(INFIL_BARE_MM + (INFIL_VEG_MM - INFIL_BARE_MM) * veg) / 1000.0,  # m per storm
        capture=RUNON_CAPTURE * veg,
        K=K_BARE * np.exp(-VEG_K_DECAY * veg),
        V=V_BARE * (1.0 + VEG_V_GAIN * veg),
        D=D_BARE * (1.0 + VEG_D_GAIN * veg),
    )


# ----------------------------------------------------------------------------
# Process 2: flow routing and overland-flow erosion / deposition
# ----------------------------------------------------------------------------
_IDX = np.arange(NROWS * NCOLS).reshape(NROWS, NCOLS)
_IDXP = np.pad(_IDX, 1, constant_values=-1)
OUTLET = np.zeros((NROWS, NCOLS), bool)
OUTLET[-1, :] = True
OUTLET_F = OUTLET.ravel()


def route_flow(z):
    """Multiple-flow-direction weights to lower neighbours.

    Returns donor index, receiver index, weight (sums to 1 per donor), the
    flow-weighted slope, the drop to the lowest neighbour, a topological order
    (high to low) and the inverse permutation."""
    zp = np.pad(z, 1, constant_values=np.inf)          # closed edges: never flow off
    S = np.empty((8, NROWS, NCOLS))
    for k, (a, b) in enumerate(OFFS):
        S[k] = (z - zp[1 + a:1 + a + NROWS, 1 + b:1 + b + NCOLS]) / DIST[k]
    S[:, OUTLET] = 0.0                                  # outlet row: water leaves the grid
    Sp = np.where(S > 0.0, S, 0.0)
    w = CLEN[:, None, None] * Sp ** MFD_EXP
    tot = w.sum(0)
    has = tot > 0
    w = np.where(has, w / np.where(has, tot, 1.0), 0.0)
    slope = (w * Sp).sum(0)
    drop = (Sp * DIST[:, None, None]).max(0)
    donors, recv, wts = [], [], []
    for k, (a, b) in enumerate(OFFS):
        m = w[k] > 0.0
        donors.append(_IDX[m])
        recv.append(_IDXP[1 + a:1 + a + NROWS, 1 + b:1 + b + NCOLS][m])
        wts.append(w[k][m])
    donors = np.concatenate(donors)
    recv = np.concatenate(recv)
    wts = np.concatenate(wts)
    order = np.argsort(-z.ravel(), kind="stable")
    inv = np.empty_like(order)
    inv[order] = np.arange(order.size)
    # Sparse structure of the strictly lower-triangular (in high-to-low order)
    # donor->receiver matrix, built once per pulse and shared by both solves.
    N = order.size
    pr, pc = inv[recv], inv[donors]
    perm = np.argsort(pr * N + pc, kind="stable")
    indptr = np.concatenate([[0], np.cumsum(np.bincount(pr, minlength=N))])
    return dict(d=donors, r=recv, w=wts, slope=slope.ravel(), drop=drop.ravel(),
                pit=(~has.ravel()) & (~OUTLET_F), inv=inv, order=order,
                perm=perm, indices=pc[perm].astype(np.int32), indptr=indptr.astype(np.int32))


def _downslope_solve(rt, f, src):
    """Solve X_i = f_i * (sum_{donors j} w_ji X_j + src_i), i.e.
    (I - diag(f) W^T) X = f * src, by forward substitution in high-to-low order."""
    N = f.size
    vals = (-f[rt["r"]] * rt["w"])[rt["perm"]]
    M = sp.csr_matrix((vals, rt["indices"], rt["indptr"]), shape=(N, N))
    M.has_sorted_indices = True
    xs = spl.spsolve_triangular(M, (f * src)[rt["order"]], lower=True, unit_diagonal=True)
    x = np.empty(N)
    x[rt["order"]] = xs
    return x


def storm_pulse(z, P_m, vf, frac):
    """One storm (or a fraction `frac` of it) of depth P_m metres.

    Runoff is generated from the whole storm; erosion and deposition are
    applied for `frac` of the storm so that a storm split into halves gives
    the same total work with the surface updated in between.
    Returns (dz, exported volume m3, gross eroded volume m3, water Q m3)."""
    rt = route_flow(z)
    zf = z.ravel()
    # --- water: Hortonian excess on each cell, part of run-on soaked up in patches
    runoff = np.maximum(P_m - vf["infil"].ravel(), 0.0) * CELL_AREA     # m3
    keep = 1.0 - vf["capture"].ravel()
    keep[OUTLET_F] = 1.0
    Q = _downslope_solve(rt, keep, runoff)                               # m3 leaving each cell
    # --- detachment, limited so a cell never drops below its lowest neighbour
    q = Q / DX                                                           # m3 per m width
    E = vf["K"].ravel() * q ** M_EXP * rt["slope"] ** N_EXP * frac       # m
    E = np.minimum(E, ERO_LIMIT * rt["drop"])
    E[OUTLET_F] = 0.0
    # --- sediment: Qs_out = f (Qs_in + E A), f = 1/(1 + V A / Q); pits keep everything
    V = vf["V"].ravel()
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(Q > 0.0, 1.0 / (1.0 + V * CELL_AREA / np.where(Q > 0, Q, 1.0)), 0.0)
    f[rt["pit"]] = 0.0
    f[OUTLET_F] = 1.0
    Qs = _downslope_solve(rt, f, E * CELL_AREA)
    Qs_in = np.bincount(rt["r"], weights=Qs[rt["d"]] * rt["w"], minlength=zf.size)
    dep = (Qs_in + E * CELL_AREA - Qs) / CELL_AREA                       # deposition depth, m
    dz = dep - E
    dz[OUTLET_F] = 0.0
    exported = Qs[OUTLET_F].sum()
    return dz.reshape(z.shape), exported, (E * CELL_AREA).sum(), Q.reshape(z.shape)


# ----------------------------------------------------------------------------
# Process 1: creep
# ----------------------------------------------------------------------------
def creep_step(z, D, dt):
    """Explicit, flux-form linear diffusion. Top, left and right edges are
    no-flux; the bottom row is a fixed base level, and what creeps into it is
    counted as exported. Returns (dz, exported m3)."""
    Dmax = D.max()
    nsub = max(1, int(np.ceil(dt * Dmax * 4.0 / DX ** 2 / 0.4)))   # keep r <= 0.1 per sub-step
    h = dt / nsub
    Dy = 0.5 * (D[1:, :] + D[:-1, :])
    Dx = 0.5 * (D[:, 1:] + D[:, :-1])
    zz = z.copy()
    exported = 0.0
    for _ in range(nsub):
        fy = -Dy * (zz[1:, :] - zz[:-1, :]) / DX        # m2/yr, positive = downward (to higher row)
        fx = -Dx * (zz[:, 1:] - zz[:, :-1]) / DX
        div = np.zeros_like(zz)
        div[:-1, :] -= fy
        div[1:, :] += fy
        div[:, :-1] -= fx
        div[:, 1:] += fx
        d = div * h / DX
        exported += d[-1, :].sum() * CELL_AREA
        d[-1, :] = 0.0
        zz += d
    return zz - z, exported


# ----------------------------------------------------------------------------
# Main time loop
# ----------------------------------------------------------------------------
def run_model(z0, veg, storm_t, storm_d, rain_scale=1.0, dt_scale=1.0, n_frames=N_FRAMES, verbose=False):
    vf = veg_fields(veg)
    dt = DT_BASE * dt_scale
    nsteps = int(np.ceil(YEARS / dt - 1e-9))
    n_split = max(1, int(round(1.0 / dt_scale))) if dt_scale < 1.0 else 1
    z = z0.copy()
    exported = 0.0
    gross = 0.0
    flow_cum = np.zeros_like(z)
    frame_years = np.linspace(0.0, YEARS, n_frames)
    frames_z = [z0.copy()]
    frames_flow = [flow_cum.copy()]
    next_frame = 1
    depths = storm_d * rain_scale / 1000.0
    min_infil = vf["infil"].min()
    si = 0
    nstorm_eroding = 0
    t0 = time.time()
    for k in range(nsteps):
        t_end = min((k + 1) * dt, YEARS)
        # storms that fall in this step, in time order
        while si < storm_t.size and storm_t[si] < t_end:
            P = depths[si]
            si += 1
            if P <= min_infil:          # nothing runs off anywhere: no overland flow work
                continue
            nstorm_eroding += 1
            for _ in range(n_split):
                dz, ex, gr, Q = storm_pulse(z, P, vf, 1.0 / n_split)
                z += dz
                exported += ex
                gross += gr
                flow_cum += Q / n_split
        dzc, exc = creep_step(z, vf["D"], t_end - k * dt)
        z += dzc
        exported += exc
        gross += np.clip(-dzc, 0, None).sum() * CELL_AREA
        while next_frame < n_frames and t_end >= frame_years[next_frame] - 1e-9:
            frames_z.append(z.copy())
            frames_flow.append(flow_cum.copy())
            next_frame += 1
        if verbose and (k + 1) % max(1, nsteps // 10) == 0:
            print(f"  step {k + 1}/{nsteps}  t={t_end:.0f} yr  elapsed {time.time() - t0:.1f}s",
                  file=sys.stderr, flush=True)
    vol_change = (z - z0).sum() * CELL_AREA
    mb_err = 100.0 * (vol_change + exported) / max(gross, 1e-30) if gross > 0 else 0.0
    return dict(z=z, exported=exported, gross=gross, mb_err=mb_err, nsteps=nsteps, dt=dt,
                frames_z=frames_z, frames_flow=frames_flow, frame_years=frame_years,
                n_eroding_storms=nstorm_eroding)


# ----------------------------------------------------------------------------
# Static map (PNG)
# ----------------------------------------------------------------------------
DRY_COLORS = ["#6b4f3a", "#9a6b45", "#c48a52", "#d9b077", "#e9d3a6", "#f5ead2"]
VE_SHADE = 3.0


def dryland_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list("dryland", DRY_COLORS)


def change_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list(
        "lossgain", ["#7f2704", "#d0661e", "#f3c99a", "#f7f7f2", "#9fd3c7", "#2a8f86", "#01414a"])


def make_png(path, z0, z, veg, flow, years):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, TwoSlopeNorm, LinearSegmentedColormap

    ls = LightSource(azdeg=315, altdeg=40)
    ext = [0, NCOLS * DX, NROWS * DX, 0]
    fig, axs = plt.subplots(2, 2, figsize=(12, 11.5), constrained_layout=True)
    # terrain
    ax = axs[0, 0]
    rgb = ls.shade(z, cmap=dryland_cmap(), vert_exag=VE_SHADE, dx=DX, dy=DX, blend_mode="soft")
    ax.imshow(rgb, extent=ext)
    sm = plt.cm.ScalarMappable(cmap=dryland_cmap(), norm=plt.Normalize(z.min(), z.max()))
    fig.colorbar(sm, ax=ax, shrink=0.8, label="Elevation (m)")
    ax.set_title(f"Terrain after {years:.0f} years\n(hillshade with {VE_SHADE:.0f}x vertical exaggeration)")
    # change
    ax = axs[0, 1]
    dz = (z - z0) * 1000.0
    lim = max(np.percentile(np.abs(dz), 99.5), 1e-3)
    hs = ls.hillshade(z, vert_exag=VE_SHADE, dx=DX, dy=DX)
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1)
    im = ax.imshow(dz, cmap=change_cmap(), norm=TwoSlopeNorm(0.0, -lim, lim), extent=ext, alpha=0.85)
    fig.colorbar(im, ax=ax, shrink=0.8, extend="both",
                 label="Elevation change (mm): brown = lost, teal = gained")
    ax.set_title("Where the surface lost and gained material")
    # vegetation
    ax = axs[1, 0]
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1)
    vcm = LinearSegmentedColormap.from_list("veg", ["#efe3c4", "#a7b86a", "#4f7a2a", "#1f4214"])
    im = ax.imshow(veg, cmap=vcm, vmin=0, vmax=1, extent=ext, alpha=0.85)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Vegetation cover (fraction 0-1)")
    ax.set_title("Vegetation patches")
    # flow
    ax = axs[1, 1]
    ax.imshow(hs, cmap="gray", extent=ext, vmin=0, vmax=1)
    lf = np.log10(np.maximum(flow, 1e-2))
    fcm = LinearSegmentedColormap.from_list("flow", ["#f3ead7", "#9cc3d5", "#2f7fb0", "#08306b"])
    lo = np.percentile(lf, 5)
    im = ax.imshow(lf, cmap=fcm, extent=ext, alpha=0.85, vmin=lo, vmax=max(lf.max(), lo + 1))
    fig.colorbar(im, ax=ax, shrink=0.8,
                 label="log10 total runoff through cell over the run (m3)")
    ax.set_title("Overland flow paths")
    for ax in axs.ravel():
        ax.set_xlabel("Across slope (m)")
        ax.set_ylabel("Down slope (m)  - foot of slope at bottom")
        # scale bar 50 m
        x0, y0 = 10, NROWS * DX - 10
        ax.plot([x0, x0 + 50], [y0, y0], color="k", lw=4, solid_capstyle="butt")
        ax.plot([x0, x0 + 50], [y0, y0], color="w", lw=2, solid_capstyle="butt")
        ax.text(x0 + 25, y0 - 4, "50 m", ha="center", va="bottom", fontsize=9,
                bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    fig.suptitle("Simulated dryland hillslope: erosion and deposition", fontsize=14)
    fig.savefig(path, dpi=90)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Interactive map (self-contained HTML)
# ----------------------------------------------------------------------------
def _b64(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii")


def _pack_scenario(res, z0):
    dz = np.stack([f - z0 for f in res["frames_z"]])
    sc = max(np.abs(dz).max() / 32000.0, 1e-7)
    dzq = np.round(dz / sc).astype("<i2")
    fl = np.stack(res["frames_flow"])
    lf = np.log10(np.maximum(fl, 1e-2))      # log10 m3, stored as -2 .. 7 in 255 steps
    lfq = np.clip(np.round((lf + 2.0) / 9.0 * 255.0), 0, 255).astype(np.uint8)
    return dict(dz=_b64(dzq), dzScale=float(sc), flow=_b64(lfq),
                exported=round(float(res["exported"]), 2))


def make_html(path, z0, veg, scenarios, years, telemetry):
    data = dict(
        rows=NROWS, cols=NCOLS, dx=DX, years=years, ve=VE_SHADE,
        frameYears=[float(y) for y in scenarios[0][1]["frame_years"]],
        z0=_b64(z0.astype("<f4")), veg=_b64(np.round(veg * 255).astype(np.uint8)),
        scen=[dict(name=n, note=note, **_pack_scenario(r, z0)) for n, r, note in scenarios],
        telemetry=telemetry,
    )
    html = HTML_TEMPLATE.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dryland hillslope: erosion and deposition explorer</title>
<style>
 body{font-family:Georgia,'Times New Roman',serif;background:#f6efe0;color:#3b2b1d;margin:0;}
 header{background:#7a5232;color:#fbf3e2;padding:12px 20px;}
 header h1{margin:0;font-size:1.5em;} header p{margin:4px 0 0 0;}
 main{display:flex;flex-wrap:wrap;gap:20px;padding:16px 20px;}
 #mapcol{flex:0 0 auto;} #side{flex:1 1 360px;max-width:640px;}
 #mapwrap{position:relative;border:2px solid #7a5232;background:#fff;width:600px;height:600px;}
 canvas#map{width:600px;height:600px;image-rendering:auto;display:block;}
 .ctl{background:#fffaf0;border:1px solid #d8c4a0;border-radius:6px;padding:10px 12px;margin-bottom:10px;}
 .ctl label{margin-right:12px;white-space:nowrap;}
 .ctl h3{margin:0 0 6px 0;font-size:1em;}
 #legend{margin-top:8px;} #readout{font-family:monospace;font-size:0.9em;min-height:1.4em;}
 #yearlab{font-weight:bold;}
 .note{font-size:0.92em;line-height:1.4;}
 table.tele{font-family:monospace;font-size:0.8em;border-collapse:collapse;}
 table.tele td{border-bottom:1px solid #e6d8bc;padding:1px 6px;}
 .arrow{position:absolute;right:8px;top:8px;background:rgba(255,250,240,.85);padding:2px 6px;font-size:.85em;border-radius:4px;}
</style>
</head>
<body>
<header>
 <h1>Dryland hillslope: where soil is lost and where it piles up</h1>
 <p>A simulated 200 m &times; 200 m desert hillslope, followed for <span id="yrs"></span> years of random storms.</p>
</header>
<main>
<div id="mapcol">
 <div id="mapwrap"><canvas id="map" width="600" height="600"></canvas>
  <div class="arrow">crest (top) &darr; downslope &darr; foot (bottom)</div></div>
 <div id="readout">Move the pointer over the map to read values.</div>
 <div id="legend"><canvas id="legcanvas" width="600" height="62"></canvas></div>
</div>
<div id="side">
 <div class="ctl"><h3>Time</h3>
  <input type="range" id="time" data-bench="time" min="0" max="10" step="1" value="10" style="width:75%">
  <span id="yearlab"></span>
  <button id="play" data-bench="play">&#9654; play</button>
 </div>
 <div class="ctl"><h3>Layer</h3>
  <label><input type="radio" name="layer" value="terrain" data-bench="layer-terrain" checked> Terrain</label>
  <label><input type="radio" name="layer" value="change" data-bench="layer-change"> Loss / gain</label>
  <label><input type="radio" name="layer" value="veg" data-bench="layer-vegetation"> Vegetation</label>
  <label><input type="radio" name="layer" value="flow" data-bench="layer-flow"> Overland flow</label>
  <div style="margin-top:6px"><label><input type="checkbox" id="vegoutline" data-bench="veg-outline"> outline vegetation patches</label></div>
 </div>
 <div class="ctl"><h3>Scenario (separate model runs, same storms and patch pattern)</h3>
  <select id="scen" data-bench="scenario"></select>
  <div id="scennote" class="note"></div>
 </div>
 <div class="ctl"><h3>Hillshade vertical exaggeration: <span id="velab"></span>&times;</h3>
  <input type="range" id="ve" data-bench="vertical-exaggeration" min="1" max="10" step="1" value="3" style="width:75%">
  <div class="note">Shading only: heights are stretched this many times to make small relief visible. Colours and numbers are not exaggerated.</div>
 </div>
 <div class="ctl note"><h3>What you are looking at</h3>
  <p>Row 0 (top of the map) is the crest of the hill; the slope falls toward the bottom edge, where a gentle plain meets a fixed base level. Sediment that reaches the bottom edge leaves the map and is counted (<span id="exp"></span> m&sup3; in this scenario).</p>
  <p><b>Loss / gain</b> colours show the change in ground height since year 0: <span style="color:#a0400b">brown = soil lost (erosion)</span>, <span style="color:#1f7f78">teal = soil gained (deposition)</span>. White means no change. The scale is centred on zero.</p>
 </div>
 <div class="ctl note"><h3>Landforms to look for</h3>
  <ul>
   <li><b>Rills and small gullies</b> in the hollows, where overland flow gathers: brown streaks on the loss/gain layer, dark blue on the flow layer.</li>
   <li><b>Sediment aprons and small fans</b> at the foot of the slope, where it flattens and the water slows: a teal band near the bottom.</li>
   <li><b>Mounds behind plants</b>: vegetation patches soak up run-on and trap sediment, so they gain soil (teal) while the bare ground between them loses it (brown).</li>
   <li><b>Rounded crest</b>: at the top, where little water collects, slow creep dominates and rounds the hill.</li>
  </ul>
 </div>
 <div class="ctl note"><h3>What the model assumes</h3>
  <ul>
   <li><b>Rain</b> arrives as separate storms at random times (about 16 a year, about 190 mm a year in total). Most storms are small; a few are large.</li>
   <li><b>Runoff</b>: in each storm the soil soaks up a fixed depth (6 mm on bare crusted ground, up to 25 mm under plants). Only the rest runs off, downhill, split among all lower neighbours.</li>
   <li><b>Plants</b> soak up part of the water that runs into them, make the soil harder to erode, catch sediment, and their roots and burrowing animals stir the soil so it creeps a little faster.</li>
   <li><b>Erosion</b> grows with the amount of water and the steepness. Moving water drops part of its load in every cell, more where it is slow (gentle slopes, plants). The rest is carried on.</li>
   <li><b>Creep</b>: soil slowly moves downhill in proportion to slope everywhere, rain or not.</li>
   <li>Nothing is lifted up by tectonics; the plants do not grow or die during the run. Soil is assumed thick enough never to run out.</li>
  </ul>
 </div>
 <div class="ctl"><h3>Run details (telemetry)</h3><table class="tele" id="tele"></table></div>
</div>
</main>
<script>
const DATA = /*__DATA__*/null;
(function(){
"use strict";
const R = DATA.rows, C = DATA.cols, N = R*C, DX = DATA.dx;
function b64bytes(s){const bin = atob(s); const u = new Uint8Array(bin.length); for(let i=0;i<bin.length;i++) u[i]=bin.charCodeAt(i); return u;}
const z0 = new Float32Array(b64bytes(DATA.z0).buffer);
const veg = b64bytes(DATA.veg);
const NF = DATA.frameYears.length;
const scen = DATA.scen.map(function(s){
  return {name:s.name, note:s.note, exported:s.exported, dz:new Int16Array(b64bytes(s.dz).buffer), sc:s.dzScale, flow:b64bytes(s.flow)};
});
const DRY = [[0x6b,0x4f,0x3a],[0x9a,0x6b,0x45],[0xc4,0x8a,0x52],[0xd9,0xb0,0x77],[0xe9,0xd3,0xa6],[0xf5,0xea,0xd2]];
const CHG = [[0x7f,0x27,0x04],[0xd0,0x66,0x1e],[0xf3,0xc9,0x9a],[0xf7,0xf7,0xf2],[0x9f,0xd3,0xc7],[0x2a,0x8f,0x86],[0x01,0x41,0x4a]];
const VEGC = [[0xef,0xe3,0xc4],[0xa7,0xb8,0x6a],[0x4f,0x7a,0x2a],[0x1f,0x42,0x14]];
const FLOWC = [[0xf3,0xea,0xd7],[0x9c,0xc3,0xd5],[0x2f,0x7f,0xb0],[0x08,0x30,0x6b]];
function ramp(cols, t){ t = Math.min(1, Math.max(0, t)); const x = t*(cols.length-1); const i = Math.min(cols.length-2, Math.floor(x)); const f = x-i;
  return [cols[i][0]+(cols[i+1][0]-cols[i][0])*f, cols[i][1]+(cols[i+1][1]-cols[i][1])*f, cols[i][2]+(cols[i+1][2]-cols[i][2])*f]; }
const st = {frame:NF-1, layer:"terrain", s:0, ve:DATA.ve, outline:false};
// fixed colour limits so pictures are comparable across time and scenarios
let zmin=Infinity, zmax=-Infinity; for(let i=0;i<N;i++){ if(z0[i]<zmin) zmin=z0[i]; if(z0[i]>zmax) zmax=z0[i]; }
// change colour limit: per scenario (99.5th percentile of |final change|), fixed through time
for(const s of scen){ const vals=[]; for(let i=0;i<N;i++) vals.push(Math.abs(s.dz[(NF-1)*N+i]*s.sc));
  vals.sort(function(a,b){return a-b;}); s.lim = Math.max(1e-4, vals[Math.floor(0.995*(vals.length-1))]); }
let chgLim = scen[0].lim;
let flowMax = 0, flowMin = 0; { const vals=[]; for(const s of scen){ for(let i=0;i<N;i++){ const v=s.flow[(NF-1)*N+i]; vals.push(v); if(v>flowMax) flowMax=v; } }
  vals.sort(function(a,b){return a-b;}); flowMin = Math.min(vals[Math.floor(0.05*(vals.length-1))], flowMax-1); }
function frameZ(s, f){ const z = new Float32Array(N); const d = scen[s].dz, sc = scen[s].sc; for(let i=0;i<N;i++) z[i] = z0[i] + d[f*N+i]*sc; return z; }
// Standard (Horn/ESRI-style) hillshade, sun from the north-west (azimuth 315 deg), 40 deg above the horizon.
// dzdy is taken positive toward the bottom (south) of the map, as in the ESRI formulation.
function hillshade(z, ve){ const hs = new Float32Array(N); const azMath = (360 - 315 + 90)*Math.PI/180, alt = 40*Math.PI/180;
  for(let r=0;r<R;r++) for(let c=0;c<C;c++){
    const cl = Math.max(0,c-1), cr = Math.min(C-1,c+1), ru = Math.max(0,r-1), rd = Math.min(R-1,r+1);
    const dzdx = ve*(z[r*C+cr]-z[r*C+cl])/((cr-cl)*DX); const dzdy = ve*(z[rd*C+c]-z[ru*C+c])/((rd-ru)*DX);
    const slope = Math.atan(Math.hypot(dzdx, dzdy)); const aspect = Math.atan2(dzdy, -dzdx);
    let v = Math.sin(alt)*Math.cos(slope) + Math.cos(alt)*Math.sin(slope)*Math.cos(azMath - aspect);
    hs[r*C+c] = Math.max(0, v);
  } return hs; }
const cv = document.getElementById("map"), ctx = cv.getContext("2d");
const off = document.createElement("canvas"); off.width = C; off.height = R; const octx = off.getContext("2d");
function draw(){
  const s = st.s, f = st.frame, z = frameZ(s, f), hs = hillshade(z, st.ve);
  chgLim = scen[s].lim;
  const img = octx.createImageData(C, R);
  for(let i=0;i<N;i++){
    let col, shade = 0.35 + 0.75*hs[i];
    if(st.layer === "terrain"){ col = ramp(DRY, (z[i]-zmin)/(zmax-zmin)); }
    else if(st.layer === "change"){ const d = scen[s].dz[f*N+i]*scen[s].sc; col = ramp(CHG, 0.5 + 0.5*d/chgLim); shade = 0.75 + 0.3*hs[i]; }
    else if(st.layer === "veg"){ col = ramp(VEGC, veg[i]/255); shade = 0.6 + 0.5*hs[i]; }
    else { col = ramp(FLOWC, (scen[s].flow[f*N+i]-flowMin)/Math.max(1, flowMax-flowMin)); shade = 0.6 + 0.5*hs[i]; }
    img.data[4*i] = Math.min(255, col[0]*shade); img.data[4*i+1] = Math.min(255, col[1]*shade); img.data[4*i+2] = Math.min(255, col[2]*shade); img.data[4*i+3] = 255;
  }
  octx.putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = true; ctx.drawImage(off, 0, 0, cv.width, cv.height);
  if(st.outline){ ctx.fillStyle = "rgba(20,60,10,0.9)"; const px = cv.width/C;
    for(let r=0;r<R;r++) for(let c=0;c<C;c++){ const a = veg[r*C+c] > 100;
      if(c<C-1 && a !== (veg[r*C+c+1] > 100)) ctx.fillRect((c+1)*px-0.75, r*px, 1.5, px);
      if(r<R-1 && a !== (veg[(r+1)*C+c] > 100)) ctx.fillRect(c*px, (r+1)*px-0.75, px, 1.5); } }
  drawScaleBar(); drawLegend();
  document.getElementById("yearlab").textContent = "year " + Math.round(DATA.frameYears[f]) + " of " + Math.round(DATA.years);
  document.getElementById("velab").textContent = st.ve;
  document.getElementById("exp").textContent = scen[s].exported.toFixed(1);
  document.getElementById("scennote").textContent = scen[s].note;
}
function drawScaleBar(){ const px = cv.width/(C*DX); const len = 50*px, x0 = 16, y0 = cv.height - 22;
  ctx.fillStyle = "rgba(255,250,240,0.85)"; ctx.fillRect(x0-6, y0-20, len+12, 30);
  ctx.fillStyle = "#222"; ctx.fillRect(x0, y0, len/2, 6); ctx.strokeStyle = "#222"; ctx.lineWidth = 1; ctx.strokeRect(x0, y0, len, 6);
  ctx.font = "12px Georgia"; ctx.textAlign = "left"; ctx.fillText("0", x0-3, y0-4); ctx.textAlign = "right"; ctx.fillText("50 m", x0+len+4, y0-4); }
function drawLegend(){ const lc = document.getElementById("legcanvas"), g = lc.getContext("2d"); g.clearRect(0,0,lc.width,lc.height);
  let cols, lo, hi, title, fmt = function(v){return v.toFixed(1);};
  if(st.layer === "terrain"){ cols = DRY; lo = zmin; hi = zmax; title = "Elevation (m above base level datum); shading exaggerated " + st.ve + "x vertically"; }
  else if(st.layer === "change"){ cols = CHG; lo = -chgLim*1000; hi = chgLim*1000; title = "Change in ground height since year 0 (mm): brown = lost, white = 0, teal = gained (scale set per scenario)"; fmt = function(v){return v.toFixed(0);}; }
  else if(st.layer === "veg"){ cols = VEGC; lo = 0; hi = 1; title = "Vegetation cover (fraction of the cell, 0 = bare, 1 = full)"; fmt = function(v){return v.toFixed(2);}; }
  else { cols = FLOWC; lo = -2 + 9*flowMin/255; hi = -2 + 9*flowMax/255; title = "Total runoff that passed through a cell since year 0 (m³, log scale: 10^value)"; }
  g.font = "13px Georgia"; g.fillStyle = "#3b2b1d"; g.textAlign = "left"; g.fillText(title, 10, 14);
  for(let x=0;x<560;x++){ const c = ramp(cols, x/559); g.fillStyle = "rgb("+(c[0]|0)+","+(c[1]|0)+","+(c[2]|0)+")"; g.fillRect(20+x, 20, 1, 16); }
  g.strokeStyle = "#555"; g.strokeRect(20, 20, 560, 16); g.fillStyle = "#3b2b1d"; g.textAlign = "center";
  for(let k=0;k<=4;k++){ const v = lo + (hi-lo)*k/4; g.fillText(fmt(v), 20+560*k/4, 52); g.fillRect(20+560*k/4, 36, 1, 4); } }
cv.addEventListener("mousemove", function(e){ const rc = cv.getBoundingClientRect();
  const c = Math.floor((e.clientX-rc.left)/rc.width*C), r = Math.floor((e.clientY-rc.top)/rc.height*R); if(r<0||c<0||r>=R||c>=C) return; const i = r*C+c;
  const s = scen[st.s], d = s.dz[st.frame*N+i]*s.sc;
  document.getElementById("readout").textContent = "x " + (c*DX).toFixed(0) + " m, y " + (r*DX).toFixed(0) + " m | elevation " + (z0[i]+d).toFixed(2) + " m | change " + (d*1000).toFixed(1) + " mm | cover " + (veg[i]/255).toFixed(2); });
const sel = document.getElementById("scen"); scen.forEach(function(s, i){ const o = document.createElement("option"); o.value = i; o.textContent = s.name; sel.appendChild(o); });
sel.addEventListener("change", function(){ st.s = +sel.value; draw(); });
const tm = document.getElementById("time"); tm.max = NF-1; tm.value = NF-1;
tm.addEventListener("input", function(){ st.frame = +tm.value; draw(); });
document.querySelectorAll("input[name=layer]").forEach(function(el){ el.addEventListener("change", function(){ st.layer = el.value; draw(); }); });
document.getElementById("ve").addEventListener("input", function(e){ st.ve = +e.target.value; draw(); });
document.getElementById("vegoutline").addEventListener("change", function(e){ st.outline = e.target.checked; draw(); });
let timer = null; document.getElementById("play").addEventListener("click", function(){
  if(timer){ clearInterval(timer); timer = null; return; } st.frame = 0;
  timer = setInterval(function(){ tm.value = st.frame; draw(); st.frame++; if(st.frame >= NF){ clearInterval(timer); timer = null; st.frame = NF-1; } }, 500); });
document.getElementById("yrs").textContent = Math.round(DATA.years);
const tb = document.getElementById("tele"); Object.keys(DATA.telemetry).forEach(function(k){ const tr = document.createElement("tr");
  tr.innerHTML = "<td>"+k+"</td><td>"+JSON.stringify(DATA.telemetry[k])+"</td>"; tb.appendChild(tr); });
draw();
window.__bench = {draw:draw, state:st};
})();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--z0", default=None)
    ap.add_argument("--rain-scale", type=float, default=1.0)
    ap.add_argument("--veg-scale", type=float, default=1.0)
    ap.add_argument("--dt-scale", type=float, default=1.0)
    ap.add_argument("--no-map", action="store_true")
    a = ap.parse_args(argv)
    if a.dt_scale <= 0 or a.rain_scale < 0 or a.veg_scale < 0:
        ap.error("--dt-scale must be > 0; --rain-scale and --veg-scale must be >= 0")

    t_start = time.time()
    ss = np.random.SeedSequence(a.seed)
    rng_rough, rng_veg, rng_storm = [np.random.default_rng(s) for s in ss.spawn(3)]

    if a.z0:
        z0 = np.load(a.z0).astype(np.float64)
        if z0.shape != (NROWS, NCOLS):
            sys.exit(f"--z0 must have shape {(NROWS, NCOLS)} with {DX} m cells; got {z0.shape}")
    else:
        z0 = default_surface(rng_rough)
    veg_base = make_vegetation(rng_veg)
    veg = np.clip(veg_base * a.veg_scale, 0.0, 1.0)
    storm_t, storm_d = make_storms(rng_storm)

    res = run_model(z0, veg, storm_t, storm_d, a.rain_scale, a.dt_scale, verbose=True)

    os.makedirs(a.out, exist_ok=True)
    np.save(os.path.join(a.out, "z_initial.npy"), z0)
    np.save(os.path.join(a.out, "z_final.npy"), res["z"])
    np.save(os.path.join(a.out, "vegetation.npy"), veg)
    with open(os.path.join(a.out, "storms.csv"), "w") as fh:
        fh.write("year,depth_mm\n")
        for t, d in zip(storm_t, storm_d):
            fh.write(f"{t:.6f},{d:.6f}\n")
    tel = dict(
        seed=a.seed,
        grid_shape=[NROWS, NCOLS],
        cell_size_m=DX,
        years_simulated=YEARS,
        timesteps=int(res["nsteps"]),
        dt_years=float(res["dt"]),
        storm_count=int(storm_t.size),
        mean_annual_rain_mm=float(storm_d.sum() * a.rain_scale / YEARS),
        creep_diffusivity_m2_per_yr=D_BARE,
        open_boundaries=list(OPEN_EDGES),
        sediment_exported_m3=float(res["exported"]),
        uplift_or_baselevel_m3=0.0,
        mass_balance_error_pct=float(res["mb_err"]),
    )
    with open(os.path.join(a.out, "telemetry.json"), "w") as fh:
        json.dump(tel, fh, indent=2)

    if not a.no_map:
        make_png(os.path.join(a.out, "map.png"), z0, res["z"], veg, res["frames_flow"][-1], YEARS)
        scenarios = [("This run", res, f"Rain x{a.rain_scale:g}, vegetation x{a.veg_scale:g}: the run whose files are in this folder.")]
        extra = [("Bare ground (vegetation x0)", 0.0, "Same storms, no plants: more runoff, faster erosion, sediment carried further."),
                 ("Dense vegetation (vegetation x2)", 2.0, "Same storms, twice the cover (capped at full): less runoff and more trapping.")]
        for name, vs, note in extra:
            print(f"scenario run: {name}", file=sys.stderr, flush=True)
            r2 = run_model(z0, np.clip(veg_base * vs, 0.0, 1.0), storm_t, storm_d, a.rain_scale, a.dt_scale)
            scenarios.append((name, r2, note))
        make_html(os.path.join(a.out, "map.html"), z0, veg, scenarios, YEARS, tel)

    print(json.dumps(tel, indent=2))
    print(f"eroding storms: {res['n_eroding_storms']}, wall time {time.time() - t_start:.1f} s", file=sys.stderr)


if __name__ == "__main__":
    main()
