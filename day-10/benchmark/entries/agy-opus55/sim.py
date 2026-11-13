#!/usr/bin/env python3
"""Dryland hillslope erosion / deposition teaching model.

Processes (all coupled through the elevation grid z):
  1. Hillslope creep: linear diffusion, flux q = -D(v) grad z           -> creep_step()
  2. Overland-flow erosion & deposition: D8 routing of storm runoff,
     transport capacity Qc ~ W^1.5 S^1.5, sediment flux relaxes toward
     capacity over a deposition length L (erosion where Qs < Qc,
     deposition where Qs > Qc); flux-divergence form, so mass is
     conserved and sediment is carried downslope                   -> overland_flow_event()
  3. Stochastic storms: Poisson arrivals, exponential depths          -> make_storms()
  4. Patchy vegetation (banded/spotted pattern) altering infiltration,
     run-on capture, transport capacity, deposition length and creep -> make_vegetation()

Usage:
  python3 sim.py --seed 42 --out OUTDIR [--z0 FILE] [--rain-scale F]
                 [--veg-scale F] [--dt-scale F] [--no-map]
"""
import argparse
import base64
import io
import json
import os
import sys
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.ndimage import gaussian_filter

# ----------------------------------------------------------------------------
# Model constants
# ----------------------------------------------------------------------------
NROWS, NCOLS = 120, 100        # grid (rows run downslope; row 0 = crest)
DX = 2.0                       # cell size, m
YEARS = 1000.0                 # simulated span, years
DT_BASE = 1.0                  # base time step, years

# Rain: Poisson storm arrivals with exponentially distributed depths
STORM_RATE = 20.0              # storms per year
STORM_MEAN_MM = 12.0           # mean storm depth, mm  (-> ~240 mm/yr)

# Infiltration (per storm, Hortonian excess): bare crusted soil vs. vegetated
I_BARE_MM = 8.0
I_VEG_MM = 30.0
RUNON_LOSS = 0.5               # fraction of passing run-on absorbed at full cover

# Creep
D_BARE = 0.005                 # m^2/yr on bare ground
D_VEG_GAIN = 1.0               # D = D_BARE * (1 + D_VEG_GAIN * v)  (bioturbation)

# Overland-flow transport
KC = 0.1                      # transport coefficient (calibrated, see reply)
M_EXP = 1.5                    # exponent on storm water per unit width
N_EXP = 1.5                    # exponent on slope
VEG_CAP_REDUCTION = 0.9        # capacity *(1 - 0.9 v)
L_BARE = 20.0                  # deposition (relaxation) length on bare soil, m
VEG_L_REDUCTION = 0.8          # L = L_BARE * (1 - 0.8 v)

SHADE_VE = 3.0                 # vertical exaggeration used in relief shading

# D8 neighbour offsets
OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
DIST = np.array([np.hypot(dr, dc) * DX for dr, dc in OFFS])

OPEN_BOUNDARIES = ["bottom"]   # top, left, right are closed (no flux)


# ----------------------------------------------------------------------------
# Random inputs
# ----------------------------------------------------------------------------
def rng_streams(seed):
    ss = np.random.SeedSequence(seed)
    s_veg, s_storm, s_rough = ss.spawn(3)
    return (np.random.default_rng(s_veg), np.random.default_rng(s_storm),
            np.random.default_rng(s_rough))


def default_surface(rng):
    """Concave hillslope (crest at row 0, footslope at last row) with two
    shallow swales and centimetre-scale random roughness."""
    r = np.arange(NROWS)[:, None] / (NROWS - 1.0)
    c = np.arange(NCOLS)[None, :] / (NCOLS - 1.0)
    z = 16.0 * (1 - r) ** 2 + 6.0 * (1 - r)
    z = z - 0.6 * np.cos(2 * np.pi * 2 * c) * np.sin(np.pi * np.clip(r * 1.1, 0, 1))
    rough = gaussian_filter(rng.standard_normal((NROWS, NCOLS)), 1.0)
    rough *= 0.02 / rough.std()
    return (z + rough).astype(np.float64)


def make_vegetation(rng):
    """Patchy cover 0..1: smoothed noise stretched along the contour (rows),
    giving the banded/spotted pattern typical of drylands."""
    g = gaussian_filter(rng.standard_normal((NROWS, NCOLS)), sigma=(1.5, 4.0),
                        mode="wrap")
    g = (g - g.mean()) / g.std()
    v = 0.95 / (1.0 + np.exp(-4.0 * (g - 0.45)))
    v[v < 0.05] = 0.0
    return v


