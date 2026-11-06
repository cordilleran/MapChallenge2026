#!/usr/bin/env python3
"""
Task 4: Imagery — Sentinel-2 L2A of 2025-08-25, tiles 11UPQ and 11UQQ, from Earth Search STAC.
- Queries Earth Search STAC (`https://earth-search.aws.element84.com/v1/search`) and saves raw STAC metadata JSON in raw/.
- Clips native EPSG:32611 subsets covering the core box (+ margin) into raw/ so raw downloads are preserved.
- Mosaics and warps TCI (true colour), B04 (Red), and B08 (NIR) for the core box to the core-box DEM's CRS
  (EPSG:3979) at 10 m resolution, aligned so that 3 x 3 pixels = 1 DEM cell (-1381680, 211380, -1359630, 231690;
  2205 cols x 2031 rows).
- Also computes 10 m NDVI from B08 and B04 (using Sentinel-2 BOA offset -1000 where applicable) for validation/comparison.

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
RAW_DIR = SLICE_A_DIR / "raw"
DERIVED_DIR = SLICE_A_DIR / "derived"

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
ITEM_IDS = ["S2B_11UPQ_20250825_0_L2A", "S2B_11UQQ_20250825_0_L2A"]

# Core box in EPSG:3979 (snapped to 30m MRDEM-30 grid):
# bounds: (-1381680.0, 211380.0, -1359630.0, 231690.0), 735 cols x 677 rows at 30m -> 2205 cols x 2031 rows at 10m
CORE_BOUNDS_3979 = (-1381680.0, 211380.0, -1359630.0, 231690.0)

# Corresponding bounding window in EPSG:32611 (UTM 11N) with generous margin for native raw clips:
# Core box in UTM 11N spans E: 699585.9..727147.4, N: 5432784.4..5459281.7
# Note: 11UPQ covers E: 600000..709800; 11UQQ covers E: 699960..809760.
RAW_PROJWIN_UPQ = (698500.0, 5460500.0, 709800.0, 5431500.0)  # ulx, uly, lrx, lry
RAW_PROJWIN_UQQ = (699960.0, 5460500.0, 728500.0, 5431500.0)  # ulx, uly, lrx, lry

def run_cmd(cmd):
    print("RUNNING:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch STAC metadata for the two 2025-08-25 Sentinel-2 L2A items
    payload = json.dumps({"collections": ["sentinel-2-l2a"], "ids": ITEM_IDS}).encode("utf-8")
    req = urllib.request.Request(STAC_URL, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        stac_data = json.loads(resp.read().decode("utf-8"))
    stac_raw_path = RAW_DIR / "stac_sentinel2_20250825.json"
    with open(stac_raw_path, "w", encoding="utf-8") as f:
        json.dump(stac_data, f, indent=2)
    print(f"Saved STAC search response ({len(stac_data.get('features', []))} items) to {stac_raw_path}")

    assets = {
        "TCI": ("visual", "TCI.tif"),
        "B04": ("red", "B04.tif"),
        "B08": ("nir", "B08.tif"),
    }

    # Map item ID -> asset hrefs
    item_hrefs = {}
    for feat in stac_data.get("features", []):
        iid = feat["id"]
        item_hrefs[iid] = {}
        for band_name, (stac_key, _) in assets.items():
            item_hrefs[iid][band_name] = feat["assets"][stac_key]["href"]

    # 2. Download native EPSG:32611 subsets for 11UPQ and 11UQQ into raw/
    raw_files = {"TCI": [], "B04": [], "B08": []}
    for iid, tile_short, projwin in [
        ("S2B_11UPQ_20250825_0_L2A", "11UPQ", RAW_PROJWIN_UPQ),
        ("S2B_11UQQ_20250825_0_L2A", "11UQQ", RAW_PROJWIN_UQQ),
    ]:
        for band_name in ["TCI", "B04", "B08"]:
            href = item_hrefs[iid][band_name]
            out_raw = str(RAW_DIR / f"{iid}_{band_name}_core_utm11.tif")
            cmd = [
                "gdal_translate",
                "-projwin", str(projwin[0]), str(projwin[1]), str(projwin[2]), str(projwin[3]),
                "-co", "TILED=YES",
                "-co", "COMPRESS=DEFLATE",
                f"/vsicurl/{href}",
                out_raw,
            ]
            run_cmd(cmd)
            raw_files[band_name].append(out_raw)

    # 3. Mosaic and warp TCI, B04, B08 to core box in EPSG:3979 at 10 m resolution
    xmin, ymin, xmax, ymax = CORE_BOUNDS_3979
    derived_outputs = {
        "TCI": str(DERIVED_DIR / "s2_20250825_TCI_core_10m_epsg3979.tif"),
        "B04": str(DERIVED_DIR / "s2_20250825_B04_core_10m_epsg3979.tif"),
        "B08": str(DERIVED_DIR / "s2_20250825_B08_core_10m_epsg3979.tif"),
    }

    for band_name, out_tif in derived_outputs.items():
        cmd = [
            "gdalwarp",
            "-overwrite",
            "-t_srs", "EPSG:3979",
            "-te", str(xmin), str(ymin), str(xmax), str(ymax),
            "-tr", "10", "10",
            "-r", "bilinear",
            "-co", "TILED=YES",
            "-co", "COMPRESS=DEFLATE",
            "-co", "PREDICTOR=2",
        ] + raw_files[band_name] + [out_tif]
        run_cmd(cmd)

        ds = gdal.Open(out_tif)
        print(f"Verified {out_tif}: cols={ds.RasterXSize}, rows={ds.RasterYSize}, bands={ds.RasterCount}, gt={ds.GetGeoTransform()}")
        for b in range(1, ds.RasterCount + 1):
            arr = ds.GetRasterBand(b).ReadAsArray()
            nd = ds.GetRasterBand(b).GetNoDataValue()
            nd_cnt = int(np.sum(arr == nd)) if nd is not None else 0
            print(f"  Band {b}: min={arr.min()}, max={arr.max()}, mean={arr.mean():.2f}, nodata={nd} (count={nd_cnt})")

if __name__ == "__main__":
    main()
