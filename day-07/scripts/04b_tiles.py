"""Day 7 step 04b: the Deep Zoom tiles for the page's zoom viewer (OpenSeadragon, site/js/day07.js), as on Day 6.

The PDF from step 03 (map raster at 762 dpi, vector text) is rasterised whole at 762 dpi with pdftoppm, so the
1958 lettering and the collar text are as crisp as the PDF, then cut into a WebP pyramid:
  site/img/day07/tiles/page.dzi and page_files/<level>/<col>_<row>.webp
Needs poppler-utils (pdftoppm) and Pillow. Run: python3 day-07/scripts/04b_tiles.py [A|B] (default B).
"""
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
DST = HERE.parents[1] / "site" / "img" / "day07" / "tiles"
DPI = 762       # as BASE_DPI in 03_map.R: one pixel of the 1958 scans
TILE = 510      # tile edge plus OVERLAP on each inner side (the Deep Zoom default shape, as Day 6)
OVERLAP = 1
QUALITY = 70    # WebP quality, as Day 6
Image.MAX_IMAGE_PIXELS = None   # the page is about 108 Mpx


def rasterise(pdf, png_stem):
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-singlefile", str(pdf), str(png_stem)], check=True)
    return Path(f"{png_stem}.png")


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
    variant = sys.argv[1] if len(sys.argv) > 1 else "B"
    DST.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        png = rasterise(OUT / f"day07_{variant}.pdf", Path(tmp) / "page")
        tile(png, "page")


if __name__ == "__main__":
    main()