def make_storms(rng):
    """Poisson storm arrivals, exponential depths (mm)."""
    n = rng.poisson(STORM_RATE * YEARS)
    t = np.sort(rng.uniform(0.0, YEARS, n))
    d = rng.exponential(STORM_MEAN_MM, n)
    return t, d


# ----------------------------------------------------------------------------
# Process 1: creep (linear diffusion, flux form)
# ----------------------------------------------------------------------------
def creep_step(z, D, zg, dt):
    """Explicit conservative diffusion over dt years. Top/left/right: no flux.
    Bottom: flux into a fixed base-level channel (ghost row zg), outward only.
    Returns (z_new, volume exported m^3, gross volume moved m^3)."""
    nsub = max(1, int(np.ceil(dt * D.max() / (0.2 * DX * DX))))
    h = dt / nsub
    Dx = 0.5 * (D[:, 1:] + D[:, :-1])
    Dy = 0.5 * (D[1:, :] + D[:-1, :])
    exported = 0.0
    gross = 0.0
    for _ in range(nsub):
        fx = -Dx * (z[:, 1:] - z[:, :-1]) / DX      # m^2/yr, col j -> j+1
        fy = -Dy * (z[1:, :] - z[:-1, :]) / DX      # m^2/yr, row i -> i+1
        fb = np.maximum(D[-1, :] * (z[-1, :] - zg) / DX, 0.0)  # out of bottom
        div = np.zeros_like(z)
        div[:, :-1] -= fx
        div[:, 1:] += fx
        div[:-1, :] -= fy
        div[1:, :] += fy
        div[-1, :] -= fb
        dz = div * h / DX
        z = z + dz
        exported += fb.sum() * DX * h
        gross += -dz[dz < 0].sum() * DX * DX
    return z, exported, gross


# ----------------------------------------------------------------------------
# Flow routing (D8) and network matrices
# ----------------------------------------------------------------------------
def d8_receivers(z, zg):
    """Steepest-descent receivers. rec >= 0: cell index; -2: leaves grid
    through the bottom edge; -1: pit (no lower neighbour). Also returns the
    distance to the receiver."""
    nr, nc = z.shape
    pad = np.full((nr + 2, nc + 2), np.inf)
    pad[1:-1, 1:-1] = z
    pad[-1, 1:-1] = zg
    best = np.zeros((nr, nc))
    kbest = np.full((nr, nc), -1)
    for k, (dr, dc) in enumerate(OFFS):
        nb = pad[1 + dr:1 + dr + nr, 1 + dc:1 + dc + nc]
        s = (z - nb) / DIST[k]
        better = s > best
        best = np.where(better, s, best)
        kbest = np.where(better, k, kbest)
    rows, cols = np.indices((nr, nc))
    dr = np.array([o[0] for o in OFFS] + [0])[kbest]
    dc = np.array([o[1] for o in OFFS] + [0])[kbest]
    rr, cc = rows + dr, cols + dc
    rec = np.where(kbest < 0, -1, np.where(rr >= nr, -2, rr * nc + cc))
    dist = np.where(kbest < 0, DX, DIST[np.maximum(kbest, 0)])
    return rec.ravel(), dist.ravel()


class Network:
    """Sparse, topologically ordered (lower-triangular) systems for routing
    water and sediment along D8 receivers; LU-factorised once per time step."""

    def __init__(self, z, zg, beta, a):
        self.N = z.size
        self.rec, self.dist = d8_receivers(z, zg)
        N = self.N
        order = np.argsort(-z.ravel(), kind="stable")
        pos = np.empty(N, dtype=np.int64)
        pos[order] = np.arange(N)
        self.order, self.pos = order, pos
        don = np.nonzero(self.rec >= 0)[0]
        self.don = don
        rows = np.r_[pos, pos[self.rec[don]]]
        cols = np.r_[pos, pos[don]]
        # water: y_i = r_i + sum_j (1-beta_j) y_j
        Mw = sp.csc_matrix((np.r_[np.ones(N), -(1 - beta[don])], (rows, cols)),
                           shape=(N, N))
        # sediment: (1+a_i) Qs_i - sum_j Qs_j = a_i Qc_i
        Ms = sp.csc_matrix((np.r_[1 + a, -np.ones(don.size)], (rows, cols)),
                           shape=(N, N))
        opts = dict(SymmetricMode=True)
        self.luw = spla.splu(Mw, permc_spec="NATURAL", options=opts)
        self.lus = spla.splu(Ms, permc_spec="NATURAL", options=opts)
        self.has_rec = self.rec != -1
        self.exits = self.rec == -2

    def solve_water(self, r):
        return self.luw.solve(r[self.order])[self.pos]

    def solve_sed(self, b):
        return self.lus.solve(b[self.order])[self.pos]

    def inflow(self, q):
        return np.bincount(self.rec[self.don], weights=q[self.don],
                           minlength=self.N)

    def slope(self, zf, zg):
        zr = np.empty_like(zf)
        internal = self.rec >= 0
        zr[internal] = zf[self.rec[internal]]
        ex = self.exits
        zr[ex] = zg[np.nonzero(ex)[0] % NCOLS]
        zr[~self.has_rec] = zf[~self.has_rec]
        return np.maximum((zf - zr) / self.dist, 0.0)


