"""Day 17 S3: shade share for 2026, near field (2 m LiDAR DSM and DEM) and region (15 m GEM-15 DTM, DSM).

For each 1-degree sun bin:
  near horizon h_n from the 2 m grid; far horizon from the 15 m regional DTM, carried to the near
  cell through its tangent point (height H, distance d): h_f = atan((H - z_cell)/d), used only where
  d >= FAR_MIN_M (closer tangents are the LiDAR's job). h = max(h_n, h_f).
  shaded minutes += minutes in the bin with sun elevation < h.
Shade share = shaded minutes / daylight minutes in the layer (year, December, June).
"""
import os
import json
import time
from pathlib import Path

import numpy as np
import rasterio

from horizon import horizon, far_on_near, accumulate
from sun import positions, binned, LAYERS


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


OUT = _need("MC26_DAY17_DATA") / "derived"
from horizon import FAR_MIN_M


def read(name):
    with rasterio.open(OUT / name) as s:
        return s.read(1).astype("float32"), s.profile, s.transform


def write(name, arr, prof):
    p = prof.copy(); p.update(dtype="float32", nodata=None, compress="deflate", tiled=True, predictor=3, blockxsize=256, blockysize=256)
    with rasterio.open(OUT / name, "w", **p) as d:
        d.write(arr.astype("float32"), 1)


t0 = time.time()
bins, totals = binned(positions())
zn = {k: read(f"near_{k}_2m.tif") for k in ("dsm", "dem")}
zr = {k: read(f"region_{k}_15m.tif") for k in ("dtm", "dsm")}
nprof, ntr = zn["dsm"][1], zn["dsm"][2]
rprof, rtr = zr["dtm"][1], zr["dtm"][2]
acc = {(s, L): np.zeros(zn[s][0].shape, np.float32) for s in zn for L in LAYERS}
racc = {(s, L): np.zeros(zr[s][0].shape, np.float32) for s in zr for L in LAYERS}

for i, (az, entry) in enumerate(sorted(bins.items())):
    hr = {}
    for s, (z, _, _) in zr.items():
        ang, dist = horizon(z, az, 15.0)
        hr[s] = (ang, dist)
        for L in LAYERS:
            accumulate(racc[(s, L)], ang, *entry[L])
    ang, dist = hr["dtm"]
    H = (zr["dtm"][0] + np.tan(ang) * dist).astype("float32")
    H[dist == 0] = -1e9
    for s, (z, _, _) in zn.items():
        hn, _ = horizon(z, az, 2.0)
        h = far_on_near(H, dist, rtr.c, rtr.f, 15.0, z, ntr.c, ntr.f, 2.0, hn)
        for L in LAYERS:
            accumulate(acc[(s, L)], h, *entry[L])
    if i % 20 == 0:
        print(f"bin {i + 1}/{len(bins)} az {az:.1f} {time.time() - t0:.0f}s", flush=True)

summary = {"daylight_minutes": totals, "far_min_m": FAR_MIN_M, "seconds": round(time.time() - t0)}
for (s, L), a in acc.items():
    share = a / totals[L]
    write(f"shade_{L}_{s}_2m.tif", share, nprof)
    summary[f"near_{s}_{L}_median"] = round(float(np.median(share)), 3)
for L in LAYERS:
    write(f"shade_{L}_objects_2m.tif", (acc[("dsm", L)] - acc[("dem", L)]) / totals[L], nprof)
for (s, L), a in racc.items():
    write(f"region_shade_{L}_{s}_15m.tif", a / totals[L], rprof)
(OUT / "s3_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
