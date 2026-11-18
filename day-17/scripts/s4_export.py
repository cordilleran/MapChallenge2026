"""Day 17 S4: export the shade layers and meshes for the three.js page (site/data/day17/).

Near: geometry = bare-earth DEM at 10 m (Uint16, 0.05 m steps above Z0); shade textures at 2 m as
greyscale WebP (byte = round(share*255)), six layers {year,dec,jun} x {dsm,dem}; a 10 m readout grid
of all six layers plus the gap mask (Uint8) for the hover panel.
Region: geometry = GEM-15 DTM at 90 m; shade textures at 30 m, {year,dec,jun} x {dtm,dsm}.
Lossy WebP quality is set so the round-trip error is reported (meta.json, 'webp_err').
"""
import io
import os
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


D = _need("MC26_DAY17_DATA") / "derived"
SITE = Path(os.environ.get("D17_SITE_DATA", Path(__file__).resolve().parents[2] / "site/data/day17"))
SITE.mkdir(parents=True, exist_ok=True)
Z0, ZS = 400.0, 0.05
Q = 82
LAYERS = ("year", "dec", "jun")


def read(name):
    with rasterio.open(D / name) as s:
        return s.read(1).astype("float32"), s.transform


def block_mean(a, k):
    ny, nx = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    return a[:ny, :nx].reshape(ny // k, k, nx // k, k).mean(axis=(1, 3))


def heights(a, name):
    q = np.clip(np.round((a - Z0) / ZS), 0, 65535).astype("<u2")
    (SITE / name).write_bytes(q.tobytes())


def webp(share, name):
    b = np.clip(np.round(share * 255), 0, 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(b, "L").save(buf, "WEBP", quality=Q, method=6)
    (SITE / name).write_bytes(buf.getvalue())
    back = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("L")).astype(int)
    err = np.abs(back - b.astype(int)) / 255 * 100
    return {"kb": round(len(buf.getvalue()) / 1024), "err_pp_median": round(float(np.median(err)), 2),
            "err_pp_p95": round(float(np.percentile(err, 95)), 2)}


meta = {"z0": Z0, "zscale": ZS, "webp_quality": Q, "files": {}}

# near
dem2, ntr = read("near_dem_2m.tif")
ny2, nx2 = dem2.shape
meta["near"] = {"x0": ntr.c, "y1": ntr.f, "cell_tex": 2.0, "tex_w": nx2, "tex_h": ny2,
                "x1": ntr.c + nx2 * 2.0, "y0": ntr.f - ny2 * 2.0}
g = block_mean(dem2, 5)
meta["near"].update(geom_cell=10.0, geom_w=g.shape[1], geom_h=g.shape[0])
heights(g, "near_dem_10m.u16")
readout = []
for s in ("dsm", "dem"):
    for L in LAYERS:
        a, _ = read(f"shade_{L}_{s}_2m.tif")
        meta["files"][f"near_{L}_{s}"] = webp(a, f"near_{L}_{s}.webp")
        readout.append(np.clip(np.round(block_mean(a, 5) * 255), 0, 255).astype("uint8"))
gap, _ = read("near_gapmask_2m.tif")
readout.append((block_mean(gap, 5) > 0.5).astype("uint8"))
readout.append(np.clip(np.round((g - Z0) / 4), 0, 255).astype("uint8"))  # elevation, 4 m steps
(SITE / "near_readout_10m.u8").write_bytes(np.stack(readout).tobytes())
meta["near"]["readout_layers"] = [f"{L}_{s}" for s in ("dsm", "dem") for L in LAYERS] + ["gap", "elev4m"]

# region
dtm, rtr = read("region_dtm_15m.tif")
gr = block_mean(dtm, 6)
meta["region"] = {"x0": rtr.c, "y1": rtr.f, "geom_cell": 90.0, "geom_w": gr.shape[1], "geom_h": gr.shape[0],
                  "cell_tex": 30.0}
heights(gr, "region_dtm_90m.u16")
for s in ("dtm", "dsm"):
    for L in LAYERS:
        a, _ = read(f"region_shade_{L}_{s}_15m.tif")
        a2 = block_mean(a, 2)
        meta["region"]["tex_w"], meta["region"]["tex_h"] = a2.shape[1], a2.shape[0]
        meta["files"][f"region_{L}_{s}"] = webp(a2, f"region_{L}_{s}.webp")
rro = []
for s in ("dsm", "dtm"):
    for L in LAYERS:
        a, _ = read(f"region_shade_{L}_{s}_15m.tif")
        rro.append(np.clip(np.round(block_mean(a, 6) * 255), 0, 255).astype("uint8"))
rro.append(np.clip(np.round((gr - Z0) / 8), 0, 255).astype("uint8"))  # elevation, 8 m steps
(SITE / "region_readout_90m.u8").write_bytes(np.stack(rro).tobytes())
meta["region"]["readout_layers"] = [f"{L}_{s}" for s in ("dsm", "dtm") for L in LAYERS] + ["elev8m"]
meta["region"]["x1"] = rtr.c + meta["region"]["tex_w"] * 30.0
meta["region"]["y0"] = rtr.f - meta["region"]["tex_h"] * 30.0
# weekly declination layers (D343), stored as a temporal PCA basis (D353): per stack, the mean over the
# 27 weeks plus K component images (WebP), and a 27 x K weight table. The page rebuilds any week on the GPU
# as mean + sum_j w[week][j] * comp_j, and interpolates the weights between weeks by solar declination.
# Near 4 m, region 30 m: the full resolution of the stacks (8 m frames lost the shadow edges, D351 reversed).
K_PCA, Q_PCA = 6, 90
wk = json.loads((D / "weekly.json").read_text())
for old in list(SITE.glob("near_w[0-9][0-9]_*.webp")) + list(SITE.glob("region_w[0-9][0-9]_*.webp")):
    old.unlink()


def pca_stack(st, prefix):
    """st: (T, H, W) uint8. Writes prefix_pc0..K.webp; returns the meta entry with weights, ranges and errors."""
    T, H, W_ = st.shape
    X = st.reshape(T, -1).astype("float32")
    mu = X.mean(axis=0)
    Xc = X - mu
    C = (Xc.astype("float64") @ Xc.T.astype("float64")) / Xc.shape[1]
    ev, V = np.linalg.eigh(C)
    order = ev.argsort()[::-1]
    ev, V = ev[order], V[:, order].astype("float32")
    imgs = [mu] + [V[:, j] @ Xc for j in range(K_PCA)]
    del Xc
    ranges, deq, kb = [], [], 0
    for j, im in enumerate(imgs):
        lo, hi = float(np.percentile(im, 0.01)), float(np.percentile(im, 99.99))
        u8 = np.clip(np.round((im - lo) / (hi - lo) * 255), 0, 255).astype("uint8").reshape(H, W_)
        buf = io.BytesIO()
        Image.fromarray(u8, "L").save(buf, "WEBP", quality=Q_PCA, method=6)
        (SITE / f"{prefix}_pc{j}.webp").write_bytes(buf.getvalue())
        kb += len(buf.getvalue()) / 1024
        back = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("L")).astype("float32").ravel()
        deq.append(back / 255 * (hi - lo) + lo)
        ranges.append([round(lo, 4), round(hi, 4)])
    rec = deq[0] + V[:, :K_PCA] @ np.stack(deq[1:])          # what the page will show, in bytes (0-255)
    e = np.abs(np.clip(rec, 0, 255) - X) / 255 * 100
    rng = np.random.default_rng(0)
    smp = e[:, rng.choice(e.shape[1], min(e.shape[1], 2_000_000), replace=False)]
    # the weekly-to-annual check (as s3_weekly_check): daylight-weighted weeks rebuild the year
    w_day = np.asarray(wk["daylight_minutes"], "float64")
    ann_err = np.abs((w_day / w_day.sum()) @ (np.clip(rec, 0, 255) - X)) / 255 * 100
    return {"k": K_PCA, "shape": [H, W_], "ranges": ranges,
            "weights": [[round(float(x), 5) for x in row] for row in V[:, :K_PCA]],
            "variance_explained": round(float(ev[:K_PCA].sum() / ev.sum()), 5), "kb": round(kb),
            "err_pp": {"p50": round(float(np.percentile(smp, 50)), 2), "p95": round(float(np.percentile(smp, 95)), 2),
                       "p99": round(float(np.percentile(smp, 99)), 2)},
            "annual_err_pp_p95": round(float(np.percentile(ann_err, 95)), 2)}


