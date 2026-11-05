#!/usr/bin/env python3
"""Day 4 basemap: quiet greyscale relief plus coast, lakes, rivers and a few places.

Outputs (relative to the repo root):
  site/img/day04_relief.webp   hillshade in EPSG:3005, 500 m per pixel, water flat
  site/data/day04_base.js      window.D4BASE = {bbox, coast, lakes, rivers, places}

Inputs (downloaded once, never overwritten):
  AWS Terrain Tiles, Terrarium PNG, zoom 8
    "Terrain Tiles, Mapzen and AWS; includes data from SRTM, GMTED, and others"
  Natural Earth 10 m (public domain): coastline, land, lakes, lakes_north_america,
    rivers_lake_centerlines, rivers_north_america (place names are listed in PLACES below)

Environment:
  MC26_DAY04_RAW   raw cache folder; tiles go in $MC26_DAY04_RAW/tiles,
                   Natural Earth zips in $MC26_DAY04_RAW/ne

Run:  python3 -I day-04/scripts/04_basemap.py
"""
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import map_coordinates, gaussian_filter
import geopandas as gpd
import rasterio.features
from rasterio.transform import from_origin
from shapely.geometry import box

# ---------------------------------------------------------------- parameters
CRS = "EPSG:3005"
FLASH_EXTENT = (880021, 697548, 1411136, 1141336)   # flash extent, m
MARGIN = 40_000                                     # frame margin, m
RES = 500                                           # relief pixel size, m
ZOOM = 8                                            # terrain tile zoom
COORD_ROUND = 100                                   # vector rounding, m
SIMPLIFY = 400                                      # Douglas-Peucker tolerance, m
SUN_AZ, SUN_ALT = 315.0, 40.0                       # NW light, degrees
Z_EXAG = 2.0                                        # mild exaggeration, keeps it quiet
GREY_LO, GREY_HI = 0.55, 0.95                       # output grey range (low contrast)

# Orientation towns: name, lon, lat (approximations, as exact locations vary)
PLACES = [
    ("Prince George", -122.75, 53.92),
    ("Williams Lake", -122.14, 52.13),
    ("Quesnel", -122.49, 52.98),
    ("Smithers", -127.17, 54.78),
    ("Burns Lake", -125.77, 54.23),
    ("Vanderhoof", -124.01, 54.01),
    ("Bella Coola", -126.76, 52.37),
]

NE_BASE = "https://naciscdn.org/naturalearth/10m/"
NE_FILES = {
    "coastline": "physical/ne_10m_coastline.zip",
    "land": "physical/ne_10m_land.zip",
    "lakes": "physical/ne_10m_lakes.zip",
    "lakes_na": "physical/ne_10m_lakes_north_america.zip",
    "rivers": "physical/ne_10m_rivers_lake_centerlines.zip",
    "rivers_na": "physical/ne_10m_rivers_north_america.zip",
}
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

ROOT = Path(__file__).resolve().parents[2]          # repo root
raw = os.environ.get("MC26_DAY04_RAW")
if not raw:
    sys.exit("Set MC26_DAY04_RAW to the raw cache folder.")
TILE_DIR, NE_DIR = Path(raw) / "tiles", Path(raw) / "ne"
TILE_DIR.mkdir(parents=True, exist_ok=True)
NE_DIR.mkdir(parents=True, exist_ok=True)


def fetch(url, path):
    """Download once; an existing raw file is never overwritten."""
    if path.exists():
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "mapchallenge2026-day04"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------- frame
# Flash extent plus margin, snapped outward to whole km.
xmin = int(np.floor((FLASH_EXTENT[0] - MARGIN) / 1000) * 1000)
ymin = int(np.floor((FLASH_EXTENT[1] - MARGIN) / 1000) * 1000)
xmax = int(np.ceil((FLASH_EXTENT[2] + MARGIN) / 1000) * 1000)
ymax = int(np.ceil((FLASH_EXTENT[3] + MARGIN) / 1000) * 1000)
W, H = (xmax - xmin) // RES, (ymax - ymin) // RES
print("frame", xmin, ymin, xmax, ymax, "->", W, "x", H, "px")

to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
from_ll = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)

