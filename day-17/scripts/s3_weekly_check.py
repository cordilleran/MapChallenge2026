"""Check D343: daylight-weighted weekly shares rebuild the annual share (near DSM at 4 m)."""
import os
import json
from pathlib import Path
import numpy as np, rasterio


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()

D = _need("MC26_DAY17_DATA") / "derived"
wk = np.load(D / "weekly_near_dsm.npy").astype("float32") / 255
m = np.array(json.loads((D / "weekly.json").read_text())["daylight_minutes"], "float32")
rebuilt = (wk * m[:, None, None]).sum(0) / m.sum()
with rasterio.open(D / "shade_year_dsm_2m.tif") as s:
    a = s.read(1)
ny, nx = rebuilt.shape
ann = a[:ny * 2, :nx * 2].reshape(ny, 2, nx, 2).mean((1, 3))
d = np.abs(rebuilt - ann) * 100
out = {"median_pp": round(float(np.median(d)), 3), "p99_pp": round(float(np.percentile(d, 99)), 3), "max_pp": round(float(d.max()), 2)}
(D / "s3_weekly_check.json").write_text(json.dumps(out)); print(out)