pcs = {}
for s in ("dsm", "dem"):
    pcs[f"near_{s}"] = pca_stack(np.load(D / f"weekly_near_{s}.npy"), f"near_wk_{s}")
for s in ("dsm", "dtm"):
    pcs[f"region_{s}"] = pca_stack(np.load(D / f"weekly_region_{s}.npy"), f"region_wk_{s}")
nH, nW = pcs["near_dsm"]["shape"]
rH, rW = pcs["region_dsm"]["shape"]
# fractional week of every day of 2026, by solar declination (the sun's path depends on declination alone)
import pandas as pd
from pvlib.solarposition import declination_spencer71
ref = pd.to_datetime(wk["ref_dates"])
dref = declination_spencer71(ref.dayofyear.to_numpy())
dday = declination_spencer71(np.arange(1, 366))
assert np.all(np.diff(dref) > 0), "reference declinations must rise from December to June"
meta["weekly"] = {"ref_dates": wk["ref_dates"], "bucket_of_doy": wk["bucket_of_doy_2026"],
                  "daylight_minutes": wk["daylight_minutes"],
                  "week_of_doy": [round(float(x), 3) for x in np.interp(dday, dref, np.arange(len(dref)))],
                  "pca": pcs,
                  "near_bounds": [ntr.c, ntr.f - nH * 4.0, ntr.c + nW * 4.0, ntr.f],
                  "region_bounds": [rtr.c, rtr.f - rH * 30.0, rtr.c + rW * 30.0, rtr.f]}
