"""Test surfaces for the --z0 checks (Fable review, section 2C), built to fit each entry's grid.

All fall toward the last row (row 0 is the top), so an entry's open bottom edge is the outlet.
Surfaces are defined by fraction of the grid, so the mean gradients match across entries
whatever their grid size; heights are in metres.
"""
import numpy as np
from scipy.special import erf

SCARP_A_M = 0.5          # half-height of the scarp, m
SCARP_SIGMA_CELLS = 3.0  # initial width of the scarp's slope, cells


def _yx(shape, dx):
    ny, nx = shape
    y = np.arange(ny)[:, None] * dx * np.ones((1, nx))
    x = np.ones((ny, 1)) * np.arange(nx)[None, :] * dx
    return y, x


def scarp(shape, dx):
    """C1: a smoothed step across the grid, high side at the top, centred mid-grid."""
    ny, _ = shape
    y, _ = _yx(shape, dx)
    y0, s0 = (ny - 1) * dx / 2, SCARP_SIGMA_CELLS * dx
    return 10.0 - SCARP_A_M * erf((y - y0) / (np.sqrt(2) * s0)), s0


def ramp_apron(shape, dx):
    """C2: a 15 % ramp meeting a 1 % apron at mid-grid."""
    ny, _ = shape
    y, _ = _yx(shape, dx)
    yb, L = (ny - 1) * dx / 2, (ny - 1) * dx
    return np.where(y <= yb, 0.01 * (L - yb) + 0.15 * (yb - y), 0.01 * (L - y)), int(round(yb / dx))


def basin(shape, dx):
    """C3: a closed bowl, floor 5 m below a flat rim band three cells wide on every side."""
    ny, nx = shape
    yy, xx = np.mgrid[:ny, :nx]
    r = np.maximum(np.abs(yy - (ny - 1) / 2) / ((ny - 1) / 2 - 3), np.abs(xx - (nx - 1) / 2) / ((nx - 1) / 2 - 3))
    return 5.0 * np.minimum(r, 1.0) ** 2


def hillslope(shape, dx):
    """C4: one convex-concave slope (mean gradient 8 %), a single central hollow, mirror-symmetric."""
    ny, nx = shape
    s = np.arange(ny)[:, None] / (ny - 1)
    L = (ny - 1) * dx
    H = 0.08 * L
    xc, w = (nx - 1) / 2, 0.12 * nx
    hollow = 0.05 * H * np.exp(-((np.arange(nx)[None, :] - xc) ** 2) / (2 * w * w)) * 0.5 * (1 - np.cos(np.pi * s))   # deepens downslope, so no rise at the foot
    z = H * 0.5 * (1 + np.cos(np.pi * s)) - hollow
    return z + 0 * np.arange(nx)[None, :]


SURFACES = {"scarp": scarp, "ramp": ramp_apron, "basin": basin, "hill": hillslope}
