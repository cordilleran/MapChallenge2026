"""Day 14: rectify the tub photo onto the model frame and measure it.

The photo was taken from above with mild tilt. The wetted footprint (floor plus lower walls) is mapped by an
axis-aligned affine fit to its bounding box onto 1280 x 520 mm, the model frame. That ignores the small
keystone (left end about 6 % taller than the right in the photo) and the curvature of the walls; both are
stated on the page. Lighting is flattened by dividing by a 40 mm blur, so "pale" means paler than the
neighbourhood, not lit by the lamp.

Writes data/derived/photo_rect_05mm.jpg (display), data/derived/photo_metrics.npz and photo_metrics.json.
Run: python -I scripts/photo_metrics.py
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "source" / "tub_20260318_noexif.jpg"
DER = ROOT / "data" / "derived"
BOX = (120, 608, 3932, 2152)        # footprint bounding box in the 4000 x 3000 photo (left, top, right, bottom)
LX, LY = 1280, 520                  # mm
DRAIN = (120, 260)                  # mm


def structure_orientation(img, sigma_d=1.0, sigma_i=4.0):
    gy, gx = np.gradient(nd.gaussian_filter(img, sigma_d))
    jxx = nd.gaussian_filter(gx * gx, sigma_i)
    jyy = nd.gaussian_filter(gy * gy, sigma_i)
    jxy = nd.gaussian_filter(gx * gy, sigma_i)
    theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2      # direction ALONG the features
    lam = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
    coh = lam / (jxx + jyy + 1e-12)
    return theta, coh


def metrics(pale, theta, coh, mask, px_mm):
    """Shared by photo and model: along-axis and cross-axis pale fraction, orientation relative to the drain."""
    ny, nx = pale.shape
    x = (np.arange(nx) + 0.5) * px_mm
    y = (np.arange(ny) + 0.5) * px_mm
    X, Y = np.meshgrid(x, y)
    to_drain = np.arctan2(DRAIN[1] - Y, DRAIN[0] - X)
    rel = np.abs(((theta - to_drain) + np.pi / 2) % np.pi - np.pi / 2)   # 0 = aligned with the drain direction
    bins_x = np.linspace(0, LX, 33)
    bins_y = np.linspace(0, LY, 14)
    along = [float(pale[mask & (X >= a) & (X < b)].mean()) for a, b in zip(bins_x[:-1], bins_x[1:], strict=True)]
    across = [float(pale[mask & (Y >= a) & (Y < b)].mean()) for a, b in zip(bins_y[:-1], bins_y[1:], strict=True)]
    strong = mask & (coh > 0.35)
    zones = {"drain (<10 cm)": np.hypot(X - DRAIN[0], Y - DRAIN[1]) < 100,
             "axis (middle third)": (np.abs(Y - LY / 2) < LY / 6) & (X > 150),
             "walls (outer band)": (np.abs(Y - LY / 2) > LY * 0.36) & (X > 150)}
    rose = {}
    for k, z in zones.items():
        h, _ = np.histogram(rel[strong & z], bins=9, range=(0, np.pi / 2), weights=coh[strong & z])
        rose[k] = (h / max(h.sum(), 1e-9)).round(4).tolist()
    return {"pale_frac": float(pale[mask].mean()), "along_x_mm": bins_x.tolist(), "along": along,
            "across_y_mm": bins_y.tolist(), "across": across, "rose_bins_deg": np.linspace(0, 90, 10).tolist(), "rose": rose}


def main():
    DER.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert("RGB").crop(BOX)
    im.resize((LX * 2, LY * 2), Image.LANCZOS).save(DER / "photo_rect_05mm.jpg", quality=88)
    a = np.asarray(im.resize((LX, LY), Image.LANCZOS), float) / 255.0          # 1 mm pixels
    L = a.mean(2)
    flat = L / nd.gaussian_filter(L, 40)
    # footprint mask in the rectified frame: dark or saturated, closed and filled
    sat = a.max(2) - a.min(2)
    m = (L < 0.59) | (sat > 0.18)
    m = nd.binary_fill_holes(nd.binary_closing(m, iterations=8))
    lab, n = nd.label(m)
    m = lab == (np.argmax(nd.sum(m, lab, range(1, n + 1))) + 1)
    m = nd.binary_erosion(m, iterations=6)
    # pale = clearly paler than the neighbourhood AND fairly light in absolute terms (scoured film or enamel)
    pale = (flat > 1.15) & (L > np.percentile(L[m], 55))
    theta, coh = structure_orientation(flat)
    res = metrics(pale, theta, coh, m, 1.0)
    res["note"] = "1 mm pixels; pale = 15 % above the 40 mm local mean and above the footprint's 55th percentile of lightness"
    np.savez_compressed(DER / "photo_metrics.npz", L=L.astype("f4"), flat=flat.astype("f4"), pale=pale, mask=m,
                        theta=theta.astype("f4"), coh=coh.astype("f4"))
    (DER / "photo_metrics.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("pale_frac", "rose")}, indent=1))


if __name__ == "__main__":
    main()
