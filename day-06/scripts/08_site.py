"""Copy the Day 6 images to the site as WebP, and write the numbers the page quotes.

Writes site/img/day06/{scan,scan_matched,2021,2021_m,sheet,sheet_m,legend,legend_m}.webp, site/img/day06_thumb.webp and
site/data/day06.json (areas, ranges and georeferencing error, from derived/*.json).
"""
import json

from PIL import Image, ImageChops
from sheet import DERIVED, OUT

SITE = OUT.parents[1] / "site"
SLIDER_PX = 2000  # the scan now comes from the 600 ppi master and holds detail at this width
# The 600 dpi sheets for the zoom viewer are tiled by 08b_tiles.py, not here.


def webp(src, dst, width, quality=82):
    """src as WebP at width pixels (None: full size)."""
    im = Image.open(src).convert("RGB")
    if width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "WEBP", quality=quality, method=6)
    return im.size


def main():
    d = SITE / "img" / "day06"
    sizes = {
        "scan": webp(OUT / "day06_scan.png", d / "scan.webp", SLIDER_PX),
        "scan_matched": webp(OUT / "day06_scan_matched.png", d / "scan_matched.webp", SLIDER_PX),
        "2021": webp(OUT / "day06_modern.png", d / "2021.webp", SLIDER_PX),
        "2021_m": webp(OUT / "day06_modern_m.png", d / "2021_m.webp", SLIDER_PX),
        "sheet": webp(OUT / "day06_sheet.png", d / "sheet.webp", 2000),
        "sheet_m": webp(OUT / "day06_sheet_m.png", d / "sheet_m.webp", 2000),
    }
    # The references alone, below the slider: cropped to their ink with a small margin.
    for suffix in ("", "_m"):
        im = Image.open(OUT / f"day06_legend{suffix}.png").convert("RGB")
        box = ImageChops.difference(im, Image.new("RGB", im.size, im.getpixel((0, 0)))).getbbox()
        pad = 20
        im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height)))
        im.save(d / f"legend{suffix}.webp", "WEBP", quality=88, method=6)
        sizes[f"legend{suffix}"] = im.size
    # Thumbnail: the Waputik Icefield and Hector Lake, from the modern map.
    im = Image.open(OUT / "day06_modern.png").convert("RGB")
    w, h = im.size
    im.crop((int(w * 0.18), int(h * 0.08), int(w * 0.68), int(h * 0.48))).resize((600, 480), Image.LANCZOS) \
        .save(SITE / "img" / "day06_thumb.webp", "WEBP", quality=80, method=6)

    c = json.loads((DERIVED / "compare_metrics.json").read_text())
    g = json.loads((DERIVED / "georef_report.json").read_text())
    out = {"area_km2": c["area_km2"], "area_1913_range_km2": c["area_1913_range_km2"],
           "loss_1913_2021_pct": c["loss_1913_2021_pct"], "loss_1913_2021_pct_range": c["loss_1913_2021_pct_range"],
           "share_1985_inside_1913": c["share_1985_inside_1913"], "georef_held_out_rms_m": g["held_out_rms_m"],
           "image_px": sizes}
    (SITE / "data").mkdir(exist_ok=True)
    (SITE / "data" / "day06.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
