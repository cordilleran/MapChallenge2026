"""Shared settings for Day 6: the extent of Sheet No. 16 and the data folders.

The sheet prints its graticule at the corners of the map frame:
51 deg 37' 15" N to 51 deg 24' 12" N, 116 deg 31' 52" W to 116 deg 15' 00" W.
Those four corners, read from the scan, are the first control points (01_georef.py).
"""
import os
import sys
from pathlib import Path

DAY = Path(os.environ.get("MC26_DAY06_DIR") or sys.exit("Set MC26_DAY06_DIR (see day-06/env.example)."))
SCAN = Path(os.environ.get("MC26_SHEET16") or sys.exit("Set MC26_SHEET16 (see day-06/env.example)."))
RAW = DAY / "raw-261109"
DERIVED = DAY / "derived"
OUT = Path(__file__).resolve().parents[1] / "out"

CRS = "EPSG:26911"  # NAD83 / UTM zone 11N
FT = 0.3048         # metres per foot

# Printed graticule of the map frame, degrees (north, south, west, east).
LAT_N = 51 + 37 / 60 + 15 / 3600
LAT_S = 51 + 24 / 60 + 12 / 3600
LON_W = -(116 + 31 / 60 + 52 / 3600)
LON_E = -(116 + 15 / 60)

# Download window: the frame plus about 1.5 km on each side.
BBOX_LL = (LON_W - 0.02, LAT_S - 0.015, LON_E + 0.02, LAT_N + 0.015)  # west, south, east, north

# The printing inks of the repeat (07_render.py) and the colour target of the scan (07b_scan_colour.py).
INK = {
    "paper": "#efe8d6", "brown": "#c4835c", "brown_idx": "#a8613c", "blue": "#5b8db6",
    "blue_idx": "#3d6f9c", "water": "#d3e2e8", "water_line": "#4b7fa8", "red": "#c4473b",
    "black": "#2a2724", "limit": "#163f66", "forefield": "#d9e3e3",
}