def contributing_area(z, zg):
    """D8 upslope contributing area (m^2), for the 'flow' map layer."""
    N = z.size
    net = Network(z, zg, np.zeros(N), np.zeros(N))
    return net.solve_water(np.full(N, DX * DX)).reshape(z.shape)


# ----------------------------------------------------------------------------
# Process 2: overland-flow erosion, transport and deposition (one storm piece)
# ----------------------------------------------------------------------------
def overland_flow_event(z, zg, net, runoff_m, capfac, a, frac):
    """Route one storm's runoff (m depth per cell) and move sediment.
    frac = fraction of the storm computed in this piece (1/k for dt-scale).
    Water per unit width W (m^2) -> capacity Qc = dx*KC*capfac*W^m*S^n*frac.
    Sediment flux relaxes toward capacity: Qs_out = (Qs_in + a Qc)/(1 + a),
    a = dx/L. Change in a cell = (Qs_in - Qs_out)/dx^2 (pits keep all inflow).
    Returns (z_new, exported m^3, gross eroded m^3)."""
    zf = z.ravel()
    y = net.solve_water(runoff_m * DX * DX)            # m^3 storm water
    W = y / DX                                         # m^2 per unit width
    S = net.slope(zf, zg)
    qc = DX * KC * capfac * W ** M_EXP * S ** N_EXP * frac   # m^3
    qc[~net.has_rec] = 0.0
    qs = net.solve_sed(a * qc)
    qs[~net.has_rec] = 0.0                             # pits: nothing leaves
    dV = net.inflow(qs) - qs
    exported = qs[net.exits].sum()
    znew = (zf + dV / (DX * DX)).reshape(z.shape)
    return znew, exported, -dV[dV < 0].sum()


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------
def simulate(z0, veg, storm_t, storm_d, rain_scale=1.0, dt_scale=1.0,
             n_snap=11):
    z = z0.copy()
    v = veg.ravel()
    # vegetation effects
    D = D_BARE * (1.0 + D_VEG_GAIN * veg)
    infil = (I_BARE_MM + (I_VEG_MM - I_BARE_MM) * v) / 1000.0   # m
    beta = RUNON_LOSS * v
    capfac = 1.0 - VEG_CAP_REDUCTION * v
    L = L_BARE * (1.0 - VEG_L_REDUCTION * v)
    a = DX / L
    # fixed base-level channel just beyond the bottom edge
    s_edge = np.maximum(z0[-2, :] - z0[-1, :], 0.02 * DX)
    zg = z0[-1, :] - s_edge

    dt = DT_BASE * dt_scale
    nsteps = int(round(YEARS / dt))
    k = max(1, int(round(1.0 / dt_scale))) if dt_scale < 1 else 1
    depths = storm_d * rain_scale / 1000.0
    imin = infil.min()

    snap_years = np.linspace(0, YEARS, n_snap)
    snaps = [z0.copy()]
    next_snap = 1
    exported = 0.0
    gross = 0.0
    nflow = 0
    for i in range(nsteps):
        t0, t1 = i * dt, (i + 1) * dt
        z, e, g = creep_step(z, D, zg, dt)
        exported += e
        gross += g
        lo, hi = np.searchsorted(storm_t, [t0, t1])
        if i == nsteps - 1:
            hi = storm_t.size
        net = None
        for j in range(lo, hi):
            P = depths[j]
            if P <= imin:
                continue
            runoff = np.maximum(P - infil, 0.0)
            for _ in range(k):
                if net is None:
                    net = Network(z, zg, beta, a)
                z, e, g = overland_flow_event(z, zg, net, runoff, capfac, a,
                                              1.0 / k)
                exported += e
                gross += g
                nflow += 1
        while next_snap < n_snap and t1 >= snap_years[next_snap] - 1e-9:
            snaps.append(z.copy())
            next_snap += 1
    return dict(z=z, exported=exported, gross=gross, nsteps=nsteps, dt=dt,
                snaps=snaps, snap_years=snap_years, zg=zg, nflow=nflow)


