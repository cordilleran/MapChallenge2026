"""Day 17 S2: does the sweep's near-range jitter matter for shade share?

At 150 random cells of a DSM and a DEM window, annual shade share from the sweep against
shade share from brute-force bilinear rays, for every 1-degree sun bin. Within-window only
(no far field), which is the harder case for near-range error.
"""
import os
import json
from pathlib import Path

import numpy as np
import rasterio

from horizon import horizon, brute
from sun import positions, binned


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


OUT = _need("MC26_DAY17_DATA") / "derived"
bins, totals = binned(positions())
res = {"sun_bins": len(bins), "daylight_minutes_year": totals["year"]}
for name in ("near_dsm_2m.tif", "near_dem_2m.tif"):
    with rasterio.open(OUT / name) as s:
        z = s.read(1, window=((1500, 2700), (2000, 3200))).astype("float32")
    cells = np.random.default_rng(7).integers(100, 1100, size=(150, 2))
    sw = np.zeros(len(cells)); bf = np.zeros(len(cells))
    for az, entry in bins.items():
        ang, _ = horizon(z, az, 2.0)
        e, cum = entry["year"]
        for i, (r, c) in enumerate(cells):
            sw[i] += cum[np.searchsorted(e, ang[r, c])]
            bf[i] += cum[np.searchsorted(e, brute(z, int(r), int(c), az, 2.0, step=0.5))]
    d = (sw - bf) / totals["year"] * 100
    res[name] = {"median_abs_pp": round(float(np.median(np.abs(d))), 2),
                 "p95_abs_pp": round(float(np.percentile(np.abs(d), 95)), 2),
                 "mean_signed_pp": round(float(d.mean()), 2),
                 "share_range_pct": [round(float(bf.min() / totals["year"] * 100), 1), round(float(bf.max() / totals["year"] * 100), 1)]}
(OUT / "s2_share_check.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
