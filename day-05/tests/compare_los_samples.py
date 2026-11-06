#!/usr/bin/env python3
"""Per-sample check for los_test.js: share of the 15 m profile samples whose visible flag
(browser, day05core.js) matches the r.viewshed raster cell they fall in.

Run after `node day-05/tests/los_test.js` (which writes los_samples_out.json):
    MC26_DAY05_DIR=/path/to/day-05-in python3 day-05/tests/compare_los_samples.py
"""
import json
import os
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("MC26_DAY05_DIR", str(HERE.parents[1].parent / "in")))
VS = DATA / "viewsheds"

samples = json.loads((HERE / "los_samples_out.json").read_text())
cache, agree, n = {}, 0, 0
for stn, x, y, vis in samples:
    if stn not in cache:
        ds = gdal.Open(str(VS / f"vs_{stn}_main.tif"))
        cache[stn] = (ds.GetGeoTransform(), ds.ReadAsArray())
    gt, a = cache[stn]
    c, r = int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5])
    if 0 <= r < a.shape[0] and 0 <= c < a.shape[1]:
        n += 1
        agree += int(bool(a[r, c]) == bool(vis))
print(f"samples: {agree}/{n} agree with r.viewshed ({100 * agree / n:.1f}%, target 99%)")
