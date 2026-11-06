#!/usr/bin/env python3
"""
Task 1: Photo crops from upright thesis pages (A1 to A8).
Crops (a) historic 1914/1881 image, (b) repeat image, (c) caption text region.
Applies a light levels stretch (1st to 99.5th percentile mapped to 0..255 for photos),
resizes so long side <= 1400 px, saves as WebP (quality 82), writes out/photos/crops.json,
and generates out/photos/contact_sheet.png for visual review.

Thesis PDF Pages Preparation:
  Download the open-access thesis PDF (Watt 2007) from:
    https://dspace.library.uvic.ca/items/4ee99067-c147-4221-9c95-2410b113d969
  Render pages 93 to 100 at 300 dpi grayscale using pdftoppm into $MC26_DAY05_DIR/thesis_pages/:
    pdftoppm -r 300 -png -gray -f 93 -l 100 /path/to/thesis.pdf $MC26_DAY05_DIR/thesis_pages/page
  This creates files page-093.png .. page-100.png in $MC26_DAY05_DIR/thesis_pages/.
  Pages 93, 94, 95, 98, 99 printed sideways in the thesis appendix are automatically rotated
  upright (270 degrees clockwise) if needed.

Environment:
  MC26_DAY05_DIR         input data root directory (defaults to <repo_root>/../in if unset)
  MC26_THESIS_PAGES_DIR  folder holding rendered thesis pages (defaults to $MC26_DAY05_DIR/thesis_pages)
  MC26_PHOTOS_DIR        output crops folder (defaults to $MC26_DAY05_DIR/photos)
  MC26_MLP_MANIFEST      path to mlp_manifest.json (required; default $MC26_DAY05_DIR/mlp_manifest.json)
"""
import json
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
THESIS_PAGES_DIR = Path(os.environ.get("MC26_THESIS_PAGES_DIR", str(DATA_DIR / "thesis_pages"))).resolve()
PHOTOS_DIR = Path(os.environ.get("MC26_PHOTOS_DIR", str(DATA_DIR / "photos"))).resolve()
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

