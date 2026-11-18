"""Day 17 S3 weekly (D343): shaded minutes by declination week, near at 4 m (from 2 m horizons),
region at 30 m (from 15 m horizons). Same horizons as s3_shade.py. Output: uint8 shade share
stacks (week, row, col) as .npy plus weekly.json (per-week daylight minutes, dates per week)."""
import os
import json
import time
from pathlib import Path

import numpy as np
import rasterio

from horizon import horizon, far_on_near, accumulate_weeks
from sun import positions, weekly_bins, N_WEEKS


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


OUT = _need("MC26_DAY17_DATA") / "derived"
t0 = time.time()
bins, minutes, b_of_doy = weekly_bins(positions())


def read(name):
    with rasterio.open(OUT / name) as s:
        return s.read(1).astype("float32"), s.transform


zn = {k: read(f"near_{k}_2m.tif") for k in ("dsm", "dem")}
zr = {k: read(f"region_{k}_15m.tif") for k in ("dtm", "dsm")}
ntr, rtr = zn["dsm"][1], zr["dtm"][1]
ny, nx = zn["dsm"][0].shape
RY, RX = zr["dtm"][0].shape
acc = {s: np.zeros((ny // 2, nx // 2, N_WEEKS), np.uint32) for s in zn}
racc = {s: np.zeros((RY // 2, RX // 2, N_WEEKS), np.uint32) for s in zr}
for i, (az, (e, wk)) in enumerate(sorted(bins.items())):
    hr = {s: horizon(z, az, 15.0) for s, (z, _) in zr.items()}
    for s in zr:
        accumulate_weeks(racc[s], hr[s][0], e, wk, 2)
    ang, dist = hr["dtm"]
    H = (zr["dtm"][0] + np.tan(ang) * dist).astype("float32")
    H[dist == 0] = -1e9
    for s, (z, _) in zn.items():
        hn, _ = horizon(z, az, 2.0)
        h = far_on_near(H, dist, rtr.c, rtr.f, 15.0, z, ntr.c, ntr.f, 2.0, hn)
        accumulate_weeks(acc[s], h, e, wk, 2)
    if i % 40 == 0:
        print(f"bin {i + 1}/{len(bins)} {time.time() - t0:.0f}s", flush=True)

den = minutes / 5.0  # positions per week per fine cell
for name, d, k in (("near", acc, 4), ("region", racc, 4)):
    for s, a in d.items():
        share = a / (den[None, None, :] * k)
        np.save(OUT / f"weekly_{name}_{s}.npy", np.clip(np.round(share * 255), 0, 255).astype("uint8").transpose(2, 0, 1))
ref = (np.datetime64("2025-12-21") + 7 * np.arange(N_WEEKS)).astype(str).tolist()
info = {"ref_dates": ref, "daylight_minutes": minutes.tolist(), "bucket_of_doy_2026": b_of_doy.tolist(),
        "seconds": round(time.time() - t0)}
(OUT / "weekly.json").write_text(json.dumps(info))
print(info["seconds"], "s; daylight minutes per week", minutes.min(), minutes.max())
