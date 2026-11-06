#!/usr/bin/env python3
"""
Tasks 2 & 3:
- Clip NRCan MRDEM-30 DTM COG (https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif)
  WITHOUT resampling (native 30 m grid, using -srcwin pixel offsets) to:
  (i) viewshed box: envelope of 30 km buffers around all primary station points
  (ii) core box: lat 49.06 to 49.20, lon -114.20 to -113.95, enveloped in EPSG:3979 and snapped to the same grid.
  Write GeoTIFFs (deflate, tiled) and report rows, columns, min, max, and any nodata.
- Compute station_dem.csv for each primary station (and also include station-metadata / 2019 summit reference rows
  where the 2004/2003 GPS point differs by >1 cell, clearly flagged).

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
RAW_DIR = SLICE_A_DIR / "raw"
DERIVED_DIR = SLICE_A_DIR / "derived"

COG_URL = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif"
VSICURL_PATH = f"/vsicurl/{COG_URL}"

# Native MRDEM-30 grid parameters (verified from gdalinfo)
X0 = -2500020.0
Y0 = 4000020.0
DX = 30.0
DY = -30.0

def snap_box_to_grid(xmin, xmax, ymin, ymax):
    col_off = int(math.floor((xmin - X0) / 30.0))
    col_end = int(math.ceil((xmax - X0) / 30.0))
    row_off = int(math.floor((Y0 - ymax) / 30.0))
    row_end = int(math.ceil((Y0 - ymin) / 30.0))
    xsize = col_end - col_off
    ysize = row_end - row_off
    s_xmin = X0 + col_off * 30.0
    s_xmax = X0 + col_end * 30.0
    s_ymax = Y0 - row_off * 30.0
    s_ymin = Y0 - row_end * 30.0
    return col_off, row_off, xsize, ysize, (s_xmin, s_ymin, s_xmax, s_ymax)

def run_cmd(cmd):
    print("RUNNING:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def inspect_dem(tif_path):
    ds = gdal.Open(str(tif_path))
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()
    nd = band.GetNoDataValue()
    nodata_mask = (arr == nd) | np.isnan(arr)
    nodata_count = int(np.sum(nodata_mask))
    valid = arr[~nodata_mask]
    info = {
        "path": str(tif_path),
        "cols": ds.RasterXSize,
        "rows": ds.RasterYSize,
        "nodata_value": nd,
        "nodata_count": nodata_count,
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "geotransform": ds.GetGeoTransform(),
    }
    print(f"DEM Stats for {tif_path}: rows={info['rows']}, cols={info['cols']}, "
          f"min={info['min']:.2f} m, max={info['max']:.2f} m, nodata_count={info['nodata_count']} (nodata={nd})")
    return info, arr

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)

    # Read primary stations from stations.csv
    stations_path = DERIVED_DIR / "stations.csv"
    if not stations_path.exists():
        stations_path = SLICE_A_DIR / "stations.csv"

    primary_rows = []
    with open(stations_path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["use"] == "primary":
                primary_rows.append(r)

    xs = [float(r["x_epsg3979"]) for r in primary_rows]
    ys = [float(r["y_epsg3979"]) for r in primary_rows]

    # (i) Viewshed box: envelope of 30 km buffers around all primary station points
    vs_xmin_raw = min(xs) - 30000.0
    vs_xmax_raw = max(xs) + 30000.0
    vs_ymin_raw = min(ys) - 30000.0
    vs_ymax_raw = max(ys) + 30000.0
    vs_col, vs_row, vs_xsize, vs_ysize, vs_bounds = snap_box_to_grid(vs_xmin_raw, vs_xmax_raw, vs_ymin_raw, vs_ymax_raw)
    print(f"Viewshed box raw 30km buffer envelope: xmin={vs_xmin_raw:.2f}, ymin={vs_ymin_raw:.2f}, xmax={vs_xmax_raw:.2f}, ymax={vs_ymax_raw:.2f}")
    print(f"Viewshed box snapped (-srcwin {vs_col} {vs_row} {vs_xsize} {vs_ysize}): bounds={vs_bounds}")

    # (ii) Core box: lat 49.06 to 49.20, lon -114.20 to -113.95, enveloped in EPSG:3979 and snapped to the same grid
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    epsg3979 = osr.SpatialReference()
    epsg3979.ImportFromEPSG(3979)
    epsg3979.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tx = osr.CoordinateTransformation(wgs84, epsg3979)

    ring = ogr.Geometry(ogr.wkbLinearRing)
    for lon in [-114.20 + i * (0.25 / 200.0) for i in range(201)]:
        ring.AddPoint(lon, 49.06)
    for lat in [49.06 + i * (0.14 / 200.0) for i in range(201)]:
        ring.AddPoint(-113.95, lat)
    for lon in [-113.95 - i * (0.25 / 200.0) for i in range(201)]:
        ring.AddPoint(lon, 49.20)
    for lat in [49.20 - i * (0.14 / 200.0) for i in range(201)]:
        ring.AddPoint(-114.20, lat)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    poly.Transform(tx)
    c_xmin_raw, c_xmax_raw, c_ymin_raw, c_ymax_raw = poly.GetEnvelope()
    c_col, c_row, c_xsize, c_ysize, c_bounds = snap_box_to_grid(c_xmin_raw, c_xmax_raw, c_ymin_raw, c_ymax_raw)
    print(f"Core box raw envelope in EPSG:3979: xmin={c_xmin_raw:.2f}, ymin={c_ymin_raw:.2f}, xmax={c_xmax_raw:.2f}, ymax={c_ymax_raw:.2f}")
    print(f"Core box snapped (-srcwin {c_col} {c_row} {c_xsize} {c_ysize}): bounds={c_bounds}")

    # Clip viewshed DEM using gdal_translate -srcwin (no resampling, deflate, tiled)
    vs_dem_raw = str(RAW_DIR / "mrdem30_viewshed_raw.tif")
    vs_dem_derived = str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif")
    cmd_vs = [
        "gdal_translate",
        "-srcwin", str(vs_col), str(vs_row), str(vs_xsize), str(vs_ysize),
        "-co", "TILED=YES",
        "-co", "COMPRESS=DEFLATE",
        "-co", "PREDICTOR=3",
        VSICURL_PATH,
        vs_dem_derived,
    ]
    run_cmd(cmd_vs)
    # Also keep an untouched copy in raw/
    run_cmd(["cp", "-f", vs_dem_derived, vs_dem_raw])

    # Clip core DEM using gdal_translate -srcwin from the remote COG (or viewshed DEM, identical pixels)
    c_dem_derived = str(DERIVED_DIR / "dem_core_30m_epsg3979.tif")
    cmd_core = [
        "gdal_translate",
        "-srcwin", str(c_col), str(c_row), str(c_xsize), str(c_ysize),
        "-co", "TILED=YES",
        "-co", "COMPRESS=DEFLATE",
        "-co", "PREDICTOR=3",
        VSICURL_PATH,
        c_dem_derived,
    ]
    run_cmd(cmd_core)

    vs_info, vs_arr = inspect_dem(vs_dem_derived)
    c_info, c_arr = inspect_dem(c_dem_derived)

    # Save box metadata for downstream scripts
    boxes_meta = {
        "viewshed_box": {
            "srcwin": [vs_col, vs_row, vs_xsize, vs_ysize],
            "bounds_epsg3979": list(vs_bounds),
            "stats": vs_info,
        },
        "core_box": {
            "srcwin": [c_col, c_row, c_xsize, c_ysize],
            "bounds_epsg3979": list(c_bounds),
            "stats": c_info,
        }
    }
    with open(DERIVED_DIR / "boxes_meta.json", "w", encoding="utf-8") as f:
        json.dump(boxes_meta, f, indent=2)

    # Task 3: For each primary station: DEM value at station cell, 3x3 maximum and its offset in cells and metres, and 5x5 maximum.
    # Let's compute this from the viewshed DEM (and verify global col/row)
    vs_x0, _, _, vs_y0, _, _ = vs_info["geotransform"]

    dem_rows = []
    for r in primary_rows:
        x = float(r["x_epsg3979"])
        y = float(r["y_epsg3979"])
        c_idx = int(math.floor((x - vs_x0) / 30.0))
        r_idx = int(math.floor((vs_y0 - y) / 30.0))
        glob_col = vs_col + c_idx
        glob_row = vs_row + r_idx

        win5 = vs_arr[r_idx - 2 : r_idx + 3, c_idx - 2 : c_idx + 3]
        win3 = win5[1:4, 1:4]
        val_cell = float(win5[2, 2])
        max3 = float(np.max(win3))
        mr3, mc3 = divmod(int(np.argmax(win3)), 3)
        drow3 = mr3 - 1
        dcol3 = mc3 - 1
        dx3_m = dcol3 * 30.0
        dy3_m = -drow3 * 30.0  # North is +y (row decreases northward)
        dist3_m = math.hypot(dx3_m, dy3_m)

        max5 = float(np.max(win5))
        mr5, mc5 = divmod(int(np.argmax(win5)), 5)
        drow5 = mr5 - 2
        dcol5 = mc5 - 2
        dx5_m = dcol5 * 30.0
        dy5_m = -drow5 * 30.0
        dist5_m = math.hypot(dx5_m, dy5_m)

        # Also check station metadata coordinate (cairn / 2019 Loc 1) for comparison
        sx = float(r["station_x_epsg3979"])
        sy = float(r["station_y_epsg3979"])
        sc_idx = int(math.floor((sx - vs_x0) / 30.0))
        sr_idx = int(math.floor((vs_y0 - sy) / 30.0))
        swin5 = vs_arr[sr_idx - 2 : sr_idx + 3, sc_idx - 2 : sc_idx + 3]
        swin3 = swin5[1:4, 1:4]
        s_val_cell = float(swin5[2, 2])
        s_max3 = float(np.max(swin3))
        s_max5 = float(np.max(swin5))

        dem_rows.append({
            "station_num": r["station_num"],
            "mlp_station_id": r["mlp_station_id"],
            "station_name": r["station_name"],
            "primary_location_id": r["location_id"],
            "primary_visit_year": r["visit_year"],
            "lat": r["lat"],
            "lon": r["lon"],
            "x_epsg3979": r["x_epsg3979"],
            "y_epsg3979": r["y_epsg3979"],
            "recorded_elevation_m": r["recorded_elevation_m"],
            "dem_col_viewshed": c_idx,
            "dem_row_viewshed": r_idx,
            "dem_col_global": glob_col,
            "dem_row_global": glob_row,
            "dem_cell_m": f"{val_cell:.2f}",
            "max_3x3_m": f"{max3:.2f}",
            "max_3x3_dcol_cells": dcol3,
            "max_3x3_drow_cells": drow3,
            "max_3x3_dx_east_m": f"{dx3_m:.1f}",
            "max_3x3_dy_north_m": f"{dy3_m:.1f}",
            "max_3x3_dist_m": f"{dist3_m:.2f}",
            "max_5x5_m": f"{max5:.2f}",
            "max_5x5_dcol_cells": dcol5,
            "max_5x5_drow_cells": drow5,
            "max_5x5_dx_east_m": f"{dx5_m:.1f}",
            "max_5x5_dy_north_m": f"{dy5_m:.1f}",
            "max_5x5_dist_m": f"{dist5_m:.2f}",
            "station_meta_cell_m": f"{s_val_cell:.2f}",
            "station_meta_max_3x3_m": f"{s_max3:.2f}",
            "station_meta_max_5x5_m": f"{s_max5:.2f}",
        })

    for outpath in [DERIVED_DIR / "station_dem.csv", SLICE_A_DIR / "station_dem.csv"]:
        with open(outpath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(dem_rows[0].keys()))
            writer.writeheader()
            writer.writerows(dem_rows)
    print(f"Wrote station_dem.csv to {DERIVED_DIR / 'station_dem.csv'} and {SLICE_A_DIR / 'station_dem.csv'}")
    for dr in dem_rows:
        print(f"  Stn {dr['station_num']} ({dr['station_name']}): cell={dr['dem_cell_m']} m, "
              f"3x3_max={dr['max_3x3_m']} m (dcol={dr['max_3x3_dcol_cells']:+d}, drow={dr['max_3x3_drow_cells']:+d}, "
              f"dx={dr['max_3x3_dx_east_m']}m, dy={dr['max_3x3_dy_north_m']}m, dist={dr['max_3x3_dist_m']}m), "
              f"5x5_max={dr['max_5x5_m']} m | stn_meta_cell={dr['station_meta_cell_m']} m")

if __name__ == "__main__":
    main()
