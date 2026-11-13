#!/usr/bin/env python3
"""Dryland hillslope erosion/deposition teaching simulation.

    python3 sim.py --seed 42 --out OUTDIR

Writes z_initial.npy, z_final.npy, telemetry.json, map.png, map.html to OUTDIR.
Everything random (roughness, vegetation, storms) derives from --seed.
"""
import argparse
import base64
import heapq
import json
import os
import time

import numpy as np
from scipy import ndimage
from scipy.sparse import csc_matrix, identity
from scipy.sparse.linalg import splu

# ----------------------------------------------------------------- parameters
N = 100                 # grid is N x N cells
DX = 6.0                # cell size, m  -> 600 m x 600 m hillslope
AREA = DX * DX
RELIEF = 30.0           # m from divide (row 0) to base level (last row)
YEARS = 5000.0
DT = 20.0              # yr per step (each step holds ~DT*LAM random storms)
NSTEPS = int(round(YEARS / DT))
N_SNAP = 5              # time snapshots stored for the interactive map

D_CREEP = 0.008         # m2/yr, linear soil creep (semi-arid range ~1e-3..1e-2)
LAM = 20.0              # storms per year that matter (rain-days)
STORM_MEAN = 12.0       # mm, mean storm depth (gamma distributed)
STORM_SHAPE = 0.8       # <1: heavy tail, many small and few big storms
INF_BARE = 6.0          # mm, infiltration capacity of crusted bare soil
INF_VEG = 14.0          # mm extra infiltration at full vegetation cover
VEG_MAX = 0.9           # biomass index inside a patch (0..1)
VEG_ERODE = 3.5         # detachment multiplier exp(-VEG_ERODE * v)
VEG_TRAP = 1.5          # transport-capacity multiplier exp(-VEG_TRAP * v)
M_D, KD = 1.2, 2.7e-4   # detachment depth (m) = KD*g(v)*sum(w q^M_D S)
M_T, N_T, KT = 1.5, 1.2, 1.0e-4  # capacity (m3)= KT*DX*sum(w q^M_T S^N_T)
DEP_FRAC = 0.4          # fraction of excess load that settles in one cell
# storm-size classes (cumulative fraction edges) used to represent each step
CLASS_EDGES = [0, .25, .5, .65, .75, .82, .88, .92, .95, .97, .985, .995, 1.0]
EPS_FILL = 1e-4

STORMINESS = [0.7, 1.0, 1.4]      # multiplier on mean storm depth
STORM_LABELS = ["calmer (-30%)", "baseline", "stormier (+40%)"]
COVER = [0.15, 0.35, 0.60]        # fraction of ground covered by vegetation
COVER_LABELS = ["sparse (15%)", "baseline (35%)", "dense (60%)"]
BASE_S, BASE_V = 1, 1

OFFS = [(-1, -1, 2 ** .5), (-1, 0, 1.0), (-1, 1, 2 ** .5), (0, -1, 1.0),
        (0, 1, 1.0), (1, -1, 2 ** .5), (1, 0, 1.0), (1, 1, 2 ** .5)]
RR, CC = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
NBRS = [[(r + dr) * N + c + dc for dr, dc, _ in OFFS
         if 0 <= r + dr < N and 0 <= c + dc < N] for r in range(N) for c in range(N)]


# ---------------------------------------------------------------- initial data
def make_initial(ss):
    rng = np.random.default_rng(ss)
    s = np.linspace(0, 1, N)[:, None] * np.ones((1, N))
    z = RELIEF * (1 - s) ** 1.6                       # convex divide, concave foot
    swale = np.sin(2 * np.pi * (CC / N) * 3.0 + 1.3 * np.sin(2 * np.pi * s)) \
        * 0.7 * np.sin(np.pi * s) ** 0.5
    z += swale                                        # shallow hollows to focus flow
    rough = ndimage.gaussian_filter(rng.standard_normal((N, N)), 1.0)
    rough /= rough.std()
    broad = ndimage.gaussian_filter(rng.standard_normal((N, N)), 6.0)
    broad /= broad.std()
    z += 0.07 * rough + 0.35 * broad
    z[-1, :] = 0.0                                    # base level (open boundary)
    return z


