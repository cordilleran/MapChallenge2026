"""Day 15 (static): the ground seen from the centre of the Earth, close up on one focus, three ways.

  hillshade  bare inverted hillshade, lit by a lamp inside the Earth
  hypso      colour by distance from the centre, index lines every 1 km, labelled every 5 km
  fused      the hillshade lightly fused with Blue Marble NG

Projection (D390): Lambert azimuthal equal-area on the focus, mirrored (east to the LEFT,
as seen from inside), square, full bleed. The lamp sits inside the Earth at LAMP_R of the
mean radius, toward the upper left of the frame, so its light rakes across the underside
of the ground (D392). Colours share the world map's range (world_facts.json).

usage: render_inside.py RAW_STATIC_DIR OUT_DIR NAME LAT LON [--px 1800] [--z 25]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script dir
import inside_common as ic  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("raw"); ap.add_argument("out"); ap.add_argument("name")
ap.add_argument("lat", type=float); ap.add_argument("lon", type=float)
ap.add_argument("--px", type=int, default=1800)
ap.add_argument("--z", type=float, default=25.0)
ap.add_argument("--half", type=float, default=0.85)       # half-width in unit-sphere LAEA units
ap.add_argument("--lamp-r", type=float, default=0.72)
ap.add_argument("--lamp-off", type=float, default=0.5)
args = ap.parse_args()
RAW, OUT = Path(args.raw), Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)
ic.load(OUT)
LIMS = json.loads((OUT / "world_facts.json").read_text())["hypso_lims_km"]
p0, l0 = np.radians(args.lat), np.radians(args.lon)


def inv_laea(xs, ys):
    """Screen (x right, y up) -> geocentric (lat, lon). Mirrored: east is to the left."""
    x = -xs
    rho = np.hypot(x, ys)
    c = 2 * np.arcsin(np.clip(rho / 2, 0, 1))
    rho = np.where(rho == 0, 1e-12, rho)
    lat = np.arcsin(np.cos(c) * np.sin(p0) + ys * np.sin(c) * np.cos(p0) / rho)
    lon = l0 + np.arctan2(x * np.sin(c), rho * np.cos(p0) * np.cos(c) - ys * np.sin(p0) * np.sin(c))
    return np.degrees(lat), np.degrees(lon)


n = args.px
s = np.linspace(-args.half, args.half, n)
XS, YS = np.meshgrid(s, s[::-1])
LAT, LON = inv_laea(XS, YS)
U = ic.unit(LAT, LON)
r_true = ic.radius(LAT, LON)
P = U * ic.radius(LAT, LON, args.z)[..., None]
N = ic.inward_normals(P, U)

lat_l, lon_l = inv_laea(np.array(-args.lamp_off), np.array(args.lamp_off))
LAMP = ic.unit(lat_l, lon_l) * args.lamp_r * ic.R_MEAN
Ld = LAMP - P
dist = np.linalg.norm(Ld, axis=-1, keepdims=True)
Ld /= dist
sh = np.concatenate([ic.cast_shadows(P[i:i + 150], Ld[i:i + 150], dist[i:i + 150], args.z, steps=40, reach=900e3)
                     for i in range(0, n, 150)])
rel = ic.relief_shade(N, U, Ld, sh)
flat = np.clip(np.sum(-U * Ld, axis=-1), 1e-3, 1)
pool = (flat / flat.max()) ** 1.5                            # the lantern's pool of light
hs = np.clip(ic.shade_scale(rel) * (0.45 + 0.75 * pool), 0, 1)

imax = np.unravel_index(np.argmax(r_true), r_true.shape)
imin = np.unravel_index(np.argmin(r_true), r_true.shape)
INK, BG = "#d9d4c7", "#07080c"


def save(img, fname, extra=None):
    fig = plt.figure(figsize=(8, 8), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    ax.imshow(img, extent=[-args.half, args.half, -args.half, args.half], interpolation="lanczos")
    if extra:
        extra(ax)
    for idx, txt, off in ((imax, "farthest", (10, -18)), (imin, "nearest", (10, 8))):
        x, y = XS[idx], YS[idx]
        ax.plot(x, y, marker="o", ms=6, mfc="none", mec=INK, mew=1.1)
        near_right, near_low = x > 0.55 * args.half, y < -0.8 * args.half     # keep the label inside the frame
        off = (-10 if near_right else 10, 10 if near_low else off[1])
        ax.annotate(f"{txt} {r_true[idx] / 1e3:,.1f} km", (x, y), xytext=off, textcoords="offset points", color=INK,
                    fontsize=8.5, ha="right" if near_right else "left", path_effects=[pe.withStroke(linewidth=2.5, foreground=BG)])
    ax.set_xlim(-args.half, args.half); ax.set_ylim(-args.half, args.half)
    fig.savefig(OUT / fname, dpi=n / 8, facecolor=BG)
    plt.close(fig)


save(np.repeat(np.clip(0.04 + 0.96 * hs ** 1.3, 0, 1)[..., None], 3, -1), f"{args.name}_hillshade.png")


def labels(ax):
    km = r_true / 1e3
    lv5 = np.arange(np.ceil(km.min() / 5) * 5, km.max(), 5.0)
    cs = ax.contour(XS, YS, km, levels=lv5, colors="none")
    ax.clabel(cs, fmt=lambda v: f"{v:,.0f}", fontsize=7, colors=INK, inline_spacing=1)


hyp = ic.hypso_rgb(r_true / 1e3, LIMS) * (0.82 + 0.18 * hs[..., None])
save(ic.index_lines(r_true / 1e3, hyp), f"{args.name}_hypso.png", labels)
bm = np.asarray(Image.open(RAW / "bmng_200408_5400.jpg").convert("RGB"), np.float32) / 255.0
save(ic.fuse(ic.sample_bmng(bm, LAT, LON), hs), f"{args.name}_fused.png")

facts = dict(focus=[args.lat, args.lon], r_max_km=float(r_true[imax] / 1e3), r_max_at=[float(LAT[imax]), float(LON[imax])],
             r_min_km=float(r_true[imin] / 1e3), r_min_at=[float(LAT[imin]), float(LON[imin])],
             lamp_lat_lon=[float(lat_l), float(lon_l)], lamp_r=args.lamp_r, z=args.z, px=n, half=args.half,
             hypso_lims_km=LIMS, edge_mid_deg_from_focus=float(np.degrees(2 * np.arcsin(args.half / 2))))
(OUT / f"{args.name}_facts.json").write_text(json.dumps(facts, indent=1))
print(json.dumps(facts, indent=1))
