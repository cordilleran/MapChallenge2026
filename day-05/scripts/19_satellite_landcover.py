#!/usr/bin/env python3
"""Day 5 (19): full-frame satellite and land cover layers for the map.

Produces, on the same EPSG:3857 grid as base_viewshed.webp (50 m Mercator, 2666 x 2638):
  site/img/day05/s2_viewshed.webp         Sentinel-2 L2A true colour (TCI), 25 August 2025,
                                          tiles 11UPQ and 11UQQ, read from Earth Search (AWS open data)
  site/img/day05/landcover_viewshed.webp  ESA WorldCover 2021 v200 classes, in the colours the
                                          simulated panoramas use (17_render_panoramas.py)
  site/data/day05/layers.json             file names, bounds, legend for the land cover classes

The Sentinel-2 warp reads the cloud-optimised GeoTIFFs over HTTP (GDAL /vsicurl/), so this
step needs the network. The warped TCI is also written to $MC26_DAY05_DIR/s2full/ so the
page assets can be rebuilt offline.

Environment:
  MC26_DAY05_DIR   input directory holding slice_a/ (defaults to <repo_root>/../in if unset)
"""
import json
import os
import subprocess
import urllib.request
from pathlib import Path

import numpy as np
from osgeo import gdal
from PIL import Image

gdal.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
IN_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
OUT_IMG = ROOT / "site" / "img" / "day05"
OUT_DATA = ROOT / "site" / "data" / "day05"
S2_DIR = IN_DIR / "s2full"
S2_DIR.mkdir(parents=True, exist_ok=True)

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
ITEM_IDS = ["S2B_11UPQ_20250825_0_L2A", "S2B_11UQQ_20250825_0_L2A"]

bounds = json.loads((OUT_DATA / "base_bounds.json").read_text())["viewshed"]
XMIN, YMIN, XMAX, YMAX = bounds["bounds_3857"]
W, H = bounds["width"], bounds["height"]
TE = [str(v) for v in (XMIN, YMIN, XMAX, YMAX)]

# Same RGB as WC_COLOURS in 17_render_panoramas.py (classes absent from the box are skipped in the legend).
WC = {
    10: ((55, 82, 52), "Tree cover"),
    20: ((108, 125, 82), "Shrubland"),
    30: ((142, 146, 98), "Grassland"),
    40: ((155, 148, 105), "Cropland"),
    50: ((125, 125, 125), "Built-up"),
    60: ((168, 158, 148), "Bare or sparse"),
    70: ((238, 242, 246), "Snow and ice"),
    80: ((55, 85, 122), "Water"),
    90: ((88, 112, 88), "Wetland"),
    100: ((128, 132, 102), "Moss and lichen"),
}


def run(cmd):
    print("RUN", " ".join(cmd))
    subprocess.run(cmd, check=True)


def satellite():
    tci = S2_DIR / "s2_20250825_TCI_viewshed_50m_epsg3857.tif"
    if not tci.exists():
        payload = json.dumps({"collections": ["sentinel-2-l2a"], "ids": ITEM_IDS}).encode()
        req = urllib.request.Request(STAC_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            stac = json.loads(r.read())
        (S2_DIR / "stac_sentinel2_20250825.json").write_text(json.dumps(stac, indent=1))
        hrefs = {f["id"]: f["assets"]["visual"]["href"] for f in stac["features"]}
        srcs = [f"/vsicurl/{hrefs[i]}" for i in ITEM_IDS]
        # TCI uses 0 as nodata outside each tile's swath; average resampling at 50 m from 10 m.
        run(["gdalwarp", "-overwrite", "-t_srs", "EPSG:3857", "-te", *TE, "-ts", str(W), str(H),
             "-r", "average", "-srcnodata", "0", "-dstnodata", "0",
             "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", *srcs, str(tci)])
    a = gdal.Open(str(tci)).ReadAsArray()  # (3, H, W)
    rgb = np.moveaxis(a, 0, -1).astype(np.uint8)
    empty = (rgb == 0).all(axis=2)
    # Clip to the hillshade's footprint (the EPSG:3979 viewshed box, rotated in Mercator).
    hs = np.array(Image.open(OUT_IMG / "base_viewshed.webp").convert("RGBA"))
    empty |= hs[:, :, 3] == 0
    print(f"satellite: {empty.mean() * 100:.2f}% of pixels without data")
    rgba = np.dstack([rgb, np.where(empty, 0, 255).astype(np.uint8)])
    out = OUT_IMG / "s2_viewshed.webp"
    Image.fromarray(rgba, "RGBA").save(out, "WEBP", quality=80, method=6)
    return out


def landcover():
    src = IN_DIR / "slice_a" / "derived" / "worldcover_2021_viewshed_10m_epsg3979.tif"
    tmp = S2_DIR / "worldcover_viewshed_50m_epsg3857.tif"
    run(["gdalwarp", "-overwrite", "-t_srs", "EPSG:3857", "-te", *TE, "-ts", str(W), str(H),
         "-r", "mode", "-co", "COMPRESS=DEFLATE", str(src), str(tmp)])
    cls = gdal.Open(str(tmp)).ReadAsArray()
    rgba = np.zeros((H, W, 4), np.uint8)
    present = []
    for k, (rgb, name) in WC.items():
        m = cls == k
        if m.any():
            rgba[m, :3] = rgb
            rgba[m, 3] = 255
            present.append({"class": k, "name": name, "rgb": list(rgb),
                            "share_pct": round(float(m.mean() * 100), 2)})
    out = OUT_IMG / "landcover_viewshed.webp"
    Image.fromarray(rgba, "RGBA").save(out, "WEBP", lossless=True, method=6)
    return out, present


def main():
    lc, legend = landcover()
    s2 = satellite()
    meta = {
        "bounds": bounds["bounds"],
        "satellite": {"url": f"img/day05/{s2.name}", "size_bytes": s2.stat().st_size,
                      "credit": "Contains modified Copernicus Sentinel data 2025 (Sentinel-2B, 25 August 2025)"},
        "landcover": {"url": f"img/day05/{lc.name}", "size_bytes": lc.stat().st_size,
                      "credit": "ESA WorldCover 10 m 2021 v200", "legend": legend},
    }
    (OUT_DATA / "layers.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
