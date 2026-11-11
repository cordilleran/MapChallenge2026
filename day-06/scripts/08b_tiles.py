"""Cut the 600 ppi images into Deep Zoom tile pyramids for the page's zoom viewers (OpenSeadragon, site/js/day06.js).

  scan      the 600 ppi master scan of the 1925 sheet, margins included (MC26_SHEET16; see env.example)
  sheet     the full repeat in feet, rendered at 600 dpi by 07_render.py (out/day06_sheet_zoom.png)
  sheet_m   the same in metres (out/day06_sheet_m_zoom.png)

Writes site/img/day06/tiles/<name>.dzi and <name>_files/<level>/<col>_<row>.webp. The images are untouched apart
from the tiling and WebP compression. Run: python3 08b_tiles.py [scan] [sheet] [sheet_m] (default: all three;
the scan needs cutting again only if the scan changes).
"""
import math
import os
import shutil
import sys
from pathlib import Path

from PIL import Image
from sheet import OUT

SITE = OUT.parents[1] / "site"
DST = SITE / "img" / "day06" / "tiles"
TILE = 510      # tile edge in pixels, plus OVERLAP on each inner side (the Deep Zoom default shape)
OVERLAP = 1
QUALITY = 70    # WebP quality: the scan's paper texture costs bytes, the ink holds at this level
Image.MAX_IMAGE_PIXELS = None  # the scan is 106 Mpx, the renders 111 Mpx


def sources():
    return {"scan": lambda: Path(os.environ["MC26_SHEET16"]),
            "sheet": lambda: OUT / "day06_sheet_zoom.png",
            "sheet_m": lambda: OUT / "day06_sheet_m_zoom.png"}


def tile(src, name):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    files = DST / f"{name}_files"
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
    (DST / f"{name}.dzi").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" Format="webp" Overlap="{OVERLAP}" '
        f'TileSize="{TILE}"><Size Width="{w}" Height="{h}"/></Image>\n')
    size = sum(f.stat().st_size for f in files.rglob("*") if f.is_file())
    print(f"{name}: {w}x{h} px, {top + 1} levels, {n} tiles, {size / 1e6:.1f} MB")


def main():
    src = sources()
    names = sys.argv[1:] or list(src)
    bad = [n for n in names if n not in src]
    if bad:
        raise SystemExit(f"unknown image {bad}; choose from {list(src)}")
    DST.mkdir(parents=True, exist_ok=True)
    for name in names:
        tile(src[name](), name)


if __name__ == "__main__":
    main()
