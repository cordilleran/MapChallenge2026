"""Day 15 (static): page assets from the renders.

  site/img/day15/tiles/world_<view>.dzi + _files/  Deep Zoom pyramids of the world renders (WebP)
  site/img/day15/world_<view>.webp                  2000 px previews (shown until the tiles load)
  site/img/day15/<focus>_<view>.webp                close-up stills
  site/img/day15_thumb.webp                         calendar thumbnail
  site/data/day15.json                              every number the page shows, from the facts files

The tiling is the Day 6 method (day-06/scripts/08b_tiles.py): 510 px tiles, 1 px overlap.

usage: site_assets.py DERIVED_STATIC_DIR SITE_DIR
"""
import argparse
import json
import math
import shutil
from pathlib import Path

from cmcrameri import cm  # the legend uses the same colour map as the renders
from PIL import Image

ap = argparse.ArgumentParser(description="Day 15 page assets from the renders.")
ap.add_argument("derived", help="folder with the world_* and <focus>_* renders and facts")
ap.add_argument("site", help="the repo's site/ folder")
args = ap.parse_args()
SRC, SITE = Path(args.derived), Path(args.site)
IMG = SITE / "img" / "day15"
TILES = IMG / "tiles"
TILES.mkdir(parents=True, exist_ok=True)
Image.MAX_IMAGE_PIXELS = None
TILE, OVERLAP, QUALITY = 510, 1, 72
VIEWS = ("hillshade", "hypso", "fused")
FOCI = ("andes", "fennoscandia")


def tile(src, name):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    files = TILES / f"{name}_files"
    if files.exists():
        shutil.rmtree(files)
    top = math.ceil(math.log2(max(w, h)))
    n = 0
    for level in range(top, -1, -1):
        lw, lh = math.ceil(w / 2 ** (top - level)), math.ceil(h / 2 ** (top - level))
        if (lw, lh) != im.size:
            im = im.resize((lw, lh), Image.LANCZOS)
        d = files / str(level)
        d.mkdir(parents=True)
        for c in range(math.ceil(lw / TILE)):
            for r in range(math.ceil(lh / TILE)):
                x0, y0 = max(c * TILE - OVERLAP, 0), max(r * TILE - OVERLAP, 0)
                x1, y1 = min((c + 1) * TILE + OVERLAP, lw), min((r + 1) * TILE + OVERLAP, lh)
                im.crop((x0, y0, x1, y1)).save(d / f"{c}_{r}.webp", "WEBP", quality=QUALITY, method=6)
                n += 1
    (TILES / f"{name}.dzi").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" Format="webp" Overlap="{OVERLAP}" '
        f'TileSize="{TILE}"><Size Width="{w}" Height="{h}"/></Image>\n')
    size = sum(f.stat().st_size for f in files.rglob("*") if f.is_file())
    print(f"{name}: {w}x{h} px, {top + 1} levels, {n} tiles, {size / 1e6:.1f} MB")
    return dict(w=w, h=h, mb=round(size / 1e6, 1))


def webp(src, dst, width):
    im = Image.open(src).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(dst, "WEBP", quality=80, method=6)
    return dict(w=im.width, h=im.height)


out = dict(world={}, foci={})
for v in VIEWS:
    out["world"][v] = dict(tiles=tile(SRC / f"world_{v}.png", f"world_{v}"),
                           preview=webp(SRC / f"world_{v}.png", IMG / f"world_{v}.webp", 2000))
for f in FOCI:
    for v in VIEWS:
        out["foci"].setdefault(f, {})[v] = webp(SRC / f"{f}_{v}.png", IMG / f"{f}_{v}.webp", 1200)
    out["foci"][f]["facts"] = json.loads((SRC / f"{f}_facts.json").read_text())
th = Image.open(SRC / "world_hypso.png").convert("RGB")
th = th.crop((th.width // 4, th.height // 6, th.width * 3 // 4, th.height * 5 // 6)).resize((600, 400), Image.LANCZOS)
th.save(SITE / "img" / "day15_thumb.webp", "WEBP", quality=78, method=6)
out["world"]["facts"] = json.loads((SRC / "world_facts.json").read_text())
out["legend"] = dict(lims_km=out["world"]["facts"]["hypso_lims_km"],
                     stops=["#%02x%02x%02x" % tuple(int(round(255 * c)) for c in cm.batlow(i / 10)[:3]) for i in range(11)])
(SITE / "data").mkdir(exist_ok=True)
(SITE / "data" / "day15.json").write_text(json.dumps(out, indent=1))
print("wrote", SITE / "data" / "day15.json")