def make_veg_field(ss):
    rng = np.random.default_rng(ss)
    f = ndimage.gaussian_filter(rng.standard_normal((N, N)), (1.5, 7.0),
                                mode="reflect")        # bands along the contour
    return (f - f.mean()) / f.std()


def veg_cover(field, frac):
    thr = np.quantile(field, 1 - frac)
    return VEG_MAX / (1 + np.exp(-(field - thr) / 0.22))


# ------------------------------------------------------------------ hydrology
def fill_pits(z):
    """Iteratively raise pits (cells with no lower neighbour) so all drain."""
    # priority-flood (Barnes et al.) with a tiny epsilon so every cell drains
    zl = z.ravel().tolist()
    zf = list(zl)
    closed = [False] * (N * N)
    heap = []
    for c in range((N - 1) * N, N * N):
        closed[c] = True
        heap.append((zl[c], c))
    heapq.heapify(heap)
    pop, push = heapq.heappop, heapq.heappush
    nbrs = NBRS
    while heap:
        zc, c = pop(heap)
        lim = zc + EPS_FILL
        for n in nbrs[c]:
            if not closed[n]:
                closed[n] = True
                zn = zl[n]
                if zn < lim:
                    zn = lim
                zf[n] = zn
                push(heap, (zn, n))
    return np.array(zf).reshape(N, N)


def receivers(zf):
    pad = np.full((N + 2, N + 2), np.inf)
    pad[1:-1, 1:-1] = zf
    best = np.zeros((N, N))
    rec = np.full((N, N), -1, dtype=np.int64)
    for dr, dc, d in OFFS:
        sl = (zf - pad[1 + dr:1 + dr + N, 1 + dc:1 + dc + N]) / d
        m = sl > best
        best = np.where(m, sl, best)
        rec = np.where(m, (RR + dr) * N + (CC + dc), rec)
    rec[-1, :] = -1
    return rec.ravel(), best.ravel()


def accumulate(rec, runoff_vol):
    """Route runoff volumes (n2 x K) downslope along D8 receivers."""
    idx = np.nonzero(rec >= 0)[0]
    R = csc_matrix((np.ones(idx.size), (rec[idx], idx)), shape=(N * N, N * N))
    lu = splu((identity(N * N, format="csc") - R).tocsc())
    return lu.solve(np.ascontiguousarray(runoff_vol))


def storm_classes(depths):
    d = np.sort(depths)
    n = d.size
    edges = (np.array(CLASS_EDGES) * n).round().astype(int)
    P, W = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b > a:
            P.append(d[a:b].mean())
            W.append(b - a)
    return np.array(P), np.array(W, dtype=float)


