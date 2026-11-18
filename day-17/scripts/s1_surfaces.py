"""Day 17 S1: build the surfaces for the shade model.

Near field: 2025 BC LiDAR DSM and DEM, 1 m -> 2 m (mean of 2x2, D335), gaps filled from the
GEM-15 DTM after a datum shift measured on the overlap (D337).
Far field: GEM-15 DTM and DSM (band 1 mean), 15 m, about 25 km around, shifted to the LiDAR datum.

Outputs (datastore day17/derived): near_dsm_2m.tif, near_dem_2m.tif, near_gapmask_2m.tif,
region_dtm_15m.tif, region_dsm_15m.tif, s1_summary.json
"""
import os
import json
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


LIDAR = _need("MC26_LIDAR_BC")
D = _need("MC26_DAY17_DATA")
RAW, OUT = D / "raw", D / "derived"
OUT.mkdir(parents=True, exist_ok=True)


def run(cmd):
    subprocess.run(cmd, check=True)


# 1. LiDAR to 2 m (GDAL average ignores nodata)
for kind in ("dsm", "dem"):
    run(["gdal_translate", "-q", "-tr", "2", "2", "-r", "average", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
         str(LIDAR / f"lidar2025_{kind}_grandforks_buffer1_cog.tif"), str(OUT / f"near_{kind}_2m_raw.tif")])

# 2. Regional rasters: fill the small nodata holes (GEM-15 voids) by interpolation
for kind in ("dtm", "dsm"):
    src = RAW / ("gem15_dtm_15m_region.tif" if kind == "dtm" else "gem15_dsm_mean_15m_region.tif")
    run(["gdal_fillnodata", "-q", "-md", "60", "-of", "GTiff", "-co", "COMPRESS=DEFLATE", str(src),
         str(OUT / f"region_{kind}_15m_unshifted.tif")])

with rasterio.open(OUT / "near_dem_2m_raw.tif") as s:
    prof = s.profile
    dem = s.read(1, masked=True).astype("float64")
    transform, crs, shape = s.transform, s.crs, s.shape
with rasterio.open(OUT / "near_dsm_2m_raw.tif") as s:
    dsm = s.read(1, masked=True).astype("float64")


def regional_on_near(path):
    with rasterio.open(path) as s:
        src = s.read(1).astype("float32")
        nd = s.nodata
        dst = np.full(shape, np.nan, "float32")  # shape and transform: the current near grid (extended in 3b)
        reproject(src, dst, src_transform=s.transform, src_crs=s.crs, src_nodata=nd,
                  dst_transform=transform, dst_crs=crs, dst_nodata=np.nan, resampling=Resampling.bilinear)
    return dst


gem_dtm_near = regional_on_near(OUT / "region_dtm_15m_unshifted.tif")

# 3. Datum shift: LiDAR DEM minus GEM-15 DTM on gentle ground (slope < 5 deg on the 2 m DEM)
gy, gx = np.gradient(dem.filled(np.nan), 2.0)
slope = np.degrees(np.arctan(np.hypot(gx, gy)))
ok = (~dem.mask) & np.isfinite(gem_dtm_near) & (slope < 5)
diff = dem.data[ok] - gem_dtm_near[ok]
shift = float(np.median(diff))
summary = {
    "shift_lidar_minus_gem15_dtm_m": round(shift, 3),
    "shift_iqr_m": [round(float(np.percentile(diff, 25)), 3), round(float(np.percentile(diff, 75)), 3)],
    "n_cells_gentle": int(ok.sum()),
}

