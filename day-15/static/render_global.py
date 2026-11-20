"""Day 15 (static): the whole ground seen from the centre, on a mirrored Equal Earth map.

Three full-size images for the zoom viewer (no frame, no text): hillshade, hypso, fused.
Equal Earth (Šavrič, Patterson and Jenny 2019) is equal-area, so every pixel is the same
patch of sky. Mirrored: east is to the left, as seen from inside.

A single lamp cannot light the whole planet from inside, so each point is lit from inside
at a fixed angle to its own screen directions: raking from the upper left, 60 degrees from
the inward normal. Shadows are cast along that direction.

usage: render_global.py RAW_STATIC_DIR OUT_DIR [--width 9000] [--lon0 0] [--z 25]
"""
import argparse
import json
from pathlib import Path

import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
import inside_common as ic  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("raw"); ap.add_argument("out")
ap.add_argument("--width", type=int, default=9000)
ap.add_argument("--lon0", type=float, default=0.0)
ap.add_argument("--z", type=float, default=25.0)
ap.add_argument("--elev", type=float, default=60.0)       # light angle from the inward normal, degrees
ap.add_argument("--strip", type=int, default=96)
args = ap.parse_args()
RAW, OUT = Path(args.raw), Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)
ic.load(OUT)
Image.MAX_IMAGE_PIXELS = None

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = np.sqrt(3) / 2
XMAX = 2 * np.sqrt(3) * np.pi / (3 * A1)                  # x at the equator, lambda = pi
YMAX = (lambda t: t * (A1 + A2 * t ** 2 + t ** 6 * (A3 + A4 * t ** 2)))(np.arcsin(M))


def inv_ee(xs, ys):
    """Screen (x right, y up) -> (lat, lon, inside). Mirrored: x = -xs."""
    x = -xs
    t = ys.copy()
    for _ in range(12):
        f = t * (A1 + A2 * t ** 2 + t ** 6 * (A3 + A4 * t ** 2)) - ys
        fp = A1 + 3 * A2 * t ** 2 + t ** 6 * (7 * A3 + 9 * A4 * t ** 2)
        t = t - f / fp
    fp = A1 + 3 * A2 * t ** 2 + t ** 6 * (7 * A3 + 9 * A4 * t ** 2)
    lam = 3 * x * fp / (2 * np.sqrt(3) * np.cos(t))
    lat = np.degrees(np.arcsin(np.clip(np.sin(t) / M, -1, 1)))
    inside = (np.abs(lam) <= np.pi) & (np.abs(ys) <= YMAX)
    return lat, np.degrees(lam) + args.lon0, inside


W = args.width
pad = 0.01
Hpx = int(round(W * (YMAX + pad) / (XMAX + pad)))
xs = np.linspace(-(XMAX + pad), XMAX + pad, W)
ys_all = np.linspace(YMAX + pad, -(YMAX + pad), Hpx)
rel = np.full((Hpx, W), np.nan, np.float32)
rkm = np.full((Hpx, W), np.nan, np.float32)
sat = np.zeros((Hpx, W, 3), np.float32)
bm = np.asarray(Image.open(RAW / "bmng_200408_5400.jpg").convert("RGB"), np.float32) / 255.0
el = np.radians(args.elev)

for i0 in range(0, Hpx, args.strip):
    a, b = max(i0 - 2, 0), min(i0 + args.strip + 2, Hpx)
    XS, YS = np.meshgrid(xs, ys_all[a:b])
    lat, lon, ins = inv_ee(XS, YS)
    U = ic.unit(lat, lon)
    r_true = ic.radius(lat, lon)
    P = U * ic.radius(lat, lon, args.z)[..., None]
    N = ic.inward_normals(P, U)
    # screen directions on the sphere: right and up, from neighbouring pixel directions
    ex = np.gradient(U, axis=1); ey = -np.gradient(U, axis=0)
    ex /= np.maximum(np.linalg.norm(ex, axis=-1, keepdims=True), 1e-12)
    ey /= np.maximum(np.linalg.norm(ey, axis=-1, keepdims=True), 1e-12)
    t = -ex + ey
    t /= np.maximum(np.linalg.norm(t, axis=-1, keepdims=True), 1e-12)
    Ld = -U * np.cos(el) + t * np.sin(el)
    sh = ic.cast_shadows(P, Ld, np.full(P.shape[:2] + (1,), np.inf), args.z, steps=24, reach=400e3)
    rr = ic.relief_shade(N, U, Ld, sh)
    s0, s1 = i0 - a, i0 - a + min(args.strip, Hpx - i0)
    rel[i0:i0 + s1 - s0] = np.where(ins, rr, np.nan)[s0:s1]
    rkm[i0:i0 + s1 - s0] = np.where(ins, r_true / 1e3, np.nan)[s0:s1]
    sat[i0:i0 + s1 - s0] = ic.sample_bmng(bm, lat, lon)[s0:s1]
    if (i0 // args.strip) % 10 == 0:
        print(f"rows {i0}/{Hpx}", flush=True)

ok = np.isfinite(rkm)
hs = ic.shade_scale(rel)
lims = [float(np.floor(np.nanpercentile(rkm, 0.1))), float(np.ceil(np.nanpercentile(rkm, 99.9)))]
bg = ic.BG


def save(rgb, name):
    rgb = np.where(ok[..., None], rgb, bg)
    Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(OUT / f"world_{name}.png", optimize=False)


save(np.repeat(np.clip(0.04 + 0.96 * hs ** 1.3, 0, 1)[..., None], 3, -1), "hillshade")
hyp = ic.hypso_rgb(np.nan_to_num(rkm, nan=lims[0]), lims) * (0.82 + 0.18 * hs[..., None])
save(ic.index_lines(rkm, hyp), "hypso")
save(ic.fuse(sat, hs), "fused")

imax = np.unravel_index(np.nanargmax(rkm), rkm.shape)
imin = np.unravel_index(np.nanargmin(rkm), rkm.shape)
XS1, YS1 = np.array([xs[imax[1]], xs[imin[1]]]), np.array([ys_all[imax[0]], ys_all[imin[0]]])
la, lo, _ = inv_ee(XS1, YS1)
facts = dict(width=W, height=Hpx, lon0=args.lon0, z=args.z, light_deg_from_inward_normal=args.elev,
             hypso_lims_km=lims, r_max_km=float(rkm[imax]), r_max_at=[float(la[0]), float(((lo[0] + 180) % 360) - 180)],
             r_min_km=float(rkm[imin]), r_min_at=[float(la[1]), float(((lo[1] + 180) % 360) - 180)],
             equator_minus_pole_km=(ic.A - ic.B) / 1e3, lmax=ic.LMAX, taper_from=ic.TAPER_FROM,
             projection="Equal Earth, mirrored (east to the left)")
(OUT / "world_facts.json").write_text(json.dumps(facts, indent=1))
print(json.dumps(facts, indent=1))