# ------------------------------------------------------------------ simulation
def simulate(z0, vfield, storm_ss, storminess, cover):
    v = veg_cover(vfield, cover).ravel()
    infil = INF_BARE + INF_VEG * v                       # mm
    g_det = np.exp(-VEG_ERODE * v)
    g_trap = np.exp(-VEG_TRAP * v)
    rng = np.random.default_rng(storm_ss)
    z = z0.copy()
    zflat0 = z0.ravel().copy()
    snaps = {}
    snap_at = {int(round(k * NSTEPS / N_SNAP)): k for k in range(1, N_SNAP + 1)}
    exp_flux = exp_creep = gross_ero = gross_dep = 0.0
    rain_total = 0.0
    flow_last = None
    for step in range(1, NSTEPS + 1):
        # --- random storms for this step
        n_storm = rng.poisson(LAM * DT)
        depth = rng.gamma(STORM_SHAPE, STORM_MEAN * storminess / STORM_SHAPE, n_storm)
        rain_total += depth.sum()
        P, W = storm_classes(depth)
        # --- flow routing over the (pit-filled) surface
        zf = fill_pits(z)
        rec, S = receivers(zf)
        h = np.maximum(P[None, :] - infil[:, None], 0.0) / 1000.0     # m runoff
        Q = accumulate(rec, h * AREA)                                  # m3 / storm
        q = Q / DX                                                     # m2
        Dsum = (W * q ** M_D).sum(axis=1)
        Tsum = (W * q ** M_T).sum(axis=1)
        Dp = KD * g_det * Dsum * S * AREA                              # m3 potential
        Tc = KT * DX * g_trap * Tsum * S ** N_T                        # m3 capacity
        zr = z.ravel()
        zfr = zf.ravel()
        zrec = np.where(rec >= 0, zr[np.maximum(rec, 0)], zr)
        drop = np.maximum(zr - zrec, 0.0)
        cap_ero = 0.5 * drop * AREA
        cap_dep = (np.maximum(zfr - zr, 0.0) + 0.3 * drop) * AREA
        order = np.argsort(-zfr, kind="stable").tolist()
        rec_l, Dp_l, Tc_l = rec.tolist(), Dp.tolist(), Tc.tolist()
        ce_l, cd_l = cap_ero.tolist(), cap_dep.tolist()
        qs = [0.0] * (N * N)
        dv = [0.0] * (N * N)
        out = 0.0
        for c in order:
            r = rec_l[c]
            qin = qs[c]
            if r < 0:
                out += qin
                continue
            tc = Tc_l[c]
            if qin > tc:
                dep = (qin - tc) * DEP_FRAC
                if dep > cd_l[c]:
                    dep = cd_l[c]
                dv[c] += dep
                gross_dep += dep
                qs[r] += qin - dep
            else:
                er = tc - qin
                if Dp_l[c] < er:
                    er = Dp_l[c]
                if ce_l[c] < er:
                    er = ce_l[c]
                dv[c] -= er
                gross_ero += er
                qs[r] += qin + er
        exp_flux += out
        zr = zr + np.array(dv) / AREA
        z = zr.reshape(N, N)
        # --- hillslope creep (explicit linear diffusion, base-level row fixed)
        pad = np.pad(z, 1, mode="edge")
        lap = (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]
               - 4 * z) / DX ** 2
        flux_out = D_CREEP * DT * (z[-2, :] - z[-1, :]).sum() * 1.0   # m3 to boundary row
        znew = z + D_CREEP * DT * lap
        znew[-1, :] = z[-1, :]
        exp_creep += flux_out
        z = znew
        if step in snap_at:
            snaps[snap_at[step]] = z.copy()
        if step == NSTEPS:
            flow_last = (W[None, :] * Q).sum(axis=1).reshape(N, N) / DT   # m3/yr
    vol_change = (z - z0).sum() * AREA
    exported = exp_flux + exp_creep
    err = abs(vol_change + exported) / max(gross_ero, 1e-12) * 100.0
    return dict(z=z, snaps=snaps, veg=v.reshape(N, N), flow=flow_last,
                exported=exported, gross_ero=gross_ero, gross_dep=gross_dep,
                err=err, vol_change=vol_change, rain_mm_per_yr=rain_total / YEARS)


