"""Horizon angles by a convex-hull sweep along parallel grid lines (O(n) per azimuth).

Azimuth is in degrees clockwise from GRID north. Rows increase southward, columns eastward.
Each cell belongs to exactly one staircase line r = r0 + round(k*m) (lateral error <= 0.5 cell).
Cells are visited from the far end in the azimuth direction, so the hull holds only the points
"ahead" of the current cell; the horizon is the tangent from the cell to that upper hull.
Returns the horizon angle (radians; -pi/2 where nothing is ahead) and the distance (m) to the
tangent point (0 where nothing is ahead).
"""
import math

import numpy as np
from numba import njit, prange


@njit(parallel=True, cache=True)
def _sweep(z, m, sgn, step):
    ny, nx = z.shape
    ang = np.full((ny, nx), -np.pi / 2, np.float32)
    dist = np.zeros((ny, nx), np.float32)
    offs = np.empty(nx, np.int64)
    for k in range(nx):
        offs[k] = int(math.floor(k * m + 0.5))
    rmin = -offs.max()
    rmax = ny - 1 - offs.min()
    for r0 in prange(rmin, rmax + 1):
        hs = np.empty(nx, np.float64)
        hz = np.empty(nx, np.float64)
        n = 0
        for kk in range(nx):
            k = nx - 1 - kk if sgn > 0 else kk
            r = r0 + offs[k]
            if r < 0 or r >= ny:
                continue
            zp = z[r, k]
            sp = sgn * k * step
            while n >= 2:
                s1 = (hz[n - 1] - zp) / (hs[n - 1] - sp)
                s2 = (hz[n - 2] - zp) / (hs[n - 2] - sp)
                if s1 <= s2:
                    n -= 1
                else:
                    break
            if n >= 1:
                d = hs[n - 1] - sp
                ang[r, k] = math.atan((hz[n - 1] - zp) / d)
                dist[r, k] = d
            hs[n] = sp
            hz[n] = zp
            n += 1
    return ang, dist


def horizon(z, az_deg, cell):
    """Horizon toward grid azimuth az_deg for grid z (float32, no NaN) with square cells."""
    a = math.radians(az_deg)
    dx, drow = math.sin(a), -math.cos(a)  # column and row steps of the direction
    if abs(dx) >= abs(drow):
        m = drow / dx
        ang, dist = _sweep(z, m, 1 if dx > 0 else -1, cell * math.sqrt(1 + m * m))
        return ang, dist
    m = dx / drow
    ang, dist = _sweep(np.ascontiguousarray(z.T), m, 1 if drow > 0 else -1, cell * math.sqrt(1 + m * m))
    return np.ascontiguousarray(ang.T), np.ascontiguousarray(dist.T)


def brute(z, r, c, az_deg, cell, step=0.5):
    """Reference: ray march every `step` cells with bilinear sampling, to the grid edge."""
    a = math.radians(az_deg)
    dx, drow = math.sin(a), -math.cos(a)
    ny, nx = z.shape
    best = -np.pi / 2
    t = step
    while True:
        rr, cc = r + drow * t, c + dx * t
        if rr < 0 or cc < 0 or rr > ny - 1 or cc > nx - 1:
            break
        r0, c0 = min(int(rr), ny - 2), min(int(cc), nx - 2)
        fr, fc = rr - r0, cc - c0
        zz = (z[r0, c0] * (1 - fc) + z[r0, c0 + 1] * fc) * (1 - fr) + (z[r0 + 1, c0] * (1 - fc) + z[r0 + 1, c0 + 1] * fc) * fr
        best = max(best, math.atan((zz - z[r, c]) / (t * cell)))
        t += step
    return best


FAR_MIN_M = 150.0  # far-field tangents closer than this are left to the LiDAR


@njit(parallel=True, cache=True)
def far_on_near(H, d, rx0, ry0, rcell, z, nx0, ny0, ncell, hn):
    """Max of near horizon hn and the far horizon carried from the regional grid (bilinear)."""
    ny, nx = z.shape
    RY, RX = H.shape
    out = np.empty_like(hn)
    for r in prange(ny):
        y = ny0 - (r + 0.5) * ncell
        fr = (ry0 - y) / rcell - 0.5
        for c in range(nx):
            x = nx0 + (c + 0.5) * ncell
            fc = (x - rx0) / rcell - 0.5
            i, j = int(math.floor(fr)), int(math.floor(fc))
            h = hn[r, c]
            if 0 <= i < RY - 1 and 0 <= j < RX - 1:
                a, b = fr - i, fc - j
                dd = (d[i, j] * (1 - b) + d[i, j + 1] * b) * (1 - a) + (d[i + 1, j] * (1 - b) + d[i + 1, j + 1] * b) * a
                mn = min(min(d[i, j], d[i, j + 1]), min(d[i + 1, j], d[i + 1, j + 1]))
                if mn >= FAR_MIN_M:
                    HH = (H[i, j] * (1 - b) + H[i, j + 1] * b) * (1 - a) + (H[i + 1, j] * (1 - b) + H[i + 1, j + 1] * b) * a
                    hf = math.atan((HH - z[r, c]) / dd)
                    if hf > h:
                        h = hf
            out[r, c] = h
    return out


@njit(parallel=True, cache=True)
def accumulate(acc, h, e, cum):
    ny, nx = h.shape
    for r in prange(ny):
        for c in range(nx):
            acc[r, c] += cum[np.searchsorted(e, h[r, c])]




@njit(parallel=True, cache=True)
def accumulate_weeks(acc, h, e, wk, k):
    """acc[R, C, week] (uint32, units of one 5-minute position) for a grid k times coarser than h:
    each fine cell adds the positions below its horizon to its coarse cell."""
    ny, nx = h.shape
    NY, NX = acc.shape[0], acc.shape[1]
    for R in prange(NY):
        for r in range(R * k, min(R * k + k, ny)):
            for c in range(nx):
                C = c // k
                if C >= NX:
                    continue
                n = np.searchsorted(e, h[r, c])
                for i in range(n):
                    acc[R, C, wk[i]] += 1
