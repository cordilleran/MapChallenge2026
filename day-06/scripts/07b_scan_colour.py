"""Colour-match the 1925 scan to the repeat, for the comparison slider.

The scan shows a century-old sheet: yellowed, stained paper and faded inks. To compare the two maps
by content, the scan image (out/day06_scan.png, same frame and pixels as out/day06_modern.png) is
re-inked in optical density (OD = -log10(I / paper)):
1. paper: each pixel is divided by its local paper colour (ink.paper_and_od), which removes stains
   and yellowing, and is then printed on the paper of the repeat;
2. inks: the typical OD of each plate in the scan (ink.plates; median of its densest fifth) is mapped
   by one 3 x 3 matrix (least squares over blue, brown, black and red) to the hue of the same ink in
   the repeat's palette (sheet.INK), keeping the plate's own strength times one gain. The gain is the
   ratio of the median density of contour ink (blue and brown plates), repeat over scan.
   (Reading the plates off the rendered repeat instead was tried: its brown index contours read as
   red, which skewed the fit.)
3. faint density below NOISE (paper grain, the screen of the scan) is faded out, not amplified.

Writes out/day06_scan_matched.png and derived/scan_colour.json (the matrix and the fit per plate).
The scan as printed stays in out/day06_scan.png; the page lets the reader switch between them.
"""
import json

import ink
import numpy as np
from PIL import Image
from sheet import DERIVED, INK, OUT

PLATES = ("blue", "brown", "black", "red")
# Palette colour each plate takes its hue from. Brown takes the index brown: at the scan's lower
# density the light brown came out orange beside the repeat (checked by eye on 11-10).
HUE = {"blue": "blue", "brown": "brown_idx", "black": "black", "red": "red"}
DENSE = 80     # percentile of OD within a plate taken as its solid ink
NOISE = 0.05   # summed OD below which a pixel is paper


def rgb(hexcode):
    return np.array([int(hexcode[i:i + 2], 16) for i in (1, 3, 5)], float)


def signatures(img):
    """OD image, plate masks, the typical OD of each plate (median of its densest fifth), pixel counts."""
    _, od = ink.paper_and_od(img)
    masks = ink.plates(od)
    tot = od.sum(0)
    sig, n = [], {}
    for p in PLATES:
        m = masks[p]
        dense = m & (tot >= np.percentile(tot[m], DENSE))
        sig.append(np.median(od[:, dense], axis=1))
        n[p] = int(m.sum())
    return od, masks, np.array(sig), n


def ink_density(od, masks):
    """Median summed OD of the contour inks (blue and brown plates): the bulk of both maps."""
    return float(np.median(od.sum(0)[masks["blue"] | masks["brown"]]))


def main():
    scan = np.moveaxis(np.asarray(Image.open(OUT / "day06_scan.png").convert("RGB"), float), -1, 0)
    modern = np.moveaxis(np.asarray(Image.open(OUT / "day06_modern.png").convert("RGB"), float), -1, 0)
    od, masks, S, n_scan = signatures(scan)
    _, od_m = ink.paper_and_od(modern)
    gain = ink_density(od_m, ink.plates(od_m)) / ink_density(od, masks)
    T = []
    for p, s in zip(PLATES, S, strict=True):
        t = -np.log10(rgb(INK[HUE[p]]) / rgb(INK["paper"]))
        T.append(t / np.linalg.norm(t) * np.linalg.norm(s) * gain)
    T = np.array(T)
    M, *_ = np.linalg.lstsq(S, T, rcond=None)  # S @ M ~ T
    tot = od.sum(0)
    fade = np.clip((tot - NOISE) / NOISE, 0, 1)  # 0 at NOISE, 1 at twice NOISE
    od2 = np.maximum(0, np.tensordot(M.T, od, 1)) * fade
    out = rgb(INK["paper"])[:, None, None] * 10 ** (-od2)
    Image.fromarray(np.moveaxis(np.clip(out, 0, 255).round().astype(np.uint8), 0, -1)) \
        .save(OUT / "day06_scan_matched.png", optimize=True)
    fit = {p: {"scan_px": n_scan[p], "scan_od": S[i].round(3).tolist(),
               "target_od": T[i].round(3).tolist(), "mapped_od": (S[i] @ M).round(3).tolist()}
           for i, p in enumerate(PLATES)}
    (DERIVED / "scan_colour.json").write_text(json.dumps(
        {"matrix_scan_to_repeat_od": M.round(4).tolist(), "dense_percentile": DENSE, "noise_od": NOISE,
         "gain": round(gain, 3), "paper": INK["paper"], "plates": fit}, indent=2) + "\n")
    print(json.dumps(fit))


if __name__ == "__main__":
    main()
