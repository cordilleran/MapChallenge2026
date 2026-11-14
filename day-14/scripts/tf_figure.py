"""Day 14: the thin-film experiment's figure and measures for the page.

Patch: the upper flank, x 300-380 mm, y 30-110 mm. Rows: the photo; the Landlab model (2 mm, enlarged); the
thin-film runs at three yield stresses (start and after 20 s). Drawn as mud tone over enamel (scripts/tf_look.py).
Writes site/data/day14/thinfilm.webp and site/data/day14/thinfilm.json (fine-pattern measures, scripts/fine_measures.py).
Run: python -I scripts/tf_figure.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import zoom

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fine_measures as fm  # noqa: E402
import tf_look as tl  # noqa: E402

PATCH = (300, 30, 80, 80)
RUNS = [("0.03", "runs/tf/s2/n0.6_c1_t0.03"), ("0.6", "runs/tf/s3/t0.6"), ("6", "runs/tf/s3/t6")]
OUT = ROOT.parent / "site" / "data" / "day14"


def main():
    src = np.asarray(Image.open(ROOT / "data/source/tub_20260318_noexif.jpg").convert("L"), np.float32)
    rows = {"photo": fm.measures(fm.photo_patch(src, *PATCH))}
    d = np.load(ROOT / "runs/base_2mm/fields.npz")
    H = d["H"].astype("f8")
    x0, y0, w, h = PATCH
    sub = zoom(H[y0 // 2:(y0 + h) // 2, x0 // 2:(x0 + w) // 2], 4, order=3)
    rows["landlab"] = fm.measures(-sub)
    S = 300
    tiles = [("Photo", tl.photo(*PATCH, (S, S))), ("Landlab model", Image.fromarray(tl.tone(sub.clip(0))).resize((S, S)))]
    for tau, r in RUNS:
        z = np.load(ROOT / r / "thinfilm.npz")
        rows[f"thinfilm_tau{tau}"] = fm.measures(-z["h"].astype("f8"))
        rows[f"thinfilm_tau{tau}"]["mass_left"] = json.loads((ROOT / r / "meta.json").read_text())["mass_left_frac"]
        tiles.append((f"Thin film, {tau} Pa, after 20 s", Image.fromarray(tl.tone(z["h"].astype("f8"))).resize((S, S))))
    z0 = np.load(ROOT / RUNS[0][1] / "thinfilm.npz")["h0"].astype("f8")
    tiles.insert(2, ("Thin film, start (all runs)", Image.fromarray(tl.tone(z0)).resize((S, S))))
    for k in rows:
        if k != "photo":
            rows[k]["score_vs_photo"] = fm.score(rows["photo"], rows[k])
    fig = Image.new("RGB", (3 * S + 20, 2 * (S + 22)), (255, 255, 255))
    dr = ImageDraw.Draw(fig)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for i, (lab, im) in enumerate(tiles[:6]):
        x, y = (i % 3) * (S + 10), (i // 3) * (S + 22)
        fig.paste(im, (x, y + 20))
        dr.text((x + 2, y + 3), lab, fill=(40, 40, 40), font=font)
    fig.save(OUT / "thinfilm.webp", quality=86)
    (OUT / "thinfilm.json").write_text(json.dumps({"patch_mm": PATCH, "px_mm": 0.5, "measures": rows}, indent=1))
    for k, v in rows.items():
        print(k, v.get("perim_0.25"), v.get("euler_0.25"), v.get("corr_len_mm"), v.get("score_vs_photo"))


if __name__ == "__main__":
    main()
