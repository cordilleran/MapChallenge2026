"""Cut the 600 ppi master scan of the 1925 sheet into a Deep Zoom tile pyramid for the page's scan viewer.

Writes site/img/day06/scan/sheet16.dzi and sheet16_files/<level>/<col>_<row>.webp, read by OpenSeadragon
(site/js/day06.js). The scan is the whole sheet as catalogued, margins included, untouched apart from
the tiling and WebP compression. Source: MC26_SHEET16 (see env.example).
"""
import math
import os
import shutil
from pathlib import Path

from PIL import Image
from sheet import OUT

SITE = OUT.parents[1] / "site"
TILE = 510      # tile edge in pixels, plus OVERLAP on each inner side (the Deep Zoom default shape)
OVERLAP = 1
QUALITY = 70    # WebP quality: the paper texture costs bytes, the ink holds at this level
Image.MAX_IMAGE_PIXELS = None  # the master is 106 Mpx


def main():
    src = Path(os.environ["MC26_SHEET16"])
    im = Image.open(src).convert("RGB")
    w, h = im.size
    dst = SITE / "img" / "day06" / "scan"
    if dst.exists():
        shutil.rmtree(dst)
    files = dst / "sheet16_files"
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
    (dst / "sheet16.dzi").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" Format="webp" Overlap="{OVERLAP}" '
        f'TileSize="{TILE}"><Size Width="{w}" Height="{h}"/></Image>\n')
    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"{w}x{h} px, {top + 1} levels, {n} tiles, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
