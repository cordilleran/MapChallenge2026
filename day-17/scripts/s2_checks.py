"""Day 17 S2 checks: C1 (sweep against brute force) and C2 (sun position), plus grid convergence."""
import os
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib
import rasterio
from pyproj import Transformer

from horizon import horizon, brute


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


OUT = _need("MC26_DAY17_DATA") / "derived"
LAT, LON = 49.03, -118.44
res = {}

# C2: sun at local solar noon, 21 Dec 2026
t = pd.date_range("2026-12-21 18:00", "2026-12-21 21:00", freq="1min", tz="UTC")
sp = pvlib.solarposition.get_solarposition(t, LAT, LON, altitude=520)
res["C2_noon_elev_dec21_deg"] = round(float(sp.apparent_elevation.max()), 2)
res["C2_expected_approx_deg"] = round(90 - LAT - 23.44, 2)

# Grid convergence: grid azimuth of true north at the site (UTM 11N)
tr = Transformer.from_crs("EPSG:4326", "EPSG:26911", always_xy=True)
x0, y0 = tr.transform(LON, LAT)
x1, y1 = tr.transform(LON, LAT + 0.01)
res["grid_az_of_true_north_deg"] = round(math.degrees(math.atan2(x1 - x0, y1 - y0)), 3)

# C1: sweep against brute force on a 1500 x 1500 window of the 2 m DSM (hills and town)
with rasterio.open(OUT / "near_dsm_2m.tif") as s:
    z = s.read(1, window=((1500, 3000), (2000, 3500))).astype("float32")
rng = np.random.default_rng(17)
cells = rng.integers(0, 1500, size=(300, 2))
diffs = []
timing = {}
for az in (60, 100, 135, 160, 180, 205, 250, 300):
    t0 = time.time(); ang, _ = horizon(z, az, 2.0); timing[az] = round(time.time() - t0, 2)
    for r, c in cells:
        b = brute(z, int(r), int(c), az, 2.0)
        if b > -np.pi / 2 + 1e-6:
            diffs.append(math.degrees(ang[r, c] - b))
d = np.abs(np.array(diffs))
res["C1_n"] = int(d.size)
res["C1_median_abs_deg"] = round(float(np.median(d)), 3)
res["C1_p95_abs_deg"] = round(float(np.percentile(d, 95)), 3)
res["C1_signed_mean_deg"] = round(float(np.mean(diffs)), 3)
res["sweep_seconds_1500sq"] = timing
(OUT / "s2_checks.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