# ------------------------------------------------------------------ static map
def make_png(path, z0, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, LinearSegmentedColormap, TwoSlopeNorm

    terrain = LinearSegmentedColormap.from_list(
        "dryland", ["#e9dcb8", "#d9bf86", "#c4955a", "#a66a43", "#7a4a37", "#53372f"])
    change = LinearSegmentedColormap.from_list(
        "loss_gain", ["#8c2d04", "#d9622b", "#f6c9a4", "#f7f4ee", "#a9d3e3", "#3f8fb5", "#0b4f7a"])
    vegc = LinearSegmentedColormap.from_list("veg", ["#e9dcb8", "#b9b872", "#6b8e4e", "#2f5d3a"])
    flowc = LinearSegmentedColormap.from_list("flow", ["#f2f0ea", "#9ccae0", "#2f7fb0", "#0b3c6b"])
    z1 = res["z"]
    dz = z1 - z0
    lim = max(float(np.percentile(np.abs(dz), 99.5)), 1e-3)
    ls = LightSource(azdeg=315, altdeg=38)
    ext = [0, N * DX, N * DX, 0]
    fig, axs = plt.subplots(2, 2, figsize=(12.5, 12), dpi=110)
    fig.suptitle("Synthetic dryland hillslope: %d yr of storms, creep, overland-flow erosion "
                 "and patchy vegetation" % YEARS, fontsize=13, fontweight="bold")

    def panel(ax, rgb, title, cmap=None, norm=None, label=""):
        ax.imshow(rgb, extent=ext, interpolation="nearest")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_xlabel("across slope (m)")
        ax.set_ylabel("downslope distance (m)  (divide at top)")
        if cmap is not None:
            sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
            cb = fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.03)
            cb.set_label(label)

    zn = plt.Normalize(z0.min(), z0.max())
    shade = ls.shade(z1, cmap=terrain, norm=zn, blend_mode="soft", vert_exag=3, dx=DX, dy=DX)
    panel(axs[0, 0], shade, "Terrain after %d yr (relief-shaded)" % YEARS, terrain, zn, "elevation (m)")
    axs[0, 0].contour(np.linspace(0, N * DX, N), np.linspace(0, N * DX, N), z1,
                      levels=np.arange(0, RELIEF + 1, 5), colors="#3b2a22", linewidths=0.4, alpha=0.6)
    cn = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
    rgb = change(cn(np.clip(dz, -lim, lim)))
    rgb = ls.shade_rgb(rgb[..., :3], z1, fraction=0.7, blend_mode="soft", vert_exag=3, dx=DX, dy=DX)
    panel(axs[0, 1], rgb, "Elevation change: loss (orange-brown) / gain (blue)", change, cn,
          "change in elevation (m), centred on 0")
    vn = plt.Normalize(0, VEG_MAX)
    rgb = ls.shade_rgb(vegc(vn(res["veg"]))[..., :3], z1, fraction=0.6, blend_mode="soft",
                       vert_exag=3, dx=DX, dy=DX)
    panel(axs[1, 0], rgb, "Vegetation patches (cover %.0f%%)" % (100 * COVER[BASE_V]), vegc, vn,
          "vegetation index")
    lf = np.log10(np.maximum(res["flow"], 1e-3))
    fn = plt.Normalize(np.percentile(lf, 5), lf.max())
    base = ls.shade(z1, cmap=plt.cm.Greys_r, blend_mode="soft", vert_exag=3, dx=DX, dy=DX)
    a = np.clip(fn(lf), 0, 1)[..., None] ** 0.8
    rgb = base[..., :3] * 0.55 + 0.45
    rgb = rgb * (1 - a) + flowc(fn(lf))[..., :3] * a
    panel(axs[1, 1], rgb, "Flow paths: mean annual runoff through each cell", flowc, fn,
          "log10 runoff (m3 per year)")
    fig.text(0.5, 0.012, "Open boundary at the bottom edge (base level); other edges closed. "
             "Synthetic landscape for teaching, not a calibrated site model.",
             ha="center", fontsize=9, color="#555")
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    fig.savefig(path)
    plt.close(fig)


