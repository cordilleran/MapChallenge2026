"""Pixel <-> UTM model for the scan of Sheet No. 16.

Model: the four printed graticule corners (read on the NAD27 datum), bilinear between them,
plus one shift equal to the mean residual at the 11 check stations (data/check_stations.json).
Fitting an affine or more points did not lower the held-out error (01_georef.py prints it).

Pixel coordinates here were read on the Internet Archive's JPEG (2315 x 2871 px, REF_WIDTH). The
master TIFF and the JPEG 2000 are the same scan at 9260 x 11484 px, exactly four times larger, so
gcps() scales the corners to whichever image is given as MC26_SHEET16.
"""
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from sheet import CRS, LAT_N, LAT_S, LON_E, LON_W

REF_WIDTH = 2315  # width in pixels of the image the coordinates below were read on

# Corners of the map frame on the scan, in scan pixels (x right, y down).
CORNER_PX = {"NW": (230.0, 258.0), "NE": (2069.0, 258.0), "SW": (231.0, 2565.0), "SE": (2076.0, 2562.0)}
CORNER_LL = {"NW": (LON_W, LAT_N), "NE": (LON_E, LAT_N), "SW": (LON_W, LAT_S), "SE": (LON_E, LAT_S)}
STATIONS = Path(__file__).resolve().parents[1] / "data" / "check_stations.json"


def corner_utm(datum="EPSG:4267"):
    t = Transformer.from_crs(datum, CRS, always_xy=True)
    return {k: t.transform(*v) for k, v in CORNER_LL.items()}


def _coef(corners):
    a = np.array([[1, x, y, x * y] for x, y in CORNER_PX.values()])
    e = np.linalg.solve(a, [corners[k][0] for k in CORNER_PX])
    n = np.linalg.solve(a, [corners[k][1] for k in CORNER_PX])
    return e, n


def corners_only(px, py, datum="EPSG:4267"):
    e, n = _coef(corner_utm(datum))
    px, py = np.asarray(px, float), np.asarray(py, float)
    v = np.stack([np.ones_like(px), px, py, px * py])
    return np.tensordot(e, v, 1), np.tensordot(n, v, 1)


def stations():
    return json.loads(STATIONS.read_text())["stations"]


def residuals(shift=(0.0, 0.0)):
    """Model minus check point, metres, for every station."""
    s = stations()
    e, n = corners_only([p["px"] for p in s], [p["py"] for p in s])
    return np.column_stack([e + shift[0] - [p["E"] for p in s], n + shift[1] - [p["N"] for p in s]])


def mean_shift():
    return tuple(-residuals().mean(axis=0))


def model(px, py):
    """Scan pixel (reference frame) to UTM: bilinear between the corners, plus the mean shift."""
    e, n = corners_only(px, py)
    de, dn = mean_shift()
    return e + de, n + dn


def gcps(scale=1.0):
    """The four corners with the shift applied: (px, py, E, N); px, py multiplied by scale."""
    c = corner_utm()
    de, dn = mean_shift()
    return [(CORNER_PX[k][0] * scale, CORNER_PX[k][1] * scale, c[k][0] + de, c[k][1] + dn) for k in CORNER_PX]


def grid_gcps(scale=1.0, n=9):
    """An n x n grid of control points from model() over the map frame, for an exact warp of the model."""
    xs = np.linspace(min(v[0] for v in CORNER_PX.values()), max(v[0] for v in CORNER_PX.values()), n)
    ys = np.linspace(min(v[1] for v in CORNER_PX.values()), max(v[1] for v in CORNER_PX.values()), n)
    px, py = (a.ravel() for a in np.meshgrid(xs, ys))
    e, nn = model(px, py)
    return [(x * scale, y * scale, a, b) for x, y, a, b in zip(px, py, e, nn, strict=True)]
