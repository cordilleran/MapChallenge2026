#!/usr/bin/env python3
"""Day 5 (14): Viewshed rasters on a single EPSG:3857 grid for in-browser toggling.

Produces:
  1. Bit-packed scenario PNGs (8-bit greyscale, nearest-neighbour from EPSG:3979):
     bit i (0..5) is set if station i in [84, 85, 86, 87, 88, 89] sees the cell:
       site/img/day05/vs_pack_main.png
       site/img/day05/vs_pack_forest10.png
       site/img/day05/vs_pack_forest20.png
       site/img/day05/vs_pack_forest30.png
       site/img/day05/vs_pack_drone.png
  2. Probable viewsheds (0..100 percentage, 8-bit greyscale PNG on the same 3857 grid):
       site/img/day05/prob_<stn>_rmse26.png  (RMSE 2.6 m, from viewsheds/prob_<stn>.tif)
       site/img/day05/prob_<stn>_rmse80.png  (RMSE 8.0 m, from viewsheds_rmse8/prob_<stn>.tif)
  3. Position uncertainty (count of variants seeing each cell, 8-bit greyscale PNG on the same 3857 grid):
       site/img/day05/vs_<stn>_unc.png
  4. Metadata & variant tables:
       site/data/day05/viewsheds_index.json  bounds, grid size, station bit order, scenario and file index, probable metrics
       site/data/day05/variants.json         station, variant_id, abs_observer_height, visible_area_km2, jaccard_main, etc.

Environment:
  MC26_DAY05_DIR   input directory (defaults to <repo_root>/../in if unset)
"""
import csv
import json
import math
import os
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from PIL import Image

gdal.UseExceptions()
osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
IN_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()

OUT_IMG = ROOT / "site" / "img" / "day05"
OUT_DATA = ROOT / "site" / "data" / "day05"
OUT_IMG.mkdir(parents=True, exist_ok=True)
OUT_DATA.mkdir(parents=True, exist_ok=True)

STATIONS = ["84", "85", "86", "87", "88", "89"]
SCENARIOS = ["main", "forest10", "forest20", "forest30", "drone"]
TR_3857 = 50.0  # matches 01_base_overlays.py viewshed grid (2666 x 2638, ~32.7 m ground resolution)


def warp_nearest_3857(tif_path):
    """Warp an EPSG:3979 viewshed raster to the standard EPSG:3857 grid using nearest neighbour."""
    ds = gdal.Warp(
        "",
        str(tif_path),
        format="MEM",
        dstSRS="EPSG:3857",
        xRes=TR_3857,
        yRes=TR_3857,
        resampleAlg="near",
        srcNodata=0,
        dstNodata=0,
    )
    return ds


def save_grey_png(arr_u8, out_path):
    img = Image.fromarray(arr_u8, mode="L")
    img.save(out_path, "PNG", optimize=True, compress_level=9)
    return out_path.stat().st_size


def mercator_bounds_to_latlon(xmin, ymin, xmax, ymax):
    s3857 = osr.SpatialReference()
    s3857.ImportFromEPSG(3857)
    s4326 = osr.SpatialReference()
    s4326.ImportFromEPSG(4326)
    s4326.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(s3857, s4326)
    west, south, _ = tr.TransformPoint(xmin, ymin)
    east, north, _ = tr.TransformPoint(xmax, ymax)
    return [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]]


