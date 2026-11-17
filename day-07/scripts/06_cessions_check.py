"""Day 7: which Royce cession areas contain the colophon points? Point-in-polygon test.

Source: USDA Forest Service EDW "Indian Land Cessions in the United States" (Royce 1899
maps, digitized), REST layer 0:
https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TribalCessionLands_01/MapServer/0
Downloads the polygons that intersect a bbox once (skipped if present) to
raw/cessions/royce_cessions_mn_bbox.geojson, then tests points and the frame box.
Run with the geospatial venv (shapely). Output: derived/cessions_check.csv.
"""
import os, sys, json, datetime, urllib.parse, urllib.request
from pathlib import Path
from shapely.geometry import shape, Point, box

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
D = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
F = D / "raw" / "cessions" / "royce_cessions_mn_bbox.geojson"
OUT = D / "derived" / "cessions_check.csv"
URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TribalCessionLands_01/MapServer/0/query"
PTS = {"Hibbing": (47.427, -92.938), "Duluth": (46.784, -92.105), "Superior WI": (46.72, -92.10), "Cloquet": (46.72, -92.46)}
FRAME = box(-93.30, 46.40, -91.30, 47.72)   # the final frame (D321), as FRAME_LL in config.R

if not F.exists():
    F.parent.mkdir(parents=True, exist_ok=True)
    q = dict(where="1=1", geometry="-95,45.5,-90,48.5", geometryType="esriGeometryEnvelope", inSR="4326",
             spatialRel="esriSpatialRelIntersects", outFields="*", outSR="4326", f="geojson")
    with urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(q), timeout=120) as r:
        body = r.read()
    if "features" not in json.loads(body):   # ArcGIS answers errors with HTTP 200
        raise SystemExit(f"cession query failed: {body[:200]!r}")
    part = F.with_suffix(".part")
    part.write_bytes(body)
    part.rename(F)   # cached only when whole

def dates(p):
    out = []
    for k, v in p.items():
        if k.split(".")[-1] in {f"cessdate{i}" for i in range(1, 6)} and v is not None:
            out.append((datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=v)).date().isoformat())
    return sorted(out)

feats = []
for f in json.load(open(F))["features"]:
    p = {k.split(".")[-1]: v for k, v in f["properties"].items()}
    feats.append((p["cessnum"], p.get("schdtrb"), dates(f["properties"]), shape(f["geometry"])))

rows = []
for name, (lat, lon) in PTS.items():
    hits = [(n, t, d) for n, t, d, g in feats if g.intersects(Point(lon, lat))]   # a point on a boundary counts
    print(name, hits or "no cession polygon")
    rows.append((name, ";".join(str(h[0]) for h in hits), " | ".join(f"{h[1]} {h[2]}" for h in hits)))
print("frame box:")
for n, t, d, g in feats:
    if g.intersects(FRAME):
        rel = "contains frame" if g.contains(FRAME) else "crosses frame"
        print(f"  Royce {n} ({t}, {d}) {rel}; boundary crosses frame: {g.boundary.intersects(FRAME)}")
        rows.append(("frame", n, f"{t} {d} {rel}"))
import csv
OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["item", "royce_cessnum", "detail"]); w.writerows(rows)
