#!/usr/bin/env python3
"""
Task 6: Names — peaks and passes inside the viewshed box from CGNDB (Canada) and GNIS (USA),
as GeoJSON with name, source, source id, and elevation if given.
- Filters points strictly inside the viewshed box in EPSG:3979:
  xmin=-1405890.0, ymin=187590.0, xmax=-1335630.0, ymax=256050.0.
- Samples elevation from dem_viewshed_30m_epsg3979.tif (MRDEM-30 CGVD2013) at each feature's coordinate,
  while explicitly noting that neither CGNDB nor US GNIS Layer 5 JSON schemas include a summit elevation field
  (and also attaches published OSM summit `ele` where available from recon_A.md).
- Verifies that all 11 required features (Mt Blakiston, Lost Mountain, Lone Mountain, Anderson Peak,
  Mt Hawkins, Mt Festubert / Festubert Mountain, Mt Lineham, Mt Rowe, Avion Ridge, Kishinena Peak, Sage Mountain)
  are present.

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import json
import math
import os
from pathlib import Path
from osgeo import gdal, osr

gdal.UseExceptions()
osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
RAW_DIR = SLICE_A_DIR / "raw"
DERIVED_DIR = SLICE_A_DIR / "derived"

VS_BOUNDS_3979 = (-1405890.0, 187590.0, -1335630.0, 256050.0)

# Published survey/topo summit elevations verified from OSM in recon_A.md (where available)
PUBLISHED_OSM_ELE_M = {
    "IAGYI": 2910,  # Mount Blakiston
    "IADWZ": 2423,  # Lone Mountain
    "IAEWC": 2512,  # Lost Mountain
    "IAIQZ": 2640,  # Mount Hawkins
    "IAEPQ": 2522,  # Festubert Mountain (AB)
    "JAVIY": 2522,  # Festubert Mountain (BC)
    "IABTD": 2652,  # Anderson Peak
    "IABFD": 2434,  # Kishinena Peak (AB)
    "JAIHZ": 2434,  # Kishinena Peak (BC)
    "IACLO": 2437,  # Avion Ridge
    "IADMY": 2377,  # Mount Bauerman
    "IAFTF": 2430,  # Ruby Ridge
    "IANDW": 2591,  # Cloudy Ridge
    "IAGNZ": 2673,  # Mount Glendowan
    "IANOW": 2621,  # Newman Peak
    "IAKPM": 2576,  # Spionkop Ridge
    "IACAQ": 2575,  # Mount Dungarvan
    # Mount Lineham (IADIS): OSM tag 2438 m dropped (D97); the DEM gives 2679.7 m at the CGNDB point.
    "IAGHB": 2368,  # Sage Mountain
}

CGNDB_GENERIC_TYPES = {
    "2701": ("Peak", "Mountain"),
    "2703": ("Peak", "Peak"),
    "2705": ("Peak", "Hill"),
    "2708": ("Peak", "Cliff / Bluff"),
    "2710": ("Ridge", "Ridge"),
    "2712": ("Peak", "Bluff"),
    "2716": ("Peak", "Butte"),
    "2743": ("Peak", "Mount"),
    "2913": ("Pass", "Pass"),
}

GNIS_ALLOWED_CLASSES = {
    "Summit": "Peak",
    "Ridge": "Ridge",
    "Gap": "Pass",
    "Pillar": "Peak",
}

def main():
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    epsg3979 = osr.SpatialReference()
    epsg3979.ImportFromEPSG(3979)
    epsg3979.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tx = osr.CoordinateTransformation(wgs84, epsg3979)

    dem_ds = gdal.Open(str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif"))
    dem_arr = dem_ds.GetRasterBand(1).ReadAsArray()
    x0, dx, _, y0, _, dy = dem_ds.GetGeoTransform()
    xmin, ymin, xmax, ymax = VS_BOUNDS_3979

    def sample_dem(x, y):
        col = int(math.floor((x - x0) / dx))
        row = int(math.floor((y0 - y) / (-dy)))
        if 0 <= row < dem_arr.shape[0] and 0 <= col < dem_arr.shape[1]:
            val = float(dem_arr[row, col])
            # Also get 3x3 max around the gazetteer point in case gazetteer arc-sec rounding is slightly off the ridge crest
            r0 = max(0, row - 1)
            r1 = min(dem_arr.shape[0], row + 2)
            c0 = max(0, col - 1)
            c1 = min(dem_arr.shape[1], col + 2)
            max3 = float(dem_arr[r0:r1, c0:c1].max())
            return round(val, 1), round(max3, 1)
        return None, None

    features = []

    # 1. Process CGNDB
    cg_items = json.load(open(RAW_DIR / "cgndb_viewshed_raw.json", "r", encoding="utf-8")).get("items", [])
    for it in cg_items:
        gcode = it.get("generic", {}).get("code")
        if gcode not in CGNDB_GENERIC_TYPES:
            continue
        lat = float(it["latitude"])
        lon = float(it["longitude"])
        x, y, _ = tx.TransformPoint(lon, lat)
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            continue
        f_cat, f_sub = CGNDB_GENERIC_TYPES[gcode]
        dem_ele, dem_max3 = sample_dem(x, y)
        cid = it["id"]
        osm_ele = PUBLISHED_OSM_ELE_M.get(cid)
        # Note: CGNDB API schema does not return an elevation attribute; we provide the MRDEM-30 elevation (and OSM ele if published)
        ele_val = osm_ele if osm_ele is not None else dem_ele

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(lon, 7), round(lat, 7)],
            },
            "properties": {
                "name": it["name"],
                "source": "CGNDB",
                "source_id": cid,
                "feature_type": f_cat,
                "feature_subtype": f_sub,
                "jurisdiction": "AB" if it.get("province", {}).get("code") == "48" else ("BC" if it.get("province", {}).get("code") == "59" else it.get("province", {}).get("code")),
                "elevation": ele_val,
                "elevation_source": "OpenStreetMap" if osm_ele is not None else "MRDEM-30",
                "elevation_source_api": None,
                "elevation_mrdem30_m": dem_ele,
                "elevation_mrdem30_3x3max_m": dem_max3,
                "elevation_osm_published_m": osm_ele,
                "x_epsg3979": round(x, 2),
                "y_epsg3979": round(y, 2),
            }
        })

    # 2. Process US GNIS Layer 5
    gnis_feats = json.load(open(RAW_DIR / "gnis_viewshed_raw.json", "r", encoding="utf-8")).get("features", [])
    seen_gaz_ids = set()
    for gf in gnis_feats:
        attrs = gf["attributes"]
        fclass = attrs.get("gaz_featureclass")
        if fclass not in GNIS_ALLOWED_CLASSES:
            continue
        gaz_id = str(attrs["gaz_id"])
        if gaz_id in seen_gaz_ids:
            continue
        pts = gf.get("geometry", {}).get("points", [])
        if not pts:
            continue
        lon, lat = float(pts[0][0]), float(pts[0][1])
        x, y, _ = tx.TransformPoint(lon, lat)
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            continue
        seen_gaz_ids.add(gaz_id)
        f_cat = GNIS_ALLOWED_CLASSES[fclass]
        dem_ele, dem_max3 = sample_dem(x, y)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(lon, 7), round(lat, 7)],
            },
            "properties": {
                "name": attrs["gaz_name"],
                "source": "GNIS",
                "source_id": gaz_id,
                "feature_type": f_cat,
                "feature_subtype": fclass,
                "jurisdiction": attrs.get("state_alpha", "MT"),
                "elevation": dem_ele,
                "elevation_source": "MRDEM-30",
                "elevation_source_api": None,
                "elevation_mrdem30_m": dem_ele,
                "elevation_mrdem30_3x3max_m": dem_max3,
                "elevation_osm_published_m": None,
                "x_epsg3979": round(x, 2),
                "y_epsg3979": round(y, 2),
            }
        })

    geojson_obj = {
        "type": "FeatureCollection",
        "name": "names_peaks_passes_viewshed",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    SLICE_A_DIR.mkdir(parents=True, exist_ok=True)
    for outpath in [DERIVED_DIR / "names_peaks_passes.geojson", SLICE_A_DIR / "names_peaks_passes.geojson"]:
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(geojson_obj, f, indent=2)

    # Check required 11 names
    required_targets = [
        ("Mt Blakiston", ["Mount Blakiston"]),
        ("Lost Mountain", ["Lost Mountain"]),
        ("Lone Mountain", ["Lone Mountain"]),
        ("Anderson Peak", ["Anderson Peak"]),
        ("Mt Hawkins", ["Mount Hawkins"]),
        ("Mt Festubert", ["Festubert Mountain"]),
        ("Mt Lineham", ["Mount Lineham"]),
        ("Mt Rowe", ["Mount Rowe"]),
        ("Avion Ridge", ["Avion Ridge"]),
        ("Kishinena Peak", ["Kishinena Peak"]),
        ("Sage Mountain", ["Sage Mountain"]),
    ]

    cg_cnt = sum(1 for f in features if f["properties"]["source"] == "CGNDB")
    gn_cnt = sum(1 for f in features if f["properties"]["source"] == "GNIS")
    print(f"Wrote {len(features)} features ({cg_cnt} CGNDB, {gn_cnt} GNIS) to {DERIVED_DIR / 'names_peaks_passes.geojson'}")

    for req_label, match_names in required_targets:
        matches = [f for f in features if f["properties"]["name"] in match_names]
        if matches:
            m = matches[0]["properties"]
            print(f"  [OK] {req_label:16s} -> '{m['name']}' ({m['source']}:{m['source_id']}, ele={m['elevation']}m, dem={m['elevation_mrdem30_m']}m)")
        else:
            print(f"  [MISSING!] {req_label}")

if __name__ == "__main__":
    main()