# ----------------------------------------------------------------------------
# Visualisation
# ----------------------------------------------------------------------------
def _cmaps():
    from matplotlib.colors import LinearSegmentedColormap
    terrain = LinearSegmentedColormap.from_list(
        "dryland", ["#efe3c2", "#e2c58f", "#cf9f62", "#b07444", "#8a5636",
                    "#6b4a3a"])
    change = LinearSegmentedColormap.from_list(
        "lossgain", ["#7a2e0b", "#c8662a", "#f0c08a", "#f7f4ee", "#9fd3c7",
                     "#2f8f83", "#0b4f4a"])
    vegc = LinearSegmentedColormap.from_list(
        "veg", ["#f3ead2", "#c9cf8f", "#7fa457", "#3f6e2f", "#1f4420"])
    flow = LinearSegmentedColormap.from_list(
        "flow", ["#f6efe0", "#bcd7e6", "#5d9ec9", "#1f5f99", "#0b2a5c"])
    return terrain, change, vegc, flow


def layer_rgbs(z, z0, veg, area, zlim, clim, alim):
    """RGB arrays (0..1) for each map layer."""
    from matplotlib.colors import LightSource, Normalize
    terrain, change, vegc, flow = _cmaps()
    ls = LightSource(azdeg=315, altdeg=40)
    hs = ls.hillshade(z, vert_exag=SHADE_VE, dx=DX, dy=DX)
    out = {}
    out["terrain"] = ls.shade(z, cmap=terrain, norm=Normalize(*zlim),
                              vert_exag=SHADE_VE, dx=DX, dy=DX,
                              blend_mode="soft")[..., :3]
    shade = (0.55 + 0.45 * hs)[..., None]
    d = z - z0
    out["change"] = np.clip(change(Normalize(-clim, clim)(d))[..., :3] * shade, 0, 1)
    out["vegetation"] = np.clip(vegc(veg)[..., :3] * shade, 0, 1)
    out["flow"] = np.clip(flow(Normalize(*alim)(np.log10(area)))[..., :3] * shade, 0, 1)
    return out


def png_b64(rgb):
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    plt.imsave(buf, rgb, format="png", metadata={"Software": None})
    return base64.b64encode(buf.getvalue()).decode("ascii")


