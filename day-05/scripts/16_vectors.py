#!/usr/bin/env python3
"""Day 5 (16): Context vectors as one compact GeoJSON (EPSG:4326, 5-decimal coords, < 400 KB).

Includes in a single GeoJSON FeatureCollection (tagged by properties.layer):
  - park_boundary: Waterton Lakes National Park boundary
  - parkway: Red Rock Parkway
  - trail: trails and alpine routes in the core box
  - kenow_fire: 2017 Kenow Fire perimeter
  - station: the six 1914 Bridgland survey stations (main positions, names, MLP IDs)
  - peak: named peaks, ridges and passes inside the viewshed box (with in_core flag)

Also writes a small JSON fixture of 20 random station-to-core-box profile test cases
(site/data/day05/los_test_cases.json or day-05/tests/los_test_cases.json) sampled from
vs_<stn>_main.tif for the Node.js line-of-sight verification test.

Environment:
  MC26_DAY05_DIR   input directory (defaults to <repo_root>/../in if unset)
"""
import csv
import json
import math
import os
import random
from pathlib import Path

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
IN_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
OUT_DATA = ROOT / "site" / "data" / "day05"
OUT_TESTS = ROOT / "day-05" / "tests"
OUT_DATA.mkdir(parents=True, exist_ok=True)
OUT_TESTS.mkdir(parents=True, exist_ok=True)


def round_coords(coords, decimals=5):
    """Recursively round GeoJSON coordinate arrays to `decimals` places and drop consecutive duplicates."""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [round(float(coords[0]), decimals), round(float(coords[1]), decimals)]
    out = []
    for c in coords:
        rc = round_coords(c, decimals)
        if not rc:
            continue
        if isinstance(rc[0], (int, float)):
            if not out or out[-1] != rc:
                out.append(rc)
        else:
            out.append(rc)
    return out


def simplify_geojson_geom(geom_dict, tol, min_ring_pts=4):
    """Simplify an OGR geometry in EPSG:4326 with Douglas-Peucker and round coordinates to 5 decimals."""
    if tol <= 0 or geom_dict["type"] == "Point":
        return {"type": geom_dict["type"], "coordinates": round_coords(geom_dict["coordinates"], 5)}
    og = ogr.CreateGeometryFromJson(json.dumps(geom_dict))
    sg = og.SimplifyPreserveTopology(tol)
    res = json.loads(sg.ExportToJson())
    rc = round_coords(res["coordinates"], 5)
    if res["type"] == "Polygon":
        rc = [ring for ring in rc if len(ring) >= min_ring_pts]
    elif res["type"] == "MultiPolygon":
        polys = []
        for poly in rc:
            rings = [ring for ring in poly if len(ring) >= min_ring_pts]
            if rings:
                polys.append(rings)
        rc = polys
    elif res["type"] == "LineString":
        if len(rc) < 2:
            rc = round_coords(geom_dict["coordinates"], 5)
    return {"type": res["type"], "coordinates": rc}


