"""Shared pieces for the Day 15 static maps: the ground seen from the centre of the Earth.

Distance from the centre: r = r_ellipsoid(geodetic lat) + N (EGM2008) + h (Earth2014 BED).
Directions are geocentric (the viewer stands at the centre); the data are sampled at the
geodetic latitude of each direction. Relief is exaggerated by Z for shading only. The maps are equal-area over directions seen from
the centre (equal solid angle: every patch of map is the same patch of sky), not over the
ellipsoid's surface.
"""
from pathlib import Path

import numpy as np
import pyshtools as pysh
from scipy.ndimage import binary_dilation, gaussian_filter
from cmcrameri import cm

A, F = 6378137.0, 1 / 298.257223563            # WGS84
B = A * (1 - F)
U0, OMEGA = 62636851.7146, 7292115e-11
R_MEAN = 6371000.0
LMAX, TAPER_FROM = 2160, 1950                   # Earth2014 at full degree, gentle roll-off at the top
BG = np.array([7, 8, 12]) / 255.0               # page ground, #07080c

H = NG = None


def load(cache_dir):
    """Bedrock heights (m above MSL) and geoid (m), both on extended DH2 grids (lat 90..-90, lon 0..360)."""
    global H, NG
    cache = Path(cache_dir) / f"_cache_bed{LMAX}t{TAPER_FROM}_geoid359.npz"
    if cache.exists():
        c = np.load(cache)
        H, NG = c["H"], c["NG"]
        return
    clm = pysh.datasets.Earth.Earth2014.bedrock(lmax=LMAX)
    l = np.arange(LMAX + 1)
    w = np.where(l <= TAPER_FROM, 1.0, np.cos(0.5 * np.pi * (l - TAPER_FROM) / (LMAX - TAPER_FROM)) ** 2)
    clm.coeffs *= w[None, :, None]
    H = clm.expand(grid="DH2", extend=True).data.astype(np.float32)
    egm = pysh.datasets.Earth.EGM2008(lmax=359)
    NG = egm.geoid(potref=U0, a=A, f=F, omega=OMEGA, grid="DH2", extend=True).geoid.data.astype(np.float32)
    np.savez(cache, H=H, NG=NG)


def bilinear(grid, lat, lon):
    if grid is None:
        raise RuntimeError("call inside_common.load() first")
    ny, nx = grid.shape
    y = (90.0 - lat) / 180.0 * (ny - 1)
    x = np.mod(lon, 360.0) / 360.0 * (nx - 1)
    y0 = np.clip(np.floor(y).astype(np.int64), 0, ny - 2)
    x0 = np.clip(np.floor(x).astype(np.int64), 0, nx - 2)
    fy, fx = y - y0, x - x0
    g = grid
    return ((g[y0, x0] * (1 - fx) + g[y0, x0 + 1] * fx) * (1 - fy)
            + (g[y0 + 1, x0] * (1 - fx) + g[y0 + 1, x0 + 1] * fx) * fy)


def geodetic(psi):
    return np.degrees(np.arctan(np.tan(np.radians(psi)) / (1 - F) ** 2))


def r_ellipsoid(phi):
    c, s = np.cos(np.radians(phi)), np.sin(np.radians(phi))
    return np.sqrt(((A * A * c) ** 2 + (B * B * s) ** 2) / ((A * c) ** 2 + (B * s) ** 2))


def radius(psi, lon, z=1.0):
    phi = geodetic(psi)
    return r_ellipsoid(phi) + bilinear(NG, phi, lon) + z * bilinear(H, phi, lon)


def unit(psi, lon):
    p, l = np.radians(psi), np.radians(lon)
    return np.stack([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)], axis=-1)


def to_lonlat(v):
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    return np.degrees(np.arcsin(np.clip(v[..., 2], -1, 1))), np.degrees(np.arctan2(v[..., 1], v[..., 0]))


def inward_normals(P, U):
    """Normals of the exaggerated surface P (rows x cols x 3), turned to face the centre."""
    N = np.cross(np.gradient(P, axis=1), np.gradient(P, axis=0))
    N /= np.linalg.norm(N, axis=-1, keepdims=True)
    return N * np.sign(np.sum(N * -U, axis=-1))[..., None]


def cast_shadows(P, Ld, dist, z, steps=32, reach=600e3):
    """1 where lit, 0 where the ray toward the light leaves the cavity first (the ground
    bulges inward between the point and the light: a trench or basin seen from below)."""
    blocked = np.zeros(P.shape[:2], bool)
    for t in np.geomspace(3e3, reach, steps):
        Q = P + Ld * np.minimum(t, dist)
        la, lo = to_lonlat(Q)
        blocked |= np.linalg.norm(Q, axis=-1) > radius(la, lo, z) + 1.0
    return (~blocked).astype(np.float32)


def relief_shade(N, U, Ld, sh):
    """Shading relative to smooth ground under the same light: log ratio, so flat ground is 0."""
    lam = np.clip(np.sum(N * Ld, axis=-1), 0, 1)
    flat = np.clip(np.sum(-U * Ld, axis=-1), 1e-3, 1)
    return np.log(np.maximum(lam / flat, 1e-3)) + np.log(0.3 + 0.7 * gaussian_filter(sh, 1.0))


def hypso_rgb(r_km, lims):
    return cm.batlow(np.clip((r_km - lims[0]) / (lims[1] - lims[0]), 0, 1))[..., :3]


def index_lines(r_km, rgb, minor=1.0, major=5.0):
    """Raster contour lines where floor(r / step) changes between valid neighbours: thin every km,
    bold every 5. NaN marks pixels off the map, which draw no line."""
    ok = np.isfinite(r_km)
    def edges(step):
        k = np.floor(np.where(ok, r_km, 0) / step)
        e = np.zeros(r_km.shape, bool)
        e[:, 1:] |= (k[:, 1:] != k[:, :-1]) & ok[:, 1:] & ok[:, :-1]
        e[1:, :] |= (k[1:, :] != k[:-1, :]) & ok[1:, :] & ok[:-1, :]
        return e
    e1, e5 = edges(minor), edges(major)
    e5 = binary_dilation(e5, structure=np.array([[0, 0, 0], [0, 1, 1], [0, 1, 0]], bool))
    out = rgb.copy()
    out[e1] = out[e1] * 0.55 + BG * 0.45
    out[e5] = out[e5] * 0.12 + BG * 0.88
    return out


def fuse(sat, hs):
    """Satellite colour under the hillshade; the second term lifts relief into the dark ocean."""
    return np.clip(sat * (0.55 + 0.7 * hs[..., None])
                   + 0.16 * (hs[..., None] - 0.35) * (1 - sat.mean(-1, keepdims=True)) ** 2, 0, 1)


def sample_bmng(bm, psi, lon):
    bh, bw = bm.shape[:2]
    phi = geodetic(psi)
    yy = np.clip(((90 - phi) / 180 * bh - 0.5).astype(np.int64), 0, bh - 1)
    xx = np.clip((np.mod(lon + 180, 360) / 360 * bw - 0.5).astype(np.int64), 0, bw - 1)
    return bm[yy, xx]


def shade_scale(rel, q=92.0):
    """Relief log-ratio to 0..1 with flat ground at 0.5: tanh on a symmetric scale, so a few
    deep shadows cannot push the whole image toward white."""
    s = np.nanpercentile(np.abs(rel), q) / 1.2
    return 0.5 + 0.5 * np.tanh(np.nan_to_num(rel) / s)