# Pixel centres in map space (row 0 = north), padded by 1 px for slope edges.
PAD = 2
cols = np.arange(-PAD, W + PAD)
rows = np.arange(-PAD, H + PAD)
X = xmin + (cols + 0.5) * RES
Y = ymax - (rows + 0.5) * RES
XX, YY = np.meshgrid(X, Y)
LON, LAT = to_ll.transform(XX, YY)

# ---------------------------------------------------------------- terrain tiles
def lonlat_to_tile(lon, lat, z):
    """Fractional slippy-map tile coordinates (Web Mercator)."""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lr = np.radians(lat)
    y = (1.0 - np.arcsinh(np.tan(lr)) / np.pi) / 2.0 * n
    return x, y

tx, ty = lonlat_to_tile(LON, LAT, ZOOM)
tx0, tx1 = int(np.floor(tx.min())) - 1, int(np.floor(tx.max())) + 1
ty0, ty1 = int(np.floor(ty.min())) - 1, int(np.floor(ty.max())) + 1
mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), dtype="float32")
for j in range(ty0, ty1 + 1):
    for i in range(tx0, tx1 + 1):
        p = fetch(TILE_URL.format(z=ZOOM, x=i, y=j), TILE_DIR / f"{ZOOM}_{i}_{j}.png")
        a = np.asarray(Image.open(p).convert("RGB")).astype("float32")
        # Terrarium encoding: metres = R*256 + G + B/256 - 32768
        mosaic[(j - ty0) * 256:(j - ty0 + 1) * 256,
               (i - tx0) * 256:(i - tx0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
print("tiles", (tx1 - tx0 + 1) * (ty1 - ty0 + 1))

# Inverse-map every output pixel to the mosaic and sample bilinearly.
px = (tx - tx0) * 256 - 0.5
py = (ty - ty0) * 256 - 0.5
elev = map_coordinates(mosaic, [py, px], order=1, mode="nearest").astype("float32")

# ---------------------------------------------------------------- water mask
def read_ne(key):
    zp = fetch(NE_BASE + NE_FILES[key], NE_DIR / Path(NE_FILES[key]).name)
    d = NE_DIR / ("x_" + zp.stem)               # extract beside the zip (raw cache)
    if not d.exists():
        d.mkdir()
        with zipfile.ZipFile(zp) as z:
            z.extractall(d)
    return gpd.read_file(next(d.glob("*.shp")))

# Work window in lon/lat (frame corners and edges, densified) padded by 0.5 deg
t = np.linspace(0, 1, 50)
ex = np.concatenate([xmin + t * (xmax - xmin), xmin + t * (xmax - xmin), np.full(50, xmin), np.full(50, xmax)])
ey = np.concatenate([np.full(50, ymin), np.full(50, ymax), ymin + t * (ymax - ymin), ymin + t * (ymax - ymin)])
elon, elat = to_ll.transform(ex, ey)
win = box(elon.min() - 0.5, elat.min() - 0.5, elon.max() + 0.5, elat.max() + 0.5)
frame_poly = box(xmin, ymin, xmax, ymax)


def to_frame(gdf):
    """Clip to the lon/lat window, reproject to EPSG:3005, clip to the frame."""
    g = gdf[gdf.intersects(win)].copy()
    g["geometry"] = g.geometry.intersection(win)
    g = g.to_crs(CRS)
    g["geometry"] = g.geometry.intersection(frame_poly.buffer(5000))
    return g[~g.geometry.is_empty]

land = to_frame(read_ne("land"))
# World lakes plus the North America supplement (Babine, Stuart, Ootsa ... are only in the latter)
_l = [read_ne("lakes"), read_ne("lakes_na")]
lakes = to_frame(gpd.GeoDataFrame(geometry=[g for p in _l for g in p.geometry], crs=_l[0].crs))
transform = from_origin(xmin - PAD * RES, ymax + PAD * RES, RES, RES)
shape = (H + 2 * PAD, W + 2 * PAD)
land_mask = rasterio.features.rasterize(land.geometry, out_shape=shape, transform=transform, fill=0, default_value=1).astype(bool)

# Ocean: flat at 0 m. Lakes: flat at the median elevation of each lake's pixels.
elev[~land_mask] = 0.0
for geom in lakes.geometry:
    m = rasterio.features.rasterize([geom], out_shape=shape, transform=transform, fill=0, default_value=1).astype(bool)
    if m.sum() > 0:
        elev[m] = np.median(elev[m])

# ---------------------------------------------------------------- hillshade
# Light smoothing removes tile-seam stair-steps and keeps the relief quiet.
z = gaussian_filter(elev, 0.8) * Z_EXAG
dzdy, dzdx = np.gradient(z, RES)            # rows run south, so dzdy is d/d(-north)
slope = np.arctan(np.hypot(dzdx, dzdy))
aspect = np.arctan2(dzdy, -dzdx)            # downslope direction convention of GDAL
az, alt = np.radians(360 - SUN_AZ + 90), np.radians(SUN_ALT)
hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
hs = np.clip(hs, 0, 1)
lo, hi = np.percentile(hs, [1, 99])
g = np.clip((hs - lo) / (hi - lo), 0, 1)
g = GREY_LO + g * (GREY_HI - GREY_LO)
g = g[PAD:-PAD, PAD:-PAD]
img = Image.fromarray((g * 255).astype("uint8"), "L")
out_img = ROOT / "site" / "img" / "day04_relief.webp"
out_img.parent.mkdir(parents=True, exist_ok=True)
img.save(out_img, "WEBP", quality=82, method=6)
print("wrote", out_img, img.size, out_img.stat().st_size)

# ---------------------------------------------------------------- vectors
def r100(v):
    return int(round(v / COORD_ROUND))

def lines_of(geom):
    """Yield coordinate lists from any (multi)line or polygon boundary."""
    if geom.is_empty:
        return
    gt = geom.geom_type
    if gt == "LineString":
        yield list(geom.coords)
    elif gt == "Polygon":
        yield list(geom.exterior.coords)       # lake islands skipped to save bytes
    elif gt in ("MultiLineString", "MultiPolygon", "GeometryCollection"):
        for p in geom.geoms:
            yield from lines_of(p)

def pack(gdf, min_len=0, simplify=SIMPLIFY, clip=True):
    """Return [[x0,y0,x1,y1,...], ...] in units of 100 m, simplified."""
    out = []
    for geom in gdf.geometry:
        if clip:
            geom = geom.intersection(frame_poly)
        geom = geom.simplify(simplify, preserve_topology=False)
        for c in lines_of(geom):
            if len(c) < 2:
                continue
            ln = sum(np.hypot(c[i + 1][0] - c[i][0], c[i + 1][1] - c[i][1]) for i in range(len(c) - 1))
            if ln < min_len:
                continue
            flat_c = []
            for x, y in c:
                a, b = r100(x), r100(y)
                if not flat_c or (a, b) != (flat_c[-2], flat_c[-1]):
                    flat_c += [a, b]
            if len(flat_c) >= 4:
                out.append(flat_c)
    return out

coast = to_frame(read_ne("coastline"))
coast_j = pack(coast, min_len=3000)
lakes_j = pack(lakes[lakes.geometry.area > 4e6], min_len=0)    # lakes over ~4 km2

riv = read_ne("rivers")
parts = [riv]
try:
    parts.append(read_ne("rivers_na"))
except Exception as e:                       # supplement is optional
    print("rivers_north_america not available:", e)
rivers = to_frame(gpd.GeoDataFrame(
    geometry=[g for p in parts for g in p.geometry], crs=riv.crs))
rivers_j = pack(rivers, min_len=5000)

places_j = []
for name, lon, lat in PLACES:
    x, y = from_ll.transform(lon, lat)
    if xmin <= x <= xmax and ymin <= y <= ymax:
        places_j.append({"name": name, "x": r100(x), "y": r100(y)})

base = {
    "note": "Natural Earth 10 m (public domain); relief from AWS Terrain Tiles (Mapzen, SRTM, GMTED). EPSG:3005.",
    "units": "100 m",
    "bbox": [xmin, ymin, xmax, ymax],
    "coast": coast_j, "lakes": lakes_j, "rivers": rivers_j, "places": places_j,
}
out_js = ROOT / "site" / "data" / "day04_base.js"
out_js.write_text(
    "/* Day 4 basemap vectors. Generated by day-04/scripts/04_basemap.py; do not edit. */\n"
    "window.D4BASE = " + json.dumps(base, separators=(",", ":")) + ";\n")
print("wrote", out_js, out_js.stat().st_size,
      {k: len(base[k]) for k in ("coast", "lakes", "rivers", "places")})