def main():
    slice_a = IN_DIR / "slice_a"
    boxes = json.loads((slice_a / "derived" / "boxes_meta.json").read_text())
    c_xmin, c_ymin, c_xmax, c_ymax = boxes["core_box"]["bounds_epsg3979"]

    features = []

    # 1. Park boundary
    park_gj = json.loads((slice_a / "waterton_lakes_np_boundary.geojson").read_text())
    for feat in park_gj["features"]:
        p = feat.get("properties", {})
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "layer": "park_boundary",
                    "name": p.get("name", "Waterton Lakes National Park"),
                },
                "geometry": simplify_geojson_geom(feat["geometry"], tol=0.00025),
            }
        )

    # 2. Red Rock Parkway
    rrp_gj = json.loads((slice_a / "red_rock_parkway.geojson").read_text())
    for feat in rrp_gj["features"]:
        p = feat.get("properties", {})
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "layer": "parkway",
                    "name": p.get("name", "Red Rock Parkway"),
                },
                "geometry": simplify_geojson_geom(feat["geometry"], tol=0.00008),
            }
        )

    # 3. Trails (core box)
    trails_gj = json.loads((slice_a / "trails_core.geojson").read_text())
    for feat in trails_gj["features"]:
        p = feat.get("properties", {})
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "layer": "trail",
                    "name": p.get("name") or "Trail",
                    "highway": p.get("highway", "path"),
                },
                "geometry": simplify_geojson_geom(feat["geometry"], tol=0.00012),
            }
        )

    # 4. Kenow 2017 fire perimeter
    kenow_gj = json.loads((slice_a / "kenow_fire_2017_perimeter.geojson").read_text())
    for feat in kenow_gj["features"]:
        p = feat.get("properties", {})
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "layer": "kenow_fire",
                    "name": p.get("fire_name", "Kenow Fire (2017)"),
                    "admin_area": p.get("admin_area", ""),
                    "poly_ha": round(float(p["poly_ha"]), 1) if p.get("poly_ha") else None,
                },
                "geometry": simplify_geojson_geom(feat["geometry"], tol=0.00045),
            }
        )

    # 5. Six stations (main positions, names, MLP IDs)
    det_metrics = json.loads((IN_DIR / "viewsheds" / "deterministic_metrics.json").read_text())
    seen_stns = set()
    stn_csv = (slice_a / "stations.csv") if (slice_a / "stations.csv").exists() else (IN_DIR / "stations.csv")
    with open(stn_csv, newline="") as f:
        for row in csv.DictReader(f):
            s = row["station_num"]
            if s in ("84", "85", "86", "87", "88", "89") and s not in seen_stns:
                seen_stns.add(s)
                slat = round(float(row["station_lat"]), 5)
                slon = round(float(row["station_lon"]), 5)
                sx = round(float(row["station_x_epsg3979"]), 2)
                sy = round(float(row["station_y_epsg3979"]), 2)
                sm = det_metrics["stations"][s]
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "layer": "station",
                            "station": int(s),
                            "mlp_id": int(row["mlp_station_id"]),
                            "name": row["station_name"],
                            "x_epsg3979": sx,
                            "y_epsg3979": sy,
                            "dem_m": sm["dem_m"],
                            "max_3x3_m": sm["max_3x3_m"],
                            "main_visible_area_km2": round(sm["main_visible_area_km2"], 2),
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [slon, slat],
                        },
                    }
                )

    # 6. Named peaks/ridges/passes inside the viewshed box (deduplicated across AB/BC border pairs)
    names_gj = json.loads((slice_a / "names_peaks_passes.geojson").read_text())
    seen_peaks = set()
    for feat in names_gj["features"]:
        p = feat.get("properties", {})
        px, py = float(p["x_epsg3979"]), float(p["y_epsg3979"])
        key = (p["name"], round(px, 1), round(py, 1))
        if key in seen_peaks:
            continue
        seen_peaks.add(key)
        in_core = (c_xmin <= px <= c_xmax) and (c_ymin <= py <= c_ymax)
        lon, lat = feat["geometry"]["coordinates"][:2]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "layer": "peak",
                    "name": p["name"],
                    "feature_type": p.get("feature_type", "Peak"),
                    "jurisdiction": p.get("jurisdiction", ""),
                    "elevation_m": round(float(p["elevation"]), 1) if p.get("elevation") is not None else None,
                    "dem_m": round(float(p["elevation_mrdem30_m"]), 1) if p.get("elevation_mrdem30_m") is not None else None,
                    "elevation_source": p.get("elevation_source", "MRDEM-30"),
                    "x_epsg3979": round(px, 2),
                    "y_epsg3979": round(py, 2),
                    "in_core": in_core,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(lon), 5), round(float(lat), 5)],
                },
            }
        )

    fc = {
        "type": "FeatureCollection",
        "name": "day05_vectors",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    out_geojson = OUT_DATA / "vectors.geojson"
    out_geojson.write_text(json.dumps(fc, separators=(",", ":")) + "\n")
    sz_kb = out_geojson.stat().st_size / 1024.0
    print(f"Wrote {out_geojson.name}: {len(features)} features, {sz_kb:.1f} KB (limit 400 KB)")
    if sz_kb >= 400.0:
        raise RuntimeError(f"vectors.geojson is {sz_kb:.1f} KB, exceeds 400 KB limit!")

    # 7. Extract 20 random station-to-core-box points and their vs_<stn>_main.tif values for Test (b)
    ds_core = gdal.Open(str(slice_a / "derived" / "dem_core_30m_epsg3979.tif"))
    gt_core = ds_core.GetGeoTransform()
    c_cols, c_rows = ds_core.RasterXSize, ds_core.RasterYSize

    ds_vs0 = gdal.Open(str(IN_DIR / "viewsheds" / "vs_84_main.tif"))
    gt_vs = ds_vs0.GetGeoTransform()
    vs_arrays = {
        s: gdal.Open(str(IN_DIR / "viewsheds" / f"vs_{s}_main.tif")).ReadAsArray()
        for s in ("84", "85", "86", "87", "88", "89")
    }

    stn_coords = {
        str(f["properties"]["station"]): (f["properties"]["x_epsg3979"], f["properties"]["y_epsg3979"], f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
        for f in features
        if f["properties"]["layer"] == "station"
    }

    rng = random.Random(20261105)
    test_cases = []
    stn_keys = sorted(stn_coords.keys())
    for i in range(20):
        s = stn_keys[i % len(stn_keys)]
        sx, sy, slat, slon = stn_coords[s]
        # Random cell center inside the core box (with 5-cell margin from edge)
        col = rng.randint(5, c_cols - 6)
        row = rng.randint(5, c_rows - 6)
        tx = gt_core[0] + (col + 0.5) * gt_core[1]
        ty = gt_core[3] + (row + 0.5) * gt_core[5]
        # Corresponding cell in viewshed raster
        v_col = int(math.floor((tx - gt_vs[0]) / gt_vs[1]))
        v_row = int(math.floor((ty - gt_vs[3]) / gt_vs[5]))
        vs_val = int(vs_arrays[s][v_row, v_col])
        test_cases.append(
            {
                "id": i + 1,
                "station": int(s),
                "station_x": sx,
                "station_y": sy,
                "station_lat": slat,
                "station_lon": slon,
                "target_col_core": col,
                "target_row_core": row,
                "target_x": round(tx, 2),
                "target_y": round(ty, 2),
                "vs_main_visible": bool(vs_val > 0),
                "vs_main_raw": vs_val,
            }
        )

    out_test_json = OUT_TESTS / "los_sampled_20.json"
    out_test_json.write_text(json.dumps({"seed": 20261105, "cases": test_cases}, indent=2) + "\n")
    print(f"Wrote {out_test_json.name} with {len(test_cases)} sampled viewshed test cases")


if __name__ == "__main__":
    main()