def colorbar_b64(cmap, vmin, vmax, label, log=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    fig, ax = plt.subplots(figsize=(4.2, 0.75), dpi=100)
    fig.subplots_adjust(left=0.05, right=0.95, bottom=0.55, top=0.9)
    sm = matplotlib.cm.ScalarMappable(norm=Normalize(vmin, vmax), cmap=cmap)
    cb = fig.colorbar(sm, cax=ax, orientation="horizontal")
    if log:
        ticks = np.arange(np.ceil(vmin), np.floor(vmax) + 1)
        cb.set_ticks(ticks)
        cb.set_ticklabels([f"{10**t:g}" for t in ticks])
    cb.set_label(label, fontsize=8)
    ax.tick_params(labelsize=7)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", metadata={"Software": None})
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_static_map(path, z0, z, veg, area, tel, clim):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    terrain, change, vegc, flow = _cmaps()
    zlim = (min(z0.min(), z.min()), max(z0.max(), z.max()))
    la = np.log10(area)
    alim = (np.log10(DX * DX), la.max())
    rgbs = layer_rgbs(z, z0, veg, area, zlim, clim, alim)
    ext = [0, NCOLS * DX, NROWS * DX, 0]
    fig, axs = plt.subplots(1, 4, figsize=(17, 6.4))
    spec = [("terrain", "Final terrain (relief shading, VE %gx)" % SHADE_VE,
             terrain, zlim, "Elevation (m)"),
            ("change", "Elevation change after %g yr" % YEARS, change,
             (-clim * 1000, clim * 1000), "Loss (-) / gain (+) (mm)"),
            ("vegetation", "Vegetation cover", vegc, (0, 1),
             "Fractional cover (0-1)"),
            ("flow", "Flow: upslope contributing area", flow, alim,
             "log10 area (m²)")]
    for ax, (key, title, cmap, lim, lab) in zip(axs, spec):
        ax.imshow(rgbs[key], extent=ext, interpolation="bilinear")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Distance across slope (m)")
        sm = matplotlib.cm.ScalarMappable(norm=Normalize(*lim), cmap=cmap)
        cb = fig.colorbar(sm, ax=ax, orientation="horizontal", pad=0.09,
                          fraction=0.05)
        cb.set_label(lab, fontsize=8)
        # scale bar 50 m
        x0, y0 = 10, NROWS * DX - 12
        ax.plot([x0, x0 + 50], [y0, y0], color="k", lw=4)
        ax.plot([x0, x0 + 50], [y0, y0], color="w", lw=2)
        ax.text(x0 + 25, y0 - 5, "50 m", ha="center", fontsize=8,
                bbox=dict(fc="w", ec="none", alpha=0.7, pad=1))
        ax.annotate("downslope", xy=(NCOLS * DX - 14, NROWS * DX - 8),
                    xytext=(NCOLS * DX - 14, NROWS * DX - 48), ha="center",
                    va="bottom", fontsize=7, arrowprops=dict(arrowstyle="->"),
                    bbox=dict(fc="w", ec="none", alpha=0.7, pad=1))
    axs[0].set_ylabel("Distance from crest (m)")
    fig.suptitle("Simulated dryland hillslope, seed %d: %g years, %d storms, "
                 "%.0f mm/yr rain. Shading: sun from NW, vertical exaggeration "
                 "%gx." % (tel["seed"], YEARS, tel["storm_count"],
                           tel["mean_annual_rain_mm"], SHADE_VE), fontsize=11)
    fig.savefig(path, dpi=110, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Dryland hillslope: erosion and deposition explorer</title>
<style>
body{font-family:Georgia,serif;background:#f7f1e3;color:#3b2f25;margin:0;padding:18px;max-width:1150px}
h1{font-size:1.5em;margin:0 0 4px}
.wrap{display:flex;gap:22px;flex-wrap:wrap}
.panel{background:#fffaf0;border:1px solid #d9c7a3;border-radius:8px;padding:12px}
#mapbox{position:relative;width:__W__px;height:__H__px;border:1px solid #8a5636}
#mapimg{width:__W__px;height:__H__px;display:block;image-rendering:auto}
#scalebar{position:absolute;left:12px;bottom:12px;background:rgba(255,255,255,.75);padding:3px 6px;font-size:12px}
#scalebar div{height:6px;background:repeating-linear-gradient(90deg,#000 0 50%,#fff 50% 100%);background-size:50% 100%;border:1px solid #000;width:__SB__px}
#arrow{position:absolute;right:10px;top:10px;background:rgba(255,255,255,.75);padding:3px 6px;font-size:12px;text-align:center}
.controls label{margin-right:10px;cursor:pointer}
#readout{font-family:monospace;font-size:13px;min-height:2.6em}
.note{font-size:.92em;line-height:1.45}
button{font-family:inherit}
h2{font-size:1.1em;margin:14px 0 4px}
</style></head><body>
<h1>Dryland hillslope: where does the soil go?</h1>
<p class="note">A simulated __WM__ m &times; __HM__ m hillslope (crest at the top, foot of the slope at the bottom) over
__YEARS__ years of random desert storms. Move the time slider and switch layers to see the slope change.</p>
<div class="wrap">
<div class="panel">
 <div id="mapbox"><img id="mapimg" alt="map">
  <div id="scalebar"><div></div>__SBM__ m</div>
  <div id="arrow">&darr;<br>downslope</div></div>
 <div id="legend" style="margin-top:6px"><img id="legimg" alt="legend" style="width:__W__px"></div>
 <div id="legtext" class="note" style="width:__W__px"></div>
 <div id="readout">Point at the map to read values.</div>
</div>
<div class="panel controls" style="flex:1;min-width:330px">
 <h2>Time</h2>
 <input type="range" id="time" data-bench="time" min="0" max="__NF1__" value="__NF1__" step="1" style="width:260px">
 <button id="play" data-bench="play">&#9654; Play</button>
 <div>Year <b id="yearlab"></b> of __YEARS__ (<span id="phase"></span>)</div>
 <h2>Layer</h2>
 <label><input type="radio" name="layer" value="terrain" data-bench="layer-terrain" checked> Terrain</label>
 <label><input type="radio" name="layer" value="change" data-bench="layer-change"> Change</label>
 <label><input type="radio" name="layer" value="vegetation" data-bench="layer-vegetation"> Vegetation</label>
 <label><input type="radio" name="layer" value="flow" data-bench="layer-flow"> Flow</label>
 <h2>What if there were no plants? (Change layer, final year)</h2>
 <label><input type="checkbox" id="bare" data-bench="scenario-bare"> Show the same storms on bare ground</label>
 <div class="note" id="bareinfo"></div>
 <h2>What the model assumes</h2>
 <ul class="note">
 <li>Rain falls as separate storms at random times (about __NSY__ a year, __RAIN__ mm a year in total). Small storms soak in; only the part of a storm that is bigger than what the soil can absorb runs off (__IB__ mm on bare crusted soil, __IV__ mm under plants).</li>
 <li>Runoff flows straight downhill from cell to cell (steepest descent). The more ground drains through a cell and the steeper it is, the more sediment the water can carry.</li>
 <li>Where water can carry more than it holds, it picks up soil (erosion). Where it can carry less (gentler ground, plant patches), it drops soil (deposition). Soil is never deleted: it moves, or leaves across the bottom edge, where it is counted.</li>
 <li>Plants: soak up more rain and some of the runoff arriving from above, protect the soil (water carries 90% less across full cover), and trap sediment. Burrowing and roots make soil creep a little faster under plants.</li>
 <li>Soil creep slowly smooths the surface everywhere, even without rain (rate __D__ m&sup2;/yr on bare ground).</li>
 <li>There is always soil to erode (no bedrock), the top and side edges are closed, the bottom edge drains to a channel at fixed height. Vegetation does not grow or die during the run.</li>
 </ul>
 <h2>Landforms to look for</h2>
 <ul class="note">
 <li><b>Rills and gullies</b>: brown lines of loss in the Change layer, where runoff gathers in the two shallow hollows (blue lines in the Flow layer).</li>
 <li><b>Footslope apron / small fans</b>: teal (gain) near the bottom, where the slope flattens and the water drops its load.</li>
 <li><b>Sediment trapped by plant patches</b>: teal on the uphill edge of green bands, brown in the bare gaps between them.</li>
 <li><b>Rounded crest</b>: creep makes the top of the slope convex.</li>
 </ul>
 <p class="note">Shading: light from the north-west, heights exaggerated __VE__&times; to make relief visible. Colours on the Change layer are centred on zero: brown = lowered, white = no change, teal = raised.</p>
</div></div>
<script>
const D = __DATA__;
const img = document.getElementById('mapimg'), slider = document.getElementById('time');
const bare = document.getElementById('bare');
let layer = 'terrain';
function zAt(f, i){ return D.zmm[f][i]/1000; }
function draw(){
  const f = +slider.value;
  document.getElementById('yearlab').textContent = D.years[f];
  document.getElementById('phase').textContent = f==0 ? 'before' : (f==D.years.length-1 ? 'after' : 'during');
  let src, leg = D.legend[layer], txt = D.legtext[layer];
  if (layer==='change' && bare.checked){ src = D.bare_img; txt = D.legtext.bare; }
  else if (layer==='vegetation'){ src = D.img.vegetation[0]; }
  else { src = D.img[layer][f]; }
  img.src = 'data:image/png;base64,' + src;
  document.getElementById('legimg').src = 'data:image/png;base64,' + leg;
  document.getElementById('legtext').textContent = txt;
}
slider.addEventListener('input', draw);
bare.addEventListener('change', draw);
document.querySelectorAll('input[name=layer]').forEach(function(r){
  r.addEventListener('change', function(){ layer = r.value; draw(); });
});
let timer = null;
document.getElementById('play').addEventListener('click', function(){
  if (timer){ clearInterval(timer); timer = null; this.innerHTML = '&#9654; Play'; return; }
  this.innerHTML = '&#10074;&#10074; Pause';
  if (+slider.value >= D.years.length-1) slider.value = 0;
  const b = this;
  timer = setInterval(function(){
    if (+slider.value >= D.years.length-1){ clearInterval(timer); timer=null; b.innerHTML='&#9654; Play'; return; }
    slider.value = +slider.value + 1; draw();
  }, 600);
});
img.addEventListener('mousemove', function(ev){
  const r = img.getBoundingClientRect();
  const c = Math.floor((ev.clientX - r.left) / r.width * D.ncols);
  const w = Math.floor((ev.clientY - r.top) / r.height * D.nrows);
  if (c<0||w<0||c>=D.ncols||w>=D.nrows) return;
  const i = w*D.ncols + c, f = +slider.value;
  const z = zAt(f,i), dz = (D.zmm[f][i]-D.zmm[0][i]);
  let s = 'x ' + (c*D.dx) + ' m, ' + (w*D.dx) + ' m from crest | elevation ' + z.toFixed(2) + ' m | change ' + (dz>=0?'+':'') + dz + ' mm | plant cover ' + D.veg[i].toFixed(2);
  if (bare.checked && layer==='change') s += ' | bare-ground change ' + (D.bare_dmm[i]>=0?'+':'') + D.bare_dmm[i] + ' mm';
  document.getElementById('readout').textContent = s;
});
document.getElementById('bareinfo').textContent = D.bareinfo;
draw();
</script>
</body></html>
"""


def make_html(path, res, z0, veg, tel, clim, bare_res):
    terrain, change, vegc, flow = _cmaps()
    snaps = res["snaps"]
    zlim = (min(s.min() for s in snaps), max(s.max() for s in snaps))
    areas = [contributing_area(s, res["zg"]) for s in snaps]
    alim = (np.log10(DX * DX), max(np.log10(a).max() for a in areas))
    imgs = {"terrain": [], "change": [], "vegetation": [], "flow": []}
    for s, a in zip(snaps, areas):
        rg = layer_rgbs(s, z0, veg, a, zlim, clim, alim)
        for key in ("terrain", "change", "flow"):
            imgs[key].append(png_b64(rg[key]))
    imgs["vegetation"].append(png_b64(rg["vegetation"]))
    bare_img, bare_d, bareinfo = "", [], "Bare-ground run not available."
    if bare_res is not None:
        rgb = layer_rgbs(bare_res["z"], z0, veg, areas[-1], zlim, clim, alim)
        bare_img = png_b64(rgb["change"])
        bare_d = np.round((bare_res["z"] - z0) * 1000).astype(int).ravel().tolist()
        def stats(zz, exp):
            d = zz - z0
            return (-d[d < 0].sum() * DX * DX, exp)
        e1, x1 = stats(res["z"], res["exported"])
        e2, x2 = stats(bare_res["z"], bare_res["exported"])
        bareinfo = ("Net soil lost from eroding cells: %.0f m³ with plants vs %.0f m³ "
                    "on bare ground; sediment leaving the bottom edge: %.0f m³ vs %.0f m³. "
                    "(Same storms, same starting surface, same colour scale.)"
                    % (e1, e2, x1, x2))
    cl = clim * 1000
    legend = {
        "terrain": colorbar_b64(terrain, zlim[0], zlim[1], "Elevation (m) - shaded relief, vertical exaggeration %gx" % SHADE_VE),
        "change": colorbar_b64(change, -cl, cl, "Elevation change since year 0 (mm): brown = loss, teal = gain"),
        "vegetation": colorbar_b64(vegc, 0, 1, "Vegetation cover (fraction of ground, 0-1)"),
        "flow": colorbar_b64(flow, alim[0], alim[1], "Upslope contributing area (m², log scale)", log=True),
    }
    legtext = {
        "terrain": "Height of the ground. Shading uses light from the north-west with heights exaggerated %gx." % SHADE_VE,
        "change": "Lowering (erosion) and raising (deposition) since the start, centred on zero; values beyond ±%.0f mm are shown at the darkest colour." % cl,
        "vegetation": "Shrub and grass patches (fixed through the run). Plants soak up runoff, protect the soil and trap sediment.",
        "flow": "How much ground drains through each cell. Blue lines are where runoff gathers into rills and gullies.",
        "bare": "Final change if the same storms fell on the same slope with no plants (same colour scale).",
    }
    data = dict(years=[int(round(y)) for y in res["snap_years"]],
                img=imgs, legend=legend, legtext=legtext, bare_img=bare_img,
                bare_dmm=bare_d, bareinfo=bareinfo,
                zmm=[np.round(s * 1000).astype(int).ravel().tolist() for s in snaps],
                veg=np.round(veg, 2).ravel().tolist(), nrows=NROWS, ncols=NCOLS,
                dx=DX)
    W = 400
    H = int(round(W * NROWS / NCOLS))
    sbm = 50
    rep = {"__W__": str(W), "__H__": str(H), "__SB__": str(int(round(sbm / (NCOLS * DX) * W))),
           "__SBM__": str(sbm), "__WM__": "%g" % (NCOLS * DX), "__HM__": "%g" % (NROWS * DX),
           "__YEARS__": "%g" % YEARS, "__NF1__": str(len(snaps) - 1),
           "__NSY__": "%.0f" % (tel["storm_count"] / YEARS), "__RAIN__": "%.0f" % tel["mean_annual_rain_mm"],
           "__IB__": "%g" % I_BARE_MM, "__IV__": "%g" % I_VEG_MM, "__D__": "%g" % D_BARE,
           "__VE__": "%g" % SHADE_VE}
    html = HTML_TEMPLATE
    for k_, v_ in rep.items():
        html = html.replace(k_, v_)
    html = html.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ----------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--z0", default=None)
    p.add_argument("--rain-scale", type=float, default=1.0)
    p.add_argument("--veg-scale", type=float, default=1.0)
    p.add_argument("--dt-scale", type=float, default=1.0)
    p.add_argument("--no-map", action="store_true")
    args = p.parse_args(argv)
    if args.dt_scale <= 0:
        p.error("--dt-scale must be > 0")
    t_start = time.time()
    os.makedirs(args.out, exist_ok=True)

    rng_veg, rng_storm, rng_rough = rng_streams(args.seed)
    veg0 = make_vegetation(rng_veg)
    storm_t, storm_d = make_storms(rng_storm)
    if args.z0:
        z0 = np.load(args.z0).astype(np.float64)
        if z0.shape != (NROWS, NCOLS):
            sys.exit("--z0 must have shape %s" % ((NROWS, NCOLS),))
    else:
        z0 = default_surface(rng_rough)
    veg = np.clip(veg0 * max(args.veg_scale, 0.0), 0.0, 1.0)

    res = simulate(z0, veg, storm_t, storm_d, args.rain_scale, args.dt_scale)
    z = res["z"]

    dV = (z - z0).sum() * DX * DX
    err = dV + res["exported"]
    tel = {
        "seed": args.seed,
        "grid_shape": [NROWS, NCOLS],
        "cell_size_m": DX,
        "years_simulated": YEARS,
        "timesteps": int(res["nsteps"]),
        "dt_years": float(res["dt"]),
        "storm_count": int(storm_t.size),
        "mean_annual_rain_mm": float(storm_d.sum() / YEARS),
        "creep_diffusivity_m2_per_yr": D_BARE,
        "open_boundaries": OPEN_BOUNDARIES,
        "sediment_exported_m3": float(res["exported"]),
        "uplift_or_baselevel_m3": 0.0,
        "mass_balance_error_pct": float(100.0 * abs(err) / max(res["gross"], 1e-12)),
    }
    np.save(os.path.join(args.out, "z_initial.npy"), z0)
    np.save(os.path.join(args.out, "z_final.npy"), z)
    np.save(os.path.join(args.out, "vegetation.npy"), veg)
    with open(os.path.join(args.out, "storms.csv"), "w") as fh:
        fh.write("year,depth_mm\n")
        for t, d in zip(storm_t, storm_d):
            fh.write("%.6f,%.4f\n" % (t, d))
    with open(os.path.join(args.out, "telemetry.json"), "w") as fh:
        json.dump(tel, fh, indent=2)

    if not args.no_map:
        d = z - z0
        clim = max(np.percentile(np.abs(d), 99), 1e-4)
        make_static_map(os.path.join(args.out, "map.png"), z0, z, veg,
                        contributing_area(z, res["zg"]), tel, clim)
        bare_res = None
        if args.veg_scale != 0:
            bare_res = simulate(z0, np.zeros_like(veg), storm_t, storm_d,
                                args.rain_scale, args.dt_scale, n_snap=2)
        make_html(os.path.join(args.out, "map.html"), res, z0, veg, tel, clim,
                  bare_res)
    print(json.dumps(tel, indent=2))
    print("runtime_s: %.1f  (overland-flow events computed: %d)"
          % (time.time() - t_start, res["nflow"]), file=sys.stderr)


if __name__ == "__main__":
    main()