meta["weekly_files_kb_total"] = sum(v["kb"] for v in pcs.values())
meta["weekly_err_pp_p95_max"] = max(v["err_pp"]["p95"] for v in pcs.values())
meta["daylight_hours_year"] = round(json.loads((D / "s3_summary.json").read_text())["daylight_minutes"]["year"] / 60)
(SITE / "meta.json").write_text(json.dumps(meta, indent=1))
print(json.dumps(meta["files"], indent=1))
print("total MB", round(sum(p.stat().st_size for p in SITE.iterdir()) / 1e6, 1))

# labels: GeoNames (CC BY 4.0) points; peaks snapped to the regional DTM maximum within 1.5 km
# (GeoNames coordinates here are coarse: Observation Mountain sits on the town point, so it is dropped)
from pyproj import Transformer
tr = Transformer.from_crs("EPSG:4326", "EPSG:26911", always_xy=True)
GN = _need("MC26_GEONAMES")
want_peaks = {"Hardy Mountain", "Mount Attwood", "Spencer Hill", "Mount Morrissey", "Boundary Mountain",
              "Goat Mountain", "Eagle Mountain", "Vulcan Mountain", "Owl Mountain", "Thimble Mountain", "Mount Wright"}
want_places = {"Grand Forks", "Danville", "Gilpin", "Christina Lake"}
rows = {}
with open(GN, encoding="utf-8") as f:
    for line in f:
        p = line.split("\t")
        if p[8] not in ("CA", "US"):
            continue
        lat, lon = float(p[4]), float(p[5])
        if not (48.9 < lat < 49.25 and -118.75 < lon < -118.15):
            continue
        if (p[1] in want_peaks and p[7] in ("MT", "HLL")) or (p[1] in want_places and p[7].startswith("PPL")):
            rows[p[1]] = (lon, lat, p[7])
labels = []
for name, (lon, lat, code) in sorted(rows.items()):
    x, y = tr.transform(lon, lat)
    if code.startswith("PPL"):
        labels.append({"name": name, "x": round(x), "y": round(y), "kind": "place"})
        continue
    r = int((rtr.f - y) / 15); c = int((x - rtr.c) / 15); k = 100
    win = dtm[max(r - k, 0):r + k + 1, max(c - k, 0):c + k + 1]
    rr, cc = np.unravel_index(np.argmax(win), win.shape)
    r2, c2 = max(r - k, 0) + rr, max(c - k, 0) + cc
    edge = rr in (0, win.shape[0] - 1) or cc in (0, win.shape[1] - 1)
    shift = 15 * float(np.hypot(r2 - r, c2 - c))
    if edge or shift > 1200:  # no summit inside the window, or a snap too far to trust
        print("dropped", name, "(no summit within 1.5 km)")
        continue
    labels.append({"name": name, "x": round(rtr.c + (c2 + 0.5) * 15), "y": round(rtr.f - (r2 + 0.5) * 15),
                   "kind": "peak", "z": round(float(dtm[r2, c2])), "snap_m": round(shift)})
(SITE / "labels.json").write_text(json.dumps(labels, indent=1))
print(json.dumps(labels, indent=1))
