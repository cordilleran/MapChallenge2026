#!/usr/bin/env python3
"""
Task 7: Vectors (GeoJSON, EPSG:4326):
1. Waterton Lakes National Park boundary (CGNDB IATZN & Alberta Parks Titan MapServer Layer 14)
2. Red Rock Parkway (OSM API v0.6 small-bbox sweep of Core Box)
3. Trails in the core box (OSM API v0.6 small-bbox sweep of Core Box)
4. 2017 Kenow fire perimeter (CWFIS NBAC WFS `year=2017 AND nfireid=2418`)

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import json
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
RAW_DIR = SLICE_A_DIR / "raw"
DERIVED_DIR = SLICE_A_DIR / "derived"

HEADERS = {"User-Agent": "Mozilla/5.0 (MapChallenge Day5 DataFetch/1.0)"}

def fetch_json(url, out_raw_path):
    print(f"Fetching {url} -> {out_raw_path}")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw_bytes = resp.read()
    with open(out_raw_path, "wb") as f:
        f.write(raw_bytes)
    return json.loads(raw_bytes.decode("utf-8"))

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    SLICE_A_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Waterton Lakes National Park boundary
    # Fetch both CGNDB IATZN.geojson and Alberta Titan MapServer Layer 14 GeoJSON
    wlnp_cgndb_url = "https://geogratis.gc.ca/services/geoname/en/geonames/IATZN.geojson"
    wlnp_titan_url = (
        "https://geospatial.alberta.ca/titan/rest/services/environment/"
        "parks_and_protected_areas_of_alberta_10tm_nad83_aep/MapServer/14/query"
        "?where=NAME%3D%27Waterton%20Lakes%27&outFields=*&outSR=4326&f=geojson"
    )
    cgndb_wlnp = fetch_json(wlnp_cgndb_url, RAW_DIR / "waterton_np_cgndb_IATZN.geojson")
    titan_wlnp = fetch_json(wlnp_titan_url, RAW_DIR / "waterton_np_alberta_titan.geojson")

    # Use the official high-resolution polygon from Alberta Titan / Parks Canada (with CGNDB metadata attached)
    wlnp_features = titan_wlnp.get("features", [])
    for feat in wlnp_features:
        props = feat.get("properties", {})
        props["cgndb_id"] = "IATZN"
        props["source"] = "Alberta Parks & Protected Areas MapServer (Layer 14) / CGNDB IATZN"
        props["licence"] = "Open Government Licence - Alberta / Open Government Licence - Canada"
    wlnp_out = {
        "type": "FeatureCollection",
        "name": "waterton_lakes_np_boundary",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": wlnp_features,
    }
    for p in [DERIVED_DIR / "waterton_lakes_np_boundary.geojson", SLICE_A_DIR / "waterton_lakes_np_boundary.geojson"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(wlnp_out, f, indent=2)
    print(f"Wrote Waterton Lakes NP boundary ({len(wlnp_features)} feature(s))")

    # 2. 2017 Kenow Fire Perimeter (NRCan CWFIS NBAC WFS)
    kenow_url = (
        "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs?service=WFS&version=2.0.0"
        "&request=GetFeature&typeNames=public:nbac&cql_filter=year=2017%20AND%20nfireid=2418"
        "&outputFormat=application/json&srsName=urn:ogc:def:crs:EPSG::4326"
    )
    kenow_raw = fetch_json(kenow_url, RAW_DIR / "kenow_fire_2017_nbac_raw.geojson")
    # Ensure coordinates are in standard GeoJSON [lon, lat] order (check first coordinate)
    def ensure_lon_lat(coords):
        if isinstance(coords[0], (int, float)):
            x, y = coords[0], coords[1]
            if 45.0 <= x <= 55.0 and -120.0 <= y <= -110.0:
                return [round(y, 7), round(x, 7)]
            return [round(x, 7), round(y, 7)]
        return [ensure_lon_lat(c) for c in coords]

    kenow_features = []
    total_ha = 0.0
    for feat in kenow_raw.get("features", []):
        geom = feat["geometry"]
        geom["coordinates"] = ensure_lon_lat(geom["coordinates"])
        props = feat.get("properties", {})
        props["fire_name"] = "Kenow Fire (2017)"
        props["source"] = "NRCan CWFIS National Burned Area Composite (public:nbac)"
        total_ha += float(props.get("poly_ha", 0.0))
        kenow_features.append({
            "type": "Feature",
            "id": feat.get("id"),
            "geometry": geom,
            "properties": props,
        })
    kenow_out = {
        "type": "FeatureCollection",
        "name": "kenow_fire_2017_perimeter",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": kenow_features,
    }
    for p in [DERIVED_DIR / "kenow_fire_2017_perimeter.geojson", SLICE_A_DIR / "kenow_fire_2017_perimeter.geojson"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(kenow_out, f, indent=2)
    print(f"Wrote 2017 Kenow Fire perimeter ({len(kenow_features)} polygons, total poly_ha={total_ha:.1f} ha)")

    # 3. OSM API v0.6 4-quadrant sweep of the Core Box (lon -114.20 to -113.95, lat 49.06 to 49.20)
    quadrants = [
        ("sw", -114.20, 49.06, -114.075, 49.13),
        ("se", -114.075, 49.06, -113.95, 49.13),
        ("nw", -114.20, 49.13, -114.075, 49.20),
        ("ne", -114.075, 49.13, -113.95, 49.20),
    ]
    nodes = {}
    ways = {}
    relations = {}

    for qname, minlon, minlat, maxlon, maxlat in quadrants:
        osm_url = f"https://api.openstreetmap.org/api/0.6/map.json?bbox={minlon},{minlat},{maxlon},{maxlat}"
        qdata = fetch_json(osm_url, RAW_DIR / f"osm_core_{qname}.json")
        for el in qdata.get("elements", []):
            etype = el.get("type")
            eid = el.get("id")
            if etype == "node":
                nodes[eid] = (el["lon"], el["lat"], el.get("tags", {}))
            elif etype == "way":
                ways[eid] = el
            elif etype == "relation":
                relations[eid] = el

    print(f"OSM Core Box sweep merged: {len(nodes)} unique nodes, {len(ways)} unique ways, {len(relations)} unique relations")

    # Map way_id -> route relation names (e.g. Great Divide Trail, Anderson Peak Route, Blakiston Falls Trail)
    way_route_names = {}
    for rid, rel in relations.items():
        rtags = rel.get("tags", {})
        if rtags.get("type") == "route" and rtags.get("name"):
            rname = rtags["name"]
            for mem in rel.get("members", []):
                if mem.get("type") == "way":
                    way_route_names.setdefault(mem["ref"], []).append(rname)

    red_rock_features = []
    trail_features = []

    for wid, w in sorted(ways.items()):
        tags = w.get("tags", {})
        hw = tags.get("highway")
        if not hw:
            continue
        nd_ids = w.get("nodes", [])
        coords = [[round(nodes[nid][0], 7), round(nodes[nid][1], 7)] for nid in nd_ids if nid in nodes]
        if len(coords) < 2:
            continue

        name = tags.get("name", "")
        route_names = way_route_names.get(wid, [])
        if not name and route_names:
            name = " / ".join(sorted(set(route_names)))

        # Red Rock Parkway
        if "red rock parkway" in name.lower():
            red_rock_features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "osm_id": f"way/{wid}",
                    "name": name,
                    "highway": hw,
                    "surface": tags.get("surface"),
                    "source": "OpenStreetMap API v0.6",
                }
            })

        # Trails in the core box (path, footway, track, bridleway, steps)
        if hw in ("path", "footway", "track", "bridleway", "steps"):
            trail_features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "osm_id": f"way/{wid}",
                    "name": name if name else None,
                    "route_relations": ", ".join(sorted(set(route_names))) if route_names else None,
                    "highway": hw,
                    "sac_scale": tags.get("sac_scale"),
                    "trail_visibility": tags.get("trail_visibility"),
                    "surface": tags.get("surface"),
                    "operator": tags.get("operator"),
                    "source": "OpenStreetMap API v0.6",
                }
            })

    rr_out = {
        "type": "FeatureCollection",
        "name": "red_rock_parkway",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": red_rock_features,
    }
    for p in [DERIVED_DIR / "red_rock_parkway.geojson", SLICE_A_DIR / "red_rock_parkway.geojson"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rr_out, f, indent=2)

    trails_out = {
        "type": "FeatureCollection",
        "name": "trails_core_box",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": trail_features,
    }
    for p in [DERIVED_DIR / "trails_core.geojson", SLICE_A_DIR / "trails_core.geojson"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(trails_out, f, indent=2)

    named_trails = sorted(set(f["properties"]["name"] for f in trail_features if f["properties"]["name"]))
    print(f"Wrote Red Rock Parkway ({len(red_rock_features)} way segments)")
    print(f"Wrote Core Box Trails ({len(trail_features)} way segments across {len(named_trails)} named trails/routes)")
    print("  Named trails/routes:", named_trails)

if __name__ == "__main__":
    main()