# --------------------------------------------------------------- interactive map
def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def make_html(path, z0, results, seed):
    base = results[(BASE_S, BASE_V)]
    dzmax = max(float(np.percentile(np.abs(r["z"] - z0), 99.5)) for r in results.values())
    lim = float(np.ceil(dzmax * 20) / 20)
    allflow = np.log10(np.maximum(base["flow"], 1e-3))
    flo, fhi = float(np.percentile(allflow, 5)), float(allflow.max())
    scen = []
    for si in range(len(STORMINESS)):
        row = []
        for vi in range(len(COVER)):
            r = results[(si, vi)]
            dz = np.stack([np.round((r["snaps"][k] - z0) * 1000) for k in range(1, N_SNAP + 1)])
            lf = np.log10(np.maximum(r["flow"], 1e-3))
            fq = np.clip((lf - flo) / (fhi - flo), 0, 1) * 255
            row.append(dict(dz=b64(dz.astype("<i2")), flow=b64(fq.round().astype(np.uint8)),
                            ero=round(r["gross_ero"]), exp=round(r["exported"]),
                            rain=round(r["rain_mm_per_yr"])))
        scen.append(row)
    veg = [b64((veg_cover(VF_GLOBAL, c) / VEG_MAX * 255).round().astype(np.uint8)) for c in COVER]
    data = dict(n=N, dx=DX, years=YEARS, nsnap=N_SNAP, seed=seed, lim=lim, flo=flo, fhi=fhi,
                zmin=float(z0.min()), zmax=float(z0.max()), z0=b64(z0.astype("<f4")),
                scen=scen, veg=veg, vegmax=VEG_MAX, storm_labels=STORM_LABELS,
                cover_labels=COVER_LABELS, bs=BASE_S, bv=BASE_V)
    with open(path, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__DATA__", json.dumps(data)))


VF_GLOBAL = None

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dryland hillslope: where does the soil go?</title>
<style>
:root{--ink:#2f2520;--sand:#f6f0e2;--rust:#a6431a;--blue:#1d6a96;--line:#d8cbb0}
*{box-sizing:border-box}
body{margin:0;background:var(--sand);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:16px 22px 6px}
h1{margin:0;font-size:22px} h2{font-size:16px;margin:18px 0 6px}
.sub{color:#6b5b4e;margin:2px 0 0}
main{display:flex;flex-wrap:wrap;gap:20px;padding:10px 22px 30px}
.left{flex:0 0 auto}.right{flex:1 1 340px;max-width:620px}
canvas#map{width:600px;height:600px;max-width:100%;border:1px solid var(--line);background:#fff;image-rendering:pixelated;display:block}
.ctl{display:flex;flex-wrap:wrap;gap:14px 22px;margin:8px 0;align-items:center}
.ctl label{font-weight:600;font-size:13px}
.seg{display:inline-flex;border:1px solid #b9a98b;border-radius:6px;overflow:hidden}
.seg button{border:0;background:#fffaf0;padding:6px 11px;font:inherit;font-size:13px;cursor:pointer;color:var(--ink)}
.seg button+button{border-left:1px solid #b9a98b}
.seg button.on{background:var(--ink);color:#fff}
.seg button:focus-visible,input:focus-visible{outline:2px solid var(--blue);outline-offset:1px}
input[type=range]{width:260px}
#legend{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:12.5px;min-height:46px}
#bar{width:260px;height:14px;border:1px solid #9a8a70}
#ticks{display:flex;justify-content:space-between;width:260px;font-size:11.5px;color:#4d3f35}
#readout{font-size:13px;min-height:20px;font-variant-numeric:tabular-nums}
.card{background:#fffaf0;border:1px solid var(--line);border-radius:8px;padding:4px 16px 10px}
ul{padding-left:20px;margin:4px 0} li{margin:3px 0}
.stat{font-size:13px;color:#4d3f35}
</style></head><body>
<header><h1>Where does the soil go? A simulated dryland hillslope</h1>
<p class="sub">Synthetic 600 m &times; 600 m slope, simulated for <span id="yrs"></span> years. Divide at the top, base level (open edge) at the bottom. Everything on this page was computed by <code>sim.py</code> from seed <span id="seed"></span>.</p></header>
<main>
<div class="left">
 <div class="ctl">
  <div><label>Layer&nbsp;</label><span class="seg" id="layers"></span></div>
 </div>
 <canvas id="map" width="600" height="600" aria-label="Hillslope map"></canvas>
 <div id="readout">Hover over the map to read a cell.</div>
 <div id="legend"><div><div id="bar"></div><div id="ticks"></div></div><div id="lgtext"></div></div>
 <div class="ctl">
  <div><label for="time">Time&nbsp;</label><input type="range" id="time" min="0" max="5" step="1" value="5">
   <span id="tlabel"></span> <span class="seg"><button id="play">&#9654; play</button></span></div>
 </div>
 <div class="ctl">
  <div><label>Storminess&nbsp;</label><span class="seg" id="storm"></span></div>
  <div><label>Vegetation cover&nbsp;</label><span class="seg" id="cover"></span></div>
 </div>
 <div class="stat" id="stat"></div>
</div>
<div class="right">
<div class="card">
<h2>How to use it</h2>
<ul>
<li><b>Layer</b>: <i>Terrain</i> is the shaded landscape; <i>Change</i> shows what was lost (orange-brown) or gained (blue) since the start, centred on zero; <i>Vegetation</i> shows the patches; <i>Flow</i> shows where runoff concentrates.</li>
<li><b>Time</b>: drag from year 0 (before) to the end (after), or press play. The change colour scale stays fixed so you can watch change build up.</li>
<li><b>Storminess</b> and <b>Vegetation cover</b> switch between 9 pre-computed runs with the same random landscape and the same random storm sequence, so differences come only from the setting you changed. (They are pre-computed, not calculated in your browser.)</li>
</ul>
<h2>What the model assumes</h2>
<ul>
<li><b>Soil creep</b>: soil slowly shuffles downhill at a rate proportional to the slope (diffusion), which rounds off hilltops and smooths small bumps.</li>
<li><b>Rain</b> comes as random storms, about 20 a year, mostly small with a few large ones. Water only runs off once rain exceeds what the soil can soak up, so big storms do most of the work.</li>
<li><b>Overland flow</b> is routed downhill over the surface, collecting water from everything upslope. Its power to pick up soil grows with both slope and the amount of water.</li>
<li><b>Sediment is carried, not deleted.</b> Flow picks up soil until it is carrying as much as it can for the local slope and water. Where slope or water drops, such as at the foot of the slope, the excess settles out.</li>
<li><b>Vegetation patches</b> (long bands across the slope) soak up more rain, shield the soil from erosion and slow sediment-laden flow, so they trap sediment.</li>
<li><b>Boundaries</b>: the bottom edge is a fixed base level that sediment can leave through; the other three edges are closed. Every cubic metre that leaves is counted.</li>
<li>Vegetation is held fixed in time, there is no tectonic uplift, and the slope is synthetic. It is a teaching model, not a forecast for a real place.</li>
</ul>
<h2>Landforms to look for</h2>
<ul>
<li><b>Rills and gullies</b>: narrow orange-brown lines on the Change layer that follow the bright paths on the Flow layer. Look for them on the steeper upper and middle slope where bare soil meets concentrated flow.</li>
<li><b>Sediment aprons / fans</b>: broad blue areas near the foot of the slope, where the slope flattens and flow loses power.</li>
<li><b>Vegetation bands as traps</b>: blue (gain) fringes on the uphill side of green bands, and orange-brown (loss) in the bare gaps between them.</li>
<li><b>Rounded divide</b>: gentle lowering near the top from creep.</li>
<li>Try <i>stormier</i> with <i>sparse</i> cover, then <i>calmer</i> with <i>dense</i> cover. Compare the export total under the map.</li>
</ul>
</div></div>
</main>
<script>
const D=__DATA__;
function dec(s,T){const b=atob(s),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return new T(u.buffer);}
const n=D.n,N2=n*n,z0=dec(D.z0,Float32Array);
const veg=D.veg.map(s=>dec(s,Uint8Array));
const scen=D.scen.map(r=>r.map(o=>({dz:dec(o.dz,Int16Array),flow:dec(o.flow,Uint8Array),ero:o.ero,exp:o.exp,rain:o.rain})));
document.getElementById('yrs').textContent=D.years;document.getElementById('seed').textContent=D.seed;
let st={layer:'terrain',t:D.nsnap,s:D.bs,v:D.bv};
const LAYERS=[['terrain','Terrain'],['change','Change'],['veg','Vegetation'],['flow','Flow']];
function seg(id,items,key,cb){const el=document.getElementById(id);items.forEach(([val,lab])=>{const b=document.createElement('button');b.textContent=lab;b.onclick=()=>{st[key]=val;refresh();cb&&cb()};b.dataset.v=val;el.appendChild(b)});}
seg('layers',LAYERS,'layer');
seg('storm',D.storm_labels.map((l,i)=>[i,l]),'s');
seg('cover',D.cover_labels.map((l,i)=>[i,l]),'v');
function lerp(stops,x){x=Math.min(1,Math.max(0,x));const k=x*(stops.length-1),i=Math.min(stops.length-2,Math.floor(k)),f=k-i,a=stops[i],b=stops[i+1];return[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f,a[2]+(b[2]-a[2])*f];}
function hex(h){return[1,3,5].map(i=>parseInt(h.substr(i,2),16));}
const TER=["#e9dcb8","#d9bf86","#c4955a","#a66a43","#7a4a37","#53372f"].map(hex);
const CHG=["#8c2d04","#d9622b","#f6c9a4","#f7f4ee","#a9d3e3","#3f8fb5","#0b4f7a"].map(hex);
const VEGC=["#e9dcb8","#b9b872","#6b8e4e","#2f5d3a"].map(hex);
const FLW=["#f2f0ea","#9ccae0","#2f7fb0","#0b3c6b"].map(hex);
const cv=document.getElementById('map'),ctx=cv.getContext('2d'),img=ctx.createImageData(n,n);
const off=document.createElement('canvas');off.width=n;off.height=n;const octx=off.getContext('2d');
let zcur=new Float32Array(N2),dzcur=new Float32Array(N2);
function current(){const o=scen[st.s][st.v];for(let i=0;i<N2;i++){const d=st.t===0?0:o.dz[(st.t-1)*N2+i]/1000;dzcur[i]=d;zcur[i]=z0[i]+d;}}
function shade(i,r,c){const ve=2.5,dx=D.dx;const g=(rr,cc)=>zcur[Math.min(n-1,Math.max(0,rr))*n+Math.min(n-1,Math.max(0,cc))];
 const dzdx=(g(r,c+1)-g(r,c-1))/(2*dx)*ve,dzdy=(g(r+1,c)-g(r-1,c))/(2*dx)*ve;
 const sl=Math.atan(Math.hypot(dzdx,dzdy)),asp=Math.atan2(dzdy,-dzdx),az=315*Math.PI/180,zen=(90-40)*Math.PI/180;
 const h=Math.cos(zen)*Math.cos(sl)+Math.sin(zen)*Math.sin(sl)*Math.cos(az-asp);return Math.max(0,Math.min(1,h));}
function draw(){current();const o=scen[st.s][st.v],vg=veg[st.v];const d=img.data;
 for(let r=0;r<n;r++)for(let c=0;c<n;c++){const i=r*n+c,sh=shade(i,r,c);let col,k;
  if(st.layer==='terrain'){col=lerp(TER,(zcur[i]-D.zmin)/(D.zmax-D.zmin));k=0.45+0.8*sh;}
  else if(st.layer==='change'){col=lerp(CHG,0.5+0.5*Math.max(-1,Math.min(1,dzcur[i]/D.lim)));k=0.78+0.4*sh;}
  else if(st.layer==='veg'){col=lerp(VEGC,vg[i]/255);k=0.6+0.6*sh;}
  else{const f=o.flow[i]/255,a=Math.pow(f,0.8),g=lerp(FLW,f),b=(0.55+0.45*sh)*235;col=[b*(1-a)+g[0]*a,b*(1-a)+g[1]*a,b*(1-a)+g[2]*a];k=1;}
  const p=i*4;d[p]=Math.min(255,col[0]*k);d[p+1]=Math.min(255,col[1]*k);d[p+2]=Math.min(255,col[2]*k);d[p+3]=255;}
 octx.putImageData(img,0,0);ctx.imageSmoothingEnabled=false;ctx.drawImage(off,0,0,600,600);
 // legend
 const bar=document.getElementById('bar'),tk=document.getElementById('ticks'),lt=document.getElementById('lgtext');let stops,labs,txt;
 if(st.layer==='terrain'){stops=TER;labs=[D.zmin,D.zmax].map(v=>v.toFixed(0)+' m');txt='elevation, with relief shading';}
 else if(st.layer==='change'){stops=CHG;const L=D.lim;labs=[(-L).toFixed(2)+' m (loss)','0',(L).toFixed(2)+' m (gain)'];txt='change since start, centred on zero (colours saturate at the ends)';}
 else if(st.layer==='veg'){stops=VEGC;labs=['bare','full cover'];txt='vegetation cover';}
 else{stops=FLW;labs=['10^'+D.flo.toFixed(1),'10^'+D.fhi.toFixed(1)+' m³/yr'];txt='mean annual runoff through the cell (log scale), final state';}
 bar.style.background='linear-gradient(to right,'+stops.map(s=>'rgb('+s.map(Math.round)+')').join(',')+')';
 tk.innerHTML=labs.map(l=>'<span>'+l+'</span>').join('');lt.textContent=txt;
 const y=Math.round(D.years*st.t/D.nsnap);document.getElementById('tlabel').textContent='year '+y+(st.t===0?' (before)':st.t===D.nsnap?' (after)':'');
 document.getElementById('stat').textContent='This run: ~'+o.rain+' mm/yr of storm rain; '+o.ero.toLocaleString()+' m³ of soil moved by flow in total; '+o.exp.toLocaleString()+' m³ left through the bottom edge (final state).';}
function refresh(){document.querySelectorAll('.seg button[data-v]').forEach(b=>{const par=b.parentNode.id,key={layers:'layer',storm:'s',cover:'v'}[par];b.classList.toggle('on',String(st[key])===b.dataset.v);});draw();}
document.getElementById('time').oninput=e=>{st.t=+e.target.value;draw();};
let timer=null;document.getElementById('play').onclick=()=>{if(timer){clearInterval(timer);timer=null;return;}
 if(st.t>=D.nsnap)st.t=0;timer=setInterval(()=>{st.t++;document.getElementById('time').value=st.t;draw();if(st.t>=D.nsnap){clearInterval(timer);timer=null;}},700);};
cv.addEventListener('mousemove',e=>{const R=cv.getBoundingClientRect(),c=Math.floor((e.clientX-R.left)/R.width*n),r=Math.floor((e.clientY-R.top)/R.height*n);if(r<0||c<0||r>=n||c>=n)return;const i=r*n+c;
 document.getElementById('readout').textContent='Cell ('+Math.round(r*D.dx)+' m down, '+Math.round(c*D.dx)+' m across): elevation '+zcur[i].toFixed(2)+' m; change '+(dzcur[i]>=0?'+':'')+dzcur[i].toFixed(3)+' m; vegetation '+Math.round(veg[st.v][i]/255*100)+'%';});
refresh();
</script></body></html>
"""


# ------------------------------------------------------------------------ main
def main():
    global VF_GLOBAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    ss_rough, ss_veg, ss_storm = np.random.SeedSequence(a.seed).spawn(3)
    z0 = make_initial(ss_rough)
    VF_GLOBAL = make_veg_field(ss_veg)
    results = {}
    for si, sf in enumerate(STORMINESS):          # base case first
        for vi, cf in enumerate(COVER):
            results[(si, vi)] = simulate(z0, VF_GLOBAL, ss_storm, sf, cf)
    base = results[(BASE_S, BASE_V)]
    z1 = base["z"]
    dz = z1 - z0
    np.save(os.path.join(a.out, "z_initial.npy"), z0.astype(np.float64))
    np.save(os.path.join(a.out, "z_final.npy"), z1.astype(np.float64))
    tel = dict(seed=a.seed, grid_shape=[N, N], cell_size_m=DX, years_simulated=YEARS,
               timesteps=NSTEPS, open_boundaries=["south"],
               sediment_exported_m3=float(base["exported"]),
               uplift_or_baselevel_m3=0.0,
               max_erosion_m=float(max(0.0, -dz.min())),
               max_deposition_m=float(max(0.0, dz.max())),
               mass_balance_error_pct=float(base["err"]))
    with open(os.path.join(a.out, "telemetry.json"), "w") as f:
        json.dump(tel, f, indent=2)
    make_png(os.path.join(a.out, "map.png"), z0, base)
    make_html(os.path.join(a.out, "map.html"), z0, results, a.seed)
    print(json.dumps(tel, indent=2))
    print("gross eroded m3 %.0f, gross deposited m3 %.0f, net grid change m3 %.1f, "
          "worst scenario mass error %.2e %%, elapsed %.1f s"
          % (base["gross_ero"], base["gross_dep"], base["vol_change"],
             max(r["err"] for r in results.values()), time.time() - t0))


if __name__ == "__main__":
    main()