# Verified pixel bounding boxes [x0, y0, x1, y1] (inclusive-exclusive in PIL crop format)
# on the upright 300 dpi pages.
PAGES = [
    {
        "appendix": "A1",
        "pdf_page": 93,
        "printed_page": 86,
        "id": "plate555",
        "plate": 555,
        "station": 84,
        "source_page": "r093.png",
        "original_page": "page093-093.png",
        "rotated_from_sideways": True,
        "layout": "left_right",
        "historic_suffix": "1914",
        "historic_box": [563, 429, 1724, 1850],
        "repeat_box": [1737, 425, 2905, 1846],
        "caption_box": [555, 1875, 2965, 2005],
        "caption_text": "Appendix A 1 View west (plate 555) toward South Kootenay Pass from Mt. Blakiston (2748 m at camera station) in 1914 (left) and 2005 (right).",
        "mlp_station_id": 2081,
        "mlp_historic_capture_id": 19638,
        "mlp_repeat_2004_capture_id": 42325,
    },
    {
        "appendix": "A2",
        "pdf_page": 94,
        "printed_page": 87,
        "id": "plate584",
        "plate": 584,
        "station": 88,
        "source_page": "r094.png",
        "original_page": "page094-094.png",
        "rotated_from_sideways": True,
        "layout": "left_right",
        "historic_suffix": "1914",
        "historic_box": [599, 470, 1740, 1787],
        "repeat_box": [1776, 470, 2919, 1788],
        "caption_box": [580, 1860, 2730, 1940],
        "caption_text": "Appendix A 2 View south (plate 584) toward Mt. Festubert from Lost Mt. (2471 m) in 1914 (left) and 2004 (right).",
        "mlp_station_id": 2021,
        "mlp_historic_capture_id": 19235,
        "mlp_repeat_2004_capture_id": 41986,
    },
    {
        "appendix": "A3",
        "pdf_page": 95,
        "printed_page": 88,
        "id": "plate585",
        "plate": 585,
        "station": 88,
        "source_page": "r095.png",
        "original_page": "page095-095.png",
        "rotated_from_sideways": True,
        "layout": "left_right",
        "historic_suffix": "1914",
        "historic_box": [608, 499, 1751, 1818],
        "repeat_box": [1778, 499, 2928, 1820],
        "caption_box": [585, 1875, 2850, 2005],
        "caption_text": "Appendix A 3 View south west (plate 585) toward South Kootenay Pass from Lost Mt. (2471 m) in 1914 (left) and 2004 (right).",
        "mlp_station_id": 2021,
        "mlp_historic_capture_id": 19234,
        "mlp_repeat_2004_capture_id": 41985,
    },
    {
        "appendix": "A4",
        "pdf_page": 96,
        "printed_page": 89,
        "id": "plate594",
        "plate": 594,
        "station": 89,
        "source_page": "page096-096.png",
        "original_page": "page096-096.png",
        "rotated_from_sideways": False,
        "layout": "top_bottom",
        "historic_suffix": "1914",
        "historic_box": [592, 360, 2195, 1489],
        "repeat_box": [588, 1500, 2192, 2627],
        "caption_box": [525, 2670, 2160, 2800],
        "caption_text": "Appendix A 4 View northwest (plate 594) along the continental divide from Lone Mt. (2413 m) in 1914 (top) and 2005 (bottom).",
        "mlp_station_id": 2067,
        "mlp_historic_capture_id": 19550,
        "mlp_repeat_2004_capture_id": 42252,
    },
    {
        "appendix": "A5",
        "pdf_page": 97,
        "printed_page": 90,
        "id": "plate597",
        "plate": 597,
        "station": 89,
        "source_page": "page097-097.png",
        "original_page": "page097-097.png",
        "rotated_from_sideways": False,
        "layout": "top_bottom",
        "historic_suffix": "1914",
        "historic_box": [551, 524, 2123, 1625],
        "repeat_box": [553, 1630, 2124, 2733],
        "caption_box": [525, 2742, 2175, 2870],
        "caption_text": "Appendix A 5 View northwest (plate 597) west toward Mt. Hawkins and Mt. Festubert from Lone Mt. (2413 m) in 1914 (top) and 2004 (bottom).",
        "mlp_station_id": 2067,
        "mlp_historic_capture_id": 19544,
        "mlp_repeat_2004_capture_id": 42246,
    },
    {
        "appendix": "A6",
        "pdf_page": 98,
        "printed_page": 91,
        "id": "plate598",
        "plate": 598,
        "station": 89,
        "source_page": "r098.png",
        "original_page": "page098-098.png",
        "rotated_from_sideways": True,
        "layout": "left_right",
        "historic_suffix": "1914",
        "historic_box": [561, 402, 1728, 1863],
        "repeat_box": [1750, 402, 2914, 1861],
        "caption_box": [570, 1965, 2650, 2045],
        "caption_text": "Appendix A 6 View north (plate 598) toward Lost Mt. from Lone Mt. (2413 m) in 1914 (left) and 2004 (right).",
        "mlp_station_id": 2067,
        "mlp_historic_capture_id": 19543,
        "mlp_repeat_2004_capture_id": 42249,
    },
    {
        "appendix": "A7",
        "pdf_page": 99,
        "printed_page": 92,
        "id": "plate599",
        "plate": 599,
        "station": 89,
        "source_page": "r099.png",
        "original_page": "page099-099.png",
        "rotated_from_sideways": True,
        "layout": "left_right",
        "historic_suffix": "1914",
        "historic_box": [606, 430, 1763, 1767],
        "repeat_box": [1781, 434, 2944, 1769],
        "caption_box": [575, 1800, 2910, 1930],
        "caption_text": "Appendix A 7 View east (plate 599) toward Anderson Mt. and Red Rock Canyon Parkway from Lone Mt. (2413 m) in 1914 (left) and 2004 (right).",
        "mlp_station_id": 2067,
        "mlp_historic_capture_id": 19546,
        "mlp_repeat_2004_capture_id": 42250,
    },
    {
        "appendix": "A8",
        "pdf_page": 100,
        "printed_page": 93,
        "id": "dawson1881",
        "plate": None,
        "station": None,
        "source_page": "page100-100.png",
        "original_page": "page100-100.png",
        "rotated_from_sideways": False,
        "layout": "top_bottom",
        "historic_suffix": "1881",
        "historic_box": [544, 376, 2202, 1364],
        "repeat_box": [535, 1385, 2204, 2373],
        "caption_box": [520, 2440, 2215, 2735],
        "caption_text": "Appendix A 8 1881 (top) and 2005 (bottom) view from the upper Blakiston Valley (elevation 1750 m) east toward Mt. Blakiston, G.M. Dawson, 1881 and Trudi Smith, 2005. Note the extent and severity of the fire, extending into the alpine larch woodland on Mt. Hawkins (upper right), and possibly extinguishing in an avalanche path in the foreground.",
        "mlp_station_id": None,
        "mlp_historic_capture_id": None,
        "mlp_repeat_2004_capture_id": None,
    },
]

