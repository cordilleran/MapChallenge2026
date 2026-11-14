"""Quick look at thin-film runs: start, end and the photo for the same patch, drawn as mud tone over enamel.

Run: python -I scripts/tf_look.py OUT.png RUN_DIR [RUN_DIR ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ENAMEL = np.array([238, 234, 224.0])
MUD = np.array([66, 46, 30.0])
K = np.array([1 / 2.2e-4, 1 / 1.6e-4, 1 / 1.1e-4])   # blue darkens fastest: cream, tan, umber


def tone(h):
    a = 1 - np.exp(-np.clip(h - 2e-5, 0, None)[..., None] * K)
    return np.clip(ENAMEL * (1 - a) + MUD * a, 0, 255).astype("uint8")


def photo(x0, y0, w, h, px):
    src = Image.open(ROOT / "data/source/tub_20260318_noexif.jpg").convert("RGB")
    pxmm = 3812 / 1280
    return src.crop((int(120 + x0 * pxmm), int(608 + y0 * pxmm), int(120 + (x0 + w) * pxmm), int(608 + (y0 + h) * pxmm))).resize(px, Image.LANCZOS)


def main():
    out, runs = sys.argv[1], sys.argv[2:]
    rows = []
    for r in runs:
        d = np.load(Path(r) / "thinfilm.npz")
        m = json.loads((Path(r) / "meta.json").read_text())
        a, b = Image.fromarray(tone(d["h0"])), Image.fromarray(tone(d["h"]))
        S = 320
        a, b = a.resize((S, int(S * a.height / a.width))), b.resize((S, int(S * b.height / b.width)))
        x0, y0, w, h = m["patch_mm"]
        p = photo(x0, y0, w, h, a.size)
        row = Image.new("RGB", (3 * S + 20, a.height + 16), (255, 255, 255))
        for i, im in enumerate((p, a, b)):
            row.paste(im, (i * (S + 10), 16))
        ImageDraw.Draw(row).text((2, 2), f"{Path(r).name}: tau {m['tau_y_Pa']} mu {m['mu_Pas']} theta {m['theta_deg']} t {m['t_end_s']} s, left {m['mass_left_frac']}", fill=(0, 0, 0))
        rows.append(row)
    H = sum(r.height for r in rows)
    sheet = Image.new("RGB", (rows[0].width, H), (255, 255, 255))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height
    sheet.save(out)


if __name__ == "__main__":
    main()
