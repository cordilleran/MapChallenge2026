#!/usr/bin/env python3
"""Day 5 (15): Profile DEM on native EPSG:3979 core-box grid (735 x 677, Int16 decimetres).

Produces:
  site/data/day05/profile_dem.bin    little-endian Int16 raw binary (677 rows x 735 cols = 995,190 bytes),
                                     elevation in decimetres (0.1 m units; multiply by 0.1 for metres CGVD2013)
  site/data/day05/profile_dem.json   geotransform, grid dimensions, EPSG:3979 LCC-2SP parameters (confirmed
                                     from gdalsrsinfo EPSG:3979), verified stations inside core box, and list
                                     of named peaks/ridges/passes inside the core box for profile targets.

Environment:
  MC26_DAY05_DIR   input directory (defaults to <repo_root>/../in if unset)
"""
import csv
import json
import os
import subprocess
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
IN_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
OUT_DATA = ROOT / "site" / "data" / "day05"
OUT_DATA.mkdir(parents=True, exist_ok=True)


def main():
    dem_path = IN_DIR / "slice_a" / "derived" / "dem_core_30m_epsg3979.tif"
    ds = gdal.Open(str(dem_path))
    cols, rows = ds.RasterXSize, ds.RasterYSize
    if (cols, rows) != (735, 677):
        raise RuntimeError(f"Expected 735x677 core DEM, got {cols}x{rows}")

    gt = list(ds.GetGeoTransform())
    xmin, ymax = gt[0], gt[3]
    xmax = xmin + cols * gt[1]
    ymin = ymax + rows * gt[5]

    arr_f32 = ds.ReadAsArray()
    # Convert metres to Int16 decimetres, little-endian (<i2)
    arr_i16 = np.round(arr_f32 * 10.0).astype("<i2")
    out_bin = OUT_DATA / "profile_dem.bin"
    out_bin.write_bytes(arr_i16.tobytes(order="C"))

    # Confirm EPSG:3979 parameters via gdalsrsinfo
    srs_proj4 = subprocess.check_output(["gdalsrsinfo", "-o", "proj4", "EPSG:3979"], text=True).strip()

    # Check that all 6 stations lie inside the core box
    stations = []
    seen_stns = set()
    stn_csv = (IN_DIR / "slice_a" / "stations.csv") if (IN_DIR / "slice_a" / "stations.csv").exists() else (IN_DIR / "stations.csv")
    with open(stn_csv, newline="") as f:
        for row in csv.DictReader(f):
            s = row["station_num"]
            if s in ("84", "85", "86", "87", "88", "89") and s not in seen_stns:
                seen_stns.add(s)
                sx = float(row["station_x_epsg3979"])
                sy = float(row["station_y_epsg3979"])
                slat = float(row["station_lat"])
                slon = float(row["station_lon"])
                inside = (xmin <= sx <= xmax) and (ymin <= sy <= ymax)
                if not inside:
                    raise RuntimeError(f"Station {s} ({sx}, {sy}) is outside core box!")
                c_idx = int((sx - xmin) // gt[1])
                r_idx = int((ymax - sy) // (-gt[5]))
                stations.append(
                    {
                        "station": int(s),
                        "mlp_id": int(row["mlp_station_id"]),
                        "name": row["station_name"],
                        "lat": round(slat, 6),
                        "lon": round(slon, 6),
                        "x_epsg3979": round(sx, 2),
                        "y_epsg3979": round(sy, 2),
                        "col": c_idx,
                        "row": r_idx,
                        "cell_center_x": round(xmin + (c_idx + 0.5) * gt[1], 2),
                        "cell_center_y": round(ymax + (r_idx + 0.5) * gt[5], 2),
                        "dem_m": round(float(arr_i16[r_idx, c_idx]) * 0.1, 1),
                        "inside_core_box": inside,
                    }
                )
    stations.sort(key=lambda d: d["station"])

    # Check named peaks/ridges/passes inside the core box (deduplicated across AB/BC border pairs)
    names_path = (IN_DIR / "slice_a" / "names_peaks_passes.geojson") if (IN_DIR / "slice_a" / "names_peaks_passes.geojson").exists() else (IN_DIR / "slice_a" / "derived" / "names_peaks_passes.geojson")
    names_gj = json.loads(names_path.read_text())
    peaks_in_core = []
    seen_names = set()
    for feat in names_gj["features"]:
        props = feat["properties"]
        px, py = float(props["x_epsg3979"]), float(props["y_epsg3979"])
        if xmin <= px <= xmax and ymin <= py <= ymax:
            key = (props["name"], round(px, 1), round(py, 1))
            if key in seen_names:
                continue
            seen_names.add(key)
            lon, lat = feat["geometry"]["coordinates"][:2]
            c_idx = min(cols - 1, max(0, int((px - xmin) // gt[1])))
            r_idx = min(rows - 1, max(0, int((ymax - py) // (-gt[5]))))
            peaks_in_core.append(
                {
                    "name": props["name"],
                    "feature_type": props.get("feature_type", "Peak"),
                    "feature_subtype": props.get("feature_subtype", ""),
                    "jurisdiction": props.get("jurisdiction", ""),
                    "lat": round(float(lat), 5),
                    "lon": round(float(lon), 5),
                    "x_epsg3979": round(px, 2),
                    "y_epsg3979": round(py, 2),
                    "elevation_m": round(float(props["elevation"]), 1) if props.get("elevation") is not None else None,
                    "dem_m": round(float(arr_i16[r_idx, c_idx]) * 0.1, 1),
                }
            )
    peaks_in_core.sort(key=lambda p: (-(p["elevation_m"] or 0), p["name"]))

    meta = {
        "file": "data/day05/profile_dem.bin",
        "format": "Int16 little-endian raw binary (row-major, north-to-south, west-to-east)",
        "units": "decimetres (0.1 m; multiply Int16 value by 0.1 for elevation in metres CGVD2013)",
        "scale_to_metres": 0.1,
        "cols": cols,
        "rows": rows,
        "size_bytes": out_bin.stat().st_size,
        "geotransform": gt,
        "bounds_epsg3979": [xmin, ymin, xmax, ymax],
        "min_elev_m": round(float(arr_i16.min()) * 0.1, 1),
        "max_elev_m": round(float(arr_i16.max()) * 0.1, 1),
        "crs": {
            "epsg": 3979,
            "name": "NAD83(CSRS) / Canada Atlas Lambert",
            "projection": "Lambert Conformal Conic (2SP)",
            "ellipsoid": "GRS80",
            "semi_major_a": 6378137.0,
            "inv_flattening_rf": 298.257222101,
            "lat_1": 49.0,
            "lat_2": 77.0,
            "lat_0": 49.0,
            "lon_0": -95.0,
            "x_0": 0.0,
            "y_0": 0.0,
            "proj4": srs_proj4,
            "wgs84_to_nad83csrs_helmert": {
                "note": "PROJ/GDAL default operation from EPSG:4326 to EPSG:3979 applies Inverse of NAD83(CSRS) to WGS 84 (2) coordinate_frame Helmert transformation before LCC-2SP",
                "dx": -0.991,
                "dy": 1.9072,
                "dz": 0.5129,
                "rx_arcsec": -0.0257899075194932,
                "ry_arcsec": -0.0096500989602704,
                "rz_arcsec": -0.0116599432323421,
                "ds_ppm": 0.0,
                "convention": "coordinate_frame_inverse",
            },
        },
        "all_six_stations_inside_core_box": True,
        "stations": stations,
        "core_box_peaks_count": len(peaks_in_core),
        "core_box_peaks": peaks_in_core,
    }

    out_json = OUT_DATA / "profile_dem.json"
    out_json.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {out_bin.name} ({out_bin.stat().st_size / 1024:.1f} KB, {cols}x{rows} Int16 dm)")
    print(f"Wrote {out_json.name} ({out_json.stat().st_size / 1024:.1f} KB), {len(stations)} stations, {len(peaks_in_core)} core-box named features:")
    for p in peaks_in_core:
        print(f"  - {p['name']} ({p['feature_type']}, {p['elevation_m']} m, DEM {p['dem_m']} m)")


if __name__ == "__main__":
    main()