def find_page_image(page_info):
    """Find the rendered thesis page image in THESIS_PAGES_DIR, rotating if needed."""
    p = page_info["pdf_page"]
    candidates = [
        THESIS_PAGES_DIR / page_info["source_page"],
        THESIS_PAGES_DIR / page_info["original_page"],
        THESIS_PAGES_DIR / f"page-{p:03d}.png",
        THESIS_PAGES_DIR / f"page-{p}.png",
        THESIS_PAGES_DIR / f"page{p:03d}.png",
    ]
    for c in candidates:
        if c.exists():
            im = Image.open(c).convert("L")
            # If the page was printed sideways and image is still tall (portrait), rotate 270 deg clockwise to upright.
            # Checked 11-05: ROTATE_270 of page093-093.png reproduces the r093.png used for the site crops
            # (mean difference 0.0085 grey levels), so raw pdftoppm pages give the same crops.
            if page_info["rotated_from_sideways"] and im.size[0] < im.size[1]:
                im = im.transpose(Image.Transpose.ROTATE_270)
            return im, str(c)
    raise FileNotFoundError(
        f"Could not find rendered page image for thesis page {p} in {THESIS_PAGES_DIR}. "
        f"Checked: {[str(c) for c in candidates]}"
    )

def light_levels_stretch(im_gray):
    """Apply a gentle linear levels stretch (0.5th percentile to 99.5th percentile)."""
    arr = np.asarray(im_gray, dtype=np.float32)
    lo = float(np.percentile(arr, 0.5))
    hi = float(np.percentile(arr, 99.5))
    if hi <= lo + 10:
        return im_gray, {"lo": lo, "hi": hi}
    stretched = np.clip((arr - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    return Image.fromarray(stretched, mode="L"), {"lo": round(lo, 2), "hi": round(hi, 2)}

def resize_max_side(im, max_side=1400):
    w, h = im.size
    long_side = max(w, h)
    if long_side <= max_side:
        return im
    scale = max_side / float(long_side)
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    return im.resize((new_w, new_h), Image.Resampling.LANCZOS)

def main():
    crops_out = []
    contact_rows = []

    for p in PAGES:
        src_im, found_path = find_page_image(p)
        W, H = src_im.size

        # Crop historic
        hbox = p["historic_box"]
        h_crop_raw = src_im.crop(hbox)
        h_crop, h_levels = light_levels_stretch(h_crop_raw)
        h_crop_out = resize_max_side(h_crop, 1400)
        h_fname = str(PHOTOS_DIR / f"{p['id']}_{p['historic_suffix']}.webp")
        h_crop_out.save(h_fname, "WEBP", quality=82)

        # Crop repeat
        rbox = p["repeat_box"]
        r_crop_raw = src_im.crop(rbox)
        r_crop, r_levels = light_levels_stretch(r_crop_raw)
        r_crop_out = resize_max_side(r_crop, 1400)
        r_fname = str(PHOTOS_DIR / f"{p['id']}_repeat.webp")
        r_crop_out.save(r_fname, "WEBP", quality=82)

        # Crop caption
        cbox = p["caption_box"]
        c_crop_raw = src_im.crop(cbox)
        c_crop_out = resize_max_side(c_crop_raw, 1400)
        c_fname = str(PHOTOS_DIR / f"{p['id']}_caption.webp")
        c_crop_out.save(c_fname, "WEBP", quality=82)

        rec = {
            "appendix": p["appendix"],
            "pdf_page": p["pdf_page"],
            "printed_page": p["printed_page"],
            "id": p["id"],
            "plate": p["plate"],
            "station": p["station"],
            "source_page": Path(found_path).name,  # file name only, no local path (D97)
            "original_page": p["original_page"],
            "rotated_from_sideways": p["rotated_from_sideways"],
            "page_size_px": [W, H],
            "layout": p["layout"],
            "crops": {
                "historic": {
                    "file": h_fname,
                    "box_xyxy": hbox,
                    "box_wh": [hbox[2] - hbox[0], hbox[3] - hbox[1]],
                    "output_size_px": list(h_crop_out.size),
                    "levels_stretch": h_levels,
                },
                "repeat": {
                    "file": r_fname,
                    "box_xyxy": rbox,
                    "box_wh": [rbox[2] - rbox[0], rbox[3] - rbox[1]],
                    "output_size_px": list(r_crop_out.size),
                    "levels_stretch": r_levels,
                },
                "caption": {
                    "file": c_fname,
                    "box_xyxy": cbox,
                    "box_wh": [cbox[2] - cbox[0], cbox[3] - cbox[1]],
                    "output_size_px": list(c_crop_out.size),
                },
            },
        }
        crops_out.append(rec)
        contact_rows.append((p, h_crop_out, r_crop_out, c_crop_out))

    with open(PHOTOS_DIR / "crops.json", "w") as fp:
        json.dump({"pages": crops_out}, fp, indent=2)

    # Task 4: Build photos.json from verified manifest records
    # mlp_manifest.json: the MLP capture records for the thesis plates (recon B, 11-05), required.
    manifest_list = []
    manifest_candidates = [
        Path(os.environ.get("MC26_MLP_MANIFEST", "")) if os.environ.get("MC26_MLP_MANIFEST") else None,
        DATA_DIR / "mlp_manifest.json",
        DATA_DIR / "slice_a" / "mlp_manifest.json",
        DATA_DIR / "mlp_locations" / "mlp_manifest.json",
    ]
    manifest_by_id = {}
    for mc in manifest_candidates:
        if mc and mc.exists():
            with open(mc, "r", encoding="utf-8") as fp:
                manifest_list = json.load(fp)
            manifest_by_id = {s["mlp_id"]: s for s in manifest_list}
            break
    if not manifest_by_id:
        raise SystemExit("mlp_manifest.json not found: set MC26_MLP_MANIFEST or put it in $MC26_DAY05_DIR")

    photos_records = []
    for p in PAGES:
        mlp_id = p["mlp_station_id"]
        hid = p["mlp_historic_capture_id"]
        mid = p["mlp_repeat_2004_capture_id"]
        station_url = None
        h_meta = None
        m_meta = None
        if mlp_id is not None and mlp_id in manifest_by_id:
            st_obj = manifest_by_id[mlp_id]
            station_url = st_obj.get("page_url", f"https://explore.mountainlegacy.ca/stations/show/{mlp_id}")
            h_matches = [x for x in st_obj.get("historic", []) if x.get("capture_id") == hid]
            m_matches = [x for x in st_obj.get("modern", []) if x.get("capture_id") == mid]
            h_meta = h_matches[0] if h_matches else None
            m_meta = m_matches[0] if m_matches else None
        elif mlp_id is not None:
            station_url = f"https://explore.mountainlegacy.ca/stations/show/{mlp_id}"

        h_fname = str(PHOTOS_DIR / f"{p['id']}_{p['historic_suffix']}.webp")
        r_fname = str(PHOTOS_DIR / f"{p['id']}_repeat.webp")
        c_fname = str(PHOTOS_DIR / f"{p['id']}_caption.webp")

        if p["plate"] is not None:
            historic_credit = "M.P. Bridgland, 1914, Library and Archives Canada / Mountain Legacy Project"
            repeat_credit = "Repeat photograph © Eric Higgs (Mountain Legacy Project), as printed in Watt 2007"
        else:
            historic_credit = "G.M. Dawson, 1881 (as printed in Watt 2007; standard plate credit: M.P. Bridgland, 1914, Library and Archives Canada / Mountain Legacy Project)"
            repeat_credit = "Repeat photograph © Eric Higgs (Mountain Legacy Project), as printed in Watt 2007 (2005 repeat photographer: Trudi Smith)"

        photos_records.append({
            "id": p["id"],
            "plate": p["plate"],
            "station": p["station"],
            "thesis_appendix": p["appendix"],
            "pdf_page": p["pdf_page"],
            "printed_page": p["printed_page"],
            "caption_text": p["caption_text"],
            "files": {
                "historic": h_fname,
                "repeat": r_fname,
                "caption": c_fname,
            },
            "mlp_station_id": mlp_id,
            "mlp_station_url": station_url,
            "mlp_historic_capture_id": hid,
            "mlp_repeat_2004_capture_id": mid,
            "mlp_manifest_historic": {
                "capture_id": h_meta["capture_id"],
                "lac_ecopy": h_meta.get("lac_ecopy"),
                # MLP capture comments are left out of the published file until MLP's terms are confirmed (D97).
            } if h_meta else None,
            "mlp_manifest_2004_repeat": {
                "capture_id": m_meta["capture_id"],
                "visit_date": m_meta.get("visit_date"),
                "azim_deg": m_meta.get("azim"),
            } if m_meta else None,
            "credits": {
                "historic": historic_credit,
                "repeat": repeat_credit,
                "1914_plate": "M.P. Bridgland, 1914, Library and Archives Canada / Mountain Legacy Project",
                "repeat_standard": "Repeat photograph © Eric Higgs (Mountain Legacy Project), as printed in Watt 2007",
            },
            "thesis_link": "https://dspace.library.uvic.ca/items/4ee99067-c147-4221-9c95-2410b113d969",
        })

    for p_out in [PHOTOS_DIR / "photos.json", DATA_DIR / "photos.json"]:
        with open(p_out, "w") as fp:
            json.dump({"photos": photos_records}, fp, indent=2)

    # Build contact sheet PNG for review
    thumb_w = 420
    thumb_h = 340
    cap_w = 860
    row_h = thumb_h + 95
    sheet_w = 40 + thumb_w * 2 + 40
    sheet_h = 50 + len(contact_rows) * row_h

    sheet = Image.new("RGB", (sheet_w, sheet_h), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)

    draw.text((20, 15), "Day 5 Slice (d) - Thesis Photo & Caption Crops Contact Sheet (A1 to A8)", fill=(20, 20, 20))

    for idx, (p, h_im, r_im, c_im) in enumerate(contact_rows):
        y_top = 50 + idx * row_h
        draw.rectangle([10, y_top - 5, sheet_w - 10, y_top + row_h - 10], outline=(200, 200, 200), fill=(255, 255, 255))
        label = f"{p['appendix']} (p.{p['pdf_page']}) - {p['id']} (Stn {p['station']})"
        draw.text((20, y_top), label, fill=(10, 10, 10))

        # Historic thumb
        ht = h_im.copy()
        ht.thumbnail((thumb_w - 20, thumb_h - 30), Image.Resampling.LANCZOS)
        sheet.paste(ht.convert("RGB"), (20, y_top + 22))
        draw.rectangle([20, y_top + 22, 20 + ht.width, y_top + 22 + ht.height], outline=(120, 120, 120))
        draw.text((25, y_top + 25 + ht.height), f"{p['id']}_{p['historic_suffix']}.webp ({h_im.width}x{h_im.height})", fill=(60, 60, 60))

        # Repeat thumb
        rt = r_im.copy()
        rt.thumbnail((thumb_w - 20, thumb_h - 30), Image.Resampling.LANCZOS)
        rx = 20 + thumb_w + 10
        sheet.paste(rt.convert("RGB"), (rx, y_top + 22))
        draw.rectangle([rx, y_top + 22, rx + rt.width, y_top + 22 + rt.height], outline=(120, 120, 120))
        draw.text((rx + 5, y_top + 25 + rt.height), f"{p['id']}_repeat.webp ({r_im.width}x{r_im.height})", fill=(60, 60, 60))

        # Caption thumb below both
        ct = c_im.copy()
        ct.thumbnail((cap_w, 55), Image.Resampling.LANCZOS)
        cy = y_top + thumb_h + 15
        sheet.paste(ct.convert("RGB"), (20, cy))
        draw.rectangle([20, cy, 20 + ct.width, cy + ct.height], outline=(180, 180, 180))

    contact_path = PHOTOS_DIR / "contact_sheet.png"
    sheet.save(contact_path, "PNG")
    print(f"Saved all WebP crops, crops.json, photos.json, and {contact_path}")

if __name__ == "__main__":
    main()