def main():
    vs_dir = IN_DIR / "viewsheds"
    vs_rmse8_dir = IN_DIR / "viewsheds_rmse8"

    grid_w = grid_h = None
    gt_3857 = None
    bounds_3857 = None
    bounds_ll = None

    packed_files = {}
    for scen in SCENARIOS:
        packed = None
        for bit_idx, stn in enumerate(STATIONS):
            tif = vs_dir / f"vs_{stn}_{scen}.tif"
            ds = warp_nearest_3857(tif)
            if grid_w is None:
                grid_w, grid_h = ds.RasterXSize, ds.RasterYSize
                gt_3857 = ds.GetGeoTransform()
                xmin, ymax = gt_3857[0], gt_3857[3]
                xmax = xmin + grid_w * gt_3857[1]
                ymin = ymax + grid_h * gt_3857[5]
                bounds_3857 = [round(xmin, 2), round(ymin, 2), round(xmax, 2), round(ymax, 2)]
                bounds_ll = mercator_bounds_to_latlon(xmin, ymin, xmax, ymax)
            arr = ds.ReadAsArray()
            if packed is None:
                packed = np.zeros((grid_h, grid_w), dtype=np.uint8)
            packed |= ((arr > 0).astype(np.uint8) << bit_idx)

        out_png = OUT_IMG / f"vs_pack_{scen}.png"
        sz = save_grey_png(packed, out_png)
        packed_files[scen] = {
            "url": f"img/day05/{out_png.name}",
            "size_bytes": sz,
            "any_visible_px_3857": int((packed > 0).sum()),
        }
        print(f"Packed {out_png.name}: {grid_w}x{grid_h}, {sz / 1024:.1f} KB")

    # Probable viewsheds (RMSE 2.6 m and RMSE 8.0 m)
    prob_files = {"rmse26": {}, "rmse80": {}}
    for stn in STATIONS:
        ds26 = warp_nearest_3857(vs_dir / f"prob_{stn}.tif")
        arr26 = ds26.ReadAsArray().astype(np.uint8)
        out26 = OUT_IMG / f"prob_{stn}_rmse26.png"
        sz26 = save_grey_png(arr26, out26)
        prob_files["rmse26"][stn] = {"url": f"img/day05/{out26.name}", "size_bytes": sz26}

        ds80 = warp_nearest_3857(vs_rmse8_dir / f"prob_{stn}.tif")
        arr80 = ds80.ReadAsArray().astype(np.uint8)
        out80 = OUT_IMG / f"prob_{stn}_rmse80.png"
        sz80 = save_grey_png(arr80, out80)
        prob_files["rmse80"][stn] = {"url": f"img/day05/{out80.name}", "size_bytes": sz80}
        print(f"Probable stn {stn}: rmse26={sz26/1024:.1f} KB, rmse80={sz80/1024:.1f} KB")

    # Position uncertainty rasters (vs_<stn>_unc.tif)
    unc_files = {}
    for stn in STATIONS:
        ds_u = warp_nearest_3857(vs_dir / f"vs_{stn}_unc.tif")
        arr_u = ds_u.ReadAsArray().astype(np.uint8)
        out_u = OUT_IMG / f"vs_{stn}_unc.png"
        sz_u = save_grey_png(arr_u, out_u)
        unc_files[stn] = {
            "url": f"img/day05/{out_u.name}",
            "size_bytes": sz_u,
            "max_count": int(arr_u.max()),
        }
        print(f"Uncertainty stn {stn}: {out_u.name} (max={arr_u.max()}), {sz_u/1024:.1f} KB")

    # Variant table JSON (from deterministic_metrics.json and variants.csv)
    det_metrics = json.loads((vs_dir / "deterministic_metrics.json").read_text())
    prob26_metrics = json.loads((vs_dir / "probable_metrics.json").read_text())
    prob80_metrics = json.loads((vs_rmse8_dir / "probable_metrics.json").read_text())

    variants_list = []
    with open(vs_dir / "variants.csv", newline="") as f:
        for row in csv.DictReader(f):
            stn = str(row["station"])
            vid = row["variant_id"]
            cells = int(row["visible_cell_count"])
            area_km2 = round(cells * 0.0009, 4)
            # Lookup notes and variant_type from deterministic_metrics.json if available
            v_meta = next(
                (v for v in det_metrics["stations"].get(stn, {}).get("variants", []) if v["variant_id"] == vid),
                {},
            )
            variants_list.append(
                {
                    "station": int(stn),
                    "variant_id": vid,
                    "variant_type": v_meta.get("variant_type", ""),
                    "x_epsg3979": round(float(row["x"]), 2),
                    "y_epsg3979": round(float(row["y"]), 2),
                    "dem_m": round(float(row["dem_value"]), 2),
                    "abs_observer_height": round(float(row["abs_observer_height"]), 2),
                    "visible_cell_count": cells,
                    "visible_area_km2": area_km2,
                    "jaccard_main": round(float(row["jaccard_main"]), 6),
                    "notes": v_meta.get("notes", ""),
                }
            )

    variants_out = {
        "note": "Position and observer-height variants for the six 1914 Bridgland stations (30 m MRDEM-30 grid, EPSG:3979, 0.0009 km2/cell).",
        "stations_num_variants": {stn: det_metrics["stations"][stn]["num_variants"] for stn in STATIONS},
        "variants": variants_list,
    }
    out_variants_json = OUT_DATA / "variants.json"
    out_variants_json.write_text(json.dumps(variants_out, indent=2) + "\n")

    # Summary station metrics for index JSON
    station_summaries = {}
    for bit_idx, stn in enumerate(STATIONS):
        sm = det_metrics["stations"][stn]
        p26 = prob26_metrics["stations"][stn]
        p80 = prob80_metrics["stations"][stn]
        station_summaries[stn] = {
            "station": int(stn),
            "bit": bit_idx,
            "mask": 1 << bit_idx,
            "station_name": sm["station_name"],
            "mlp_station_id": int(sm["mlp_station_id"]),
            "x_epsg3979": sm["x"],
            "y_epsg3979": sm["y"],
            "dem_m": sm["dem_m"],
            "max_3x3_m": sm["max_3x3_m"],
            "num_variants": sm["num_variants"],
            "area_km2": {
                "main": round(sm["main_visible_area_km2"], 2),
                "forest10": round(sm["forest"]["10"]["visible_area_km2"], 2),
                "forest20": round(sm["forest"]["20"]["visible_area_km2"], 2),
                "forest30": round(sm["forest"]["30"]["visible_area_km2"], 2),
                "drone": round(sm["drone_visible_area_km2"], 2),
                "prob_rmse26_expected": round(p26["expected_visible_area_km2"], 2),
                "prob_rmse26_p50": round(p26["area_prob_ge_50_km2"], 2),
                "prob_rmse26_p90": round(p26["area_prob_ge_90_km2"], 2),
                "prob_rmse80_expected": round(p80["expected_visible_area_km2"], 2),
                "prob_rmse80_p50": round(p80["area_prob_ge_50_km2"], 2),
                "prob_rmse80_p90": round(p80["area_prob_ge_90_km2"], 2),
            },
        }

    cos_lat = math.cos(math.radians(49.13))
    index_data = {
        "crs": "EPSG:3857",
        "bounds_crs": "EPSG:4326",
        "width": grid_w,
        "height": grid_h,
        "mercator_res_m": TR_3857,
        "ground_res_approx_m": round(TR_3857 * cos_lat, 2),
        "geotransform_3857": [round(x, 4) for x in gt_3857],
        "bounds_3857": bounds_3857,
        "bounds": bounds_ll,
        "station_order": [int(s) for s in STATIONS],
        "bit_packing": "bit i (0..5) is (1 << i) for station_order[i] in [84, 85, 86, 87, 88, 89]",
        "scenarios": packed_files,
        "probable": {
            "rmse26": {
                "rmse_m": 2.6,
                "corr_len_m": 150.0,
                "n_runs": 50,
                "files": prob_files["rmse26"],
            },
            "rmse80": {
                "rmse_m": 8.0,
                "corr_len_m": 150.0,
                "n_runs": 50,
                "files": prob_files["rmse80"],
            },
        },
        "uncertainty": unc_files,
        "stations": station_summaries,
    }
    out_index_json = OUT_DATA / "viewsheds_index.json"
    out_index_json.write_text(json.dumps(index_data, indent=2) + "\n")
    print(f"Wrote {out_variants_json.name} ({out_variants_json.stat().st_size} B) and {out_index_json.name} ({out_index_json.stat().st_size} B)")


if __name__ == "__main__":
    main()