# 3b. US LiDAR south of the border (D348), on the same columns, stacked under the BC rows.
#     Its vertical datum (NAVD88) is tied to BC's through GEM-15: both are compared with the same GEM-15 DTM.
US = D / "us"
if (US / "us_dem_2m.tif").exists():
    with rasterio.open(US / "us_dem_2m.tif") as s:
        udem = s.read(1, masked=True).astype("float64"); utr = s.transform
    with rasterio.open(US / "us_dsm_2m.tif") as s:
        udsm = s.read(1, masked=True).astype("float64")
    assert abs(utr.c - transform.c) < 1e-6 and abs(utr.f - (transform.f - shape[0] * 2)) < 1e-6, "US grid misaligned"
    assert udem.shape[1] == shape[1]
    ny_bc = shape[0]
    shape = (shape[0] + udem.shape[0], shape[1])
    prof = prof.copy(); prof.update(height=shape[0])
    dem = np.ma.concatenate([dem, udem]); dsm = np.ma.concatenate([dsm, udsm])
    gem_dtm_near = regional_on_near(OUT / "region_dtm_15m_unshifted.tif")
    gy, gx = np.gradient(dem.filled(np.nan), 2.0)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    ok = (~dem.mask) & np.isfinite(gem_dtm_near) & (slope < 5)
    ok[:ny_bc] = False
    du = dem.data[ok] - gem_dtm_near[ok]
    us_shift = float(np.median(du))
    corr = shift - us_shift  # add to US heights to put them on the BC datum
    dem[ny_bc:] += corr; dsm[ny_bc:] += corr
    summary.update(us_shift_us_minus_gem15_m=round(us_shift, 3), us_correction_m=round(corr, 3),
                   us_iqr_m=[round(float(np.percentile(du, 25)), 3), round(float(np.percentile(du, 75)), 3)],
                   us_rows=int(udem.shape[0]))
    # the seam: BC's last row against the US first row, on gentle ground
    seam = (dem[ny_bc - 1] - dem[ny_bc]).compressed()
    summary["seam_dem_step_median_m"] = round(float(np.median(seam)), 3) if seam.size else None
    summary["seam_cells_both_valid"] = int(seam.size)

# 4. Fill LiDAR gaps from shifted GEM-15: the DEM from its DTM, the DSM from its DSM (band 1 mean), so
#    forest in the gap blocks still casts shade, as it does in the regional ring (D346)
fills = {"dem": gem_dtm_near + shift, "dsm": regional_on_near(OUT / "region_dsm_15m_unshifted.tif") + shift}
gap = dem.mask | dsm.mask
summary["near_gap_share"] = round(float(gap.mean()), 4)
for name, arr in (("dem", dem), ("dsm", dsm)):
    a = arr.filled(np.nan)
    a = np.where(np.isnan(a), fills[name], a)
    if name == "dsm":
        a = np.maximum(a, np.where(np.isnan(arr.filled(np.nan)), fills["dem"], -np.inf))  # DSM never below DEM
    if name == "dsm":
        # D349: despike. The US DSM (max of returns) keeps unflagged noise points: a cell more than 10 m above
        # its 5x5 median takes the median, and nothing stands more than 60 m above the filled DEM.
        from scipy.ndimage import median_filter
        med = median_filter(a, size=5)
        spike = (a - med) > 10
        summary["dsm_despiked_share_bc"] = round(float(spike[:4271].mean()), 5)
        summary["dsm_despiked_share_us"] = round(float(spike[4271:].mean()), 5) if a.shape[0] > 4271 else None
        a = np.where(spike, med, a)
        cap = dem_filled + 60
        summary["dsm_capped_share"] = round(float((a > cap).mean()), 5)
        a = np.minimum(a, cap)
    else:
        dem_filled = a
    assert np.isfinite(a).all(), f"{name}: unfilled cells remain"
    p = prof.copy(); p.update(dtype="float32", nodata=None, compress="deflate", tiled=True)
    with rasterio.open(OUT / f"near_{name}_2m.tif", "w", **p) as d:
        d.write(a.astype("float32"), 1)
p = prof.copy(); p.update(dtype="uint8", nodata=None, compress="deflate", tiled=True)
with rasterio.open(OUT / "near_gapmask_2m.tif", "w", **p) as d:
    d.write(gap.astype("uint8"), 1)

# 5. Shift the regional rasters to the LiDAR datum
for kind in ("dtm", "dsm"):
    with rasterio.open(OUT / f"region_{kind}_15m_unshifted.tif") as s:
        a = s.read(1, masked=True).astype("float32")
        p = s.profile
    summary[f"region_{kind}_remaining_nodata"] = int(a.mask.sum())
    a = (a + shift).filled(np.nan)
    p.update(dtype="float32", nodata=np.nan)
    with rasterio.open(OUT / f"region_{kind}_15m.tif", "w", **p) as d:
        d.write(a, 1)

summary["near_shape"] = list(shape)
summary["dsm_minus_dem_p99_m"] = round(float(np.nanpercentile((dsm - dem).filled(np.nan), 99)), 2)
(OUT / "s1_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
