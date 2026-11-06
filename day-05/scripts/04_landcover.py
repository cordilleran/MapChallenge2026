#!/usr/bin/env python3
"""
Task 5: Land cover for the forest scenario — ESA WorldCover 10 m (2021 v200) for the viewshed box,
then a forest fraction raster on the viewshed-box DEM grid (share of 10 m pixels in class 10 'Tree cover'
inside each 30 m cell) and a forest mask (fraction >= 0.5).
Reports the share of forested cells in both the viewshed box and the core box.

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import json
import os
from pathlib import Path
import subprocess
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
RAW_DIR = SLICE_A_DIR / "raw"
DERIVED_DIR = SLICE_A_DIR / "derived"

WC_N48W117_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W117_Map.tif"
WC_N48W114_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W114_Map.tif"

# Viewshed box in EPSG:3979: (-1405890.0, 187590.0, -1335630.0, 256050.0) -> 2342 cols x 2282 rows at 30m
VS_BOUNDS_3979 = (-1405890.0, 187590.0, -1335630.0, 256050.0)
# Core box in EPSG:3979: (-1381680.0, 211380.0, -1359630.0, 231690.0) -> 735 cols x 677 rows at 30m
CORE_BOUNDS_3979 = (-1381680.0, 211380.0, -1359630.0, 231690.0)

def run_cmd(cmd):
    print("RUNNING:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def write_geotiff(path, arr, gt, wkt, dtype, nodata=None):
    driver = gdal.GetDriverByName("GTiff")
    rows, cols = arr.shape
    ds = driver.Create(
        str(path), cols, rows, 1, dtype,
        options=["TILED=YES", "COMPRESS=DEFLATE"]
    )
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    band.FlushCache()
    ds = None

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch native EPSG:4326 subsets from ESA WorldCover 2021 v200 S3 bucket into raw/
    raw_w117 = str(RAW_DIR / "ESA_WorldCover_10m_2021_v200_N48W117_viewshed_wgs84.tif")
    raw_w114 = str(RAW_DIR / "ESA_WorldCover_10m_2021_v200_N48W114_viewshed_wgs84.tif")

    run_cmd([
        "gdal_translate",
        "-projwin", "-114.70", "49.55", "-114.00", "48.72",
        "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
        f"/vsicurl/{WC_N48W117_URL}",
        raw_w117,
    ])
    run_cmd([
        "gdal_translate",
        "-projwin", "-114.00", "49.55", "-113.45", "48.72",
        "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
        f"/vsicurl/{WC_N48W114_URL}",
        raw_w114,
    ])

    # 2. Warp WorldCover to 10 m EPSG:3979 aligned 3x3 with the viewshed-box 30m DEM grid
    wc_10m_vs = str(DERIVED_DIR / "worldcover_2021_viewshed_10m_epsg3979.tif")
    xmin, ymin, xmax, ymax = VS_BOUNDS_3979
    run_cmd([
        "gdalwarp",
        "-overwrite",
        "-t_srs", "EPSG:3979",
        "-te", str(xmin), str(ymin), str(xmax), str(ymax),
        "-tr", "10", "10",
        "-r", "near",
        "-co", "TILED=YES",
        "-co", "COMPRESS=DEFLATE",
        raw_w117, raw_w114,
        wc_10m_vs,
    ])

    # 3. Compute forest fraction (share of 10m pixels in class 10 'Tree cover' inside each 30m DEM cell)
    #    and forest mask (fraction >= 0.5) on the viewshed-box 30m DEM grid
    dem_vs_ds = gdal.Open(str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif"))
    vs_gt = dem_vs_ds.GetGeoTransform()
    vs_wkt = dem_vs_ds.GetProjection()
    vs_cols = dem_vs_ds.RasterXSize  # 2342
    vs_rows = dem_vs_ds.RasterYSize  # 2282

    wc_ds = gdal.Open(wc_10m_vs)
    wc_arr = wc_ds.GetRasterBand(1).ReadAsArray()
    assert wc_arr.shape == (vs_rows * 3, vs_cols * 3), f"Unexpected shape {wc_arr.shape}"

    # Check class distribution in WorldCover 10m viewshed box
    unique_classes, counts = np.unique(wc_arr, return_counts=True)
    class_dist = {int(k): int(v) for k, v in zip(unique_classes, counts)}
    print("WorldCover 10m class distribution in viewshed box:", class_dist)

    tree_10m = (wc_arr == 10).astype(np.float32)
    # Reshape into (vs_rows, 3, vs_cols, 3) and average over the 3x3 10m pixels per 30m cell
    forest_fraction_vs = tree_10m.reshape(vs_rows, 3, vs_cols, 3).mean(axis=(1, 3)).astype(np.float32)
    forest_mask_vs = (forest_fraction_vs >= 0.5).astype(np.uint8)

    frac_vs_path = str(DERIVED_DIR / "forest_fraction_viewshed_30m_epsg3979.tif")
    mask_vs_path = str(DERIVED_DIR / "forest_mask_viewshed_30m_epsg3979.tif")
    write_geotiff(frac_vs_path, forest_fraction_vs, vs_gt, vs_wkt, gdal.GDT_Float32, nodata=-9999.0)
    write_geotiff(mask_vs_path, forest_mask_vs, vs_gt, vs_wkt, gdal.GDT_Byte, nodata=255)

    # Also extract/clip the exact core-box sub-window (snapped to the same 30m grid!)
    # Core box offset relative to viewshed box:
    # vs_col=36471, vs_row=124799; c_col=37278, c_row=125611
    c_col_off = 37278 - 36471  # 807
    c_row_off = 125611 - 124799  # 812
    c_cols = 735
    c_rows = 677

    forest_fraction_core = forest_fraction_vs[c_row_off : c_row_off + c_rows, c_col_off : c_col_off + c_cols]
    forest_mask_core = forest_mask_vs[c_row_off : c_row_off + c_rows, c_col_off : c_col_off + c_cols]

    dem_core_ds = gdal.Open(str(DERIVED_DIR / "dem_core_30m_epsg3979.tif"))
    core_gt = dem_core_ds.GetGeoTransform()
    core_wkt = dem_core_ds.GetProjection()

    frac_core_path = str(DERIVED_DIR / "forest_fraction_core_30m_epsg3979.tif")
    mask_core_path = str(DERIVED_DIR / "forest_mask_core_30m_epsg3979.tif")
    write_geotiff(frac_core_path, forest_fraction_core, core_gt, core_wkt, gdal.GDT_Float32, nodata=-9999.0)
    write_geotiff(mask_core_path, forest_mask_core, core_gt, core_wkt, gdal.GDT_Byte, nodata=255)

    # Report share of forested cells in each box
    vs_total_cells = int(forest_mask_vs.size)
    vs_forested_cells = int(np.sum(forest_mask_vs == 1))
    vs_forested_share = vs_forested_cells / vs_total_cells
    vs_mean_fraction = float(np.mean(forest_fraction_vs))

    core_total_cells = int(forest_mask_core.size)
    core_forested_cells = int(np.sum(forest_mask_core == 1))
    core_forested_share = core_forested_cells / core_total_cells
    core_mean_fraction = float(np.mean(forest_fraction_core))

    stats = {
        "source": "ESA WorldCover 10 m 2021 v200 (class 10 = Tree cover)",
        "viewshed_box": {
            "rows": vs_rows,
            "cols": vs_cols,
            "total_30m_cells": vs_total_cells,
            "forested_30m_cells_ge_0p5": vs_forested_cells,
            "forested_share_ge_0p5": vs_forested_share,
            "forested_pct_ge_0p5": round(vs_forested_share * 100.0, 2),
            "mean_tree_cover_fraction": vs_mean_fraction,
            "worldcover_10m_class_counts": class_dist,
        },
        "core_box": {
            "rows": c_rows,
            "cols": c_cols,
            "total_30m_cells": core_total_cells,
            "forested_30m_cells_ge_0p5": core_forested_cells,
            "forested_share_ge_0p5": core_forested_share,
            "forested_pct_ge_0p5": round(core_forested_share * 100.0, 2),
            "mean_tree_cover_fraction": core_mean_fraction,
        }
    }
    with open(DERIVED_DIR / "forest_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(f"\n=== Forest Cover Summary (ESA WorldCover 2021 v200, class 10 'Tree cover') ===")
    print(f"Viewshed Box (2342 x 2282 = {vs_total_cells:,} cells):")
    print(f"  Forested cells (fraction >= 0.5): {vs_forested_cells:,} / {vs_total_cells:,} = {vs_forested_share*100:.2f}% (mean tree fraction = {vs_mean_fraction*100:.2f}%)")
    print(f"Core Box (735 x 677 = {core_total_cells:,} cells):")
    print(f"  Forested cells (fraction >= 0.5): {core_forested_cells:,} / {core_total_cells:,} = {core_forested_share*100:.2f}% (mean tree fraction = {core_mean_fraction*100:.2f}%)")

if __name__ == "__main__":
    main()
