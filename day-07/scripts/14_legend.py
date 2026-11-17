"""Day 7 step 14: the legend of the 1958 sheets, as ink plates (D326).

The Duluth sheet's own legend (lower collar), cut from the scan and separated into the same
ink plates as the map (12_htmc_inks.classify, with the Duluth sheet's reference colours), so
03_map.R prints it in the same inks and washes as the map.
Output: derived/htmc/legend_plates.tif, one byte band per plate (band names = plates), no
georeference: pixel space of the scan, 300 dpi.
No wetland plate: on these scans a marsh is a scatter of small blue tufts, mostly printed over
the woodland green, and no colour or shape rule tried on 2026-11-16 told the tufts apart from
the fringes of streams and lines at 20 m (D327).

Inputs: raw/htmc/MN_Duluth_*_1958_250000_geo.tif; derived/htmc/inks_report.json (12_htmc_inks.py).
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
DATA = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
RAW = DATA / "raw" / "htmc"
OUT = DATA / "derived" / "htmc"
HERE = Path(__file__).resolve().parent

# The legend block on the Duluth sheet, in scan pixels (col, row, width, height): from
# "LEGEND" to "Power line", read on the scan, clear of the production note on its left, the
# scale bars on its right and the border rule above
LEGEND_WINDOW = (1410, 5722, 1780, 700)


def load_inks_module():
    spec = importlib.util.spec_from_file_location("htmc_inks", HERE / "12_htmc_inks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def legend(inks):
    path = next(RAW.glob("MN_Duluth_*_1958_250000_geo.tif"))
    ds = gdal.Open(str(path))
    c, r, w, h = LEGEND_WINDOW
    a = ds.ReadAsArray(c, r, w, h).astype(np.float32)[:3]
    refs = json.loads((OUT / "inks_report.json").read_text())["refs_rgb"]
    refs = {k: {p: np.asarray(v[p], float) for p in ("paper", "green", "water", "urban")} for k, v in refs.items()}
    sid = np.zeros(a.shape[1:], np.int8)            # every pixel read as the Duluth sheet
    plates = inks.classify(a, sid, refs)
    out = gdal.GetDriverByName("GTiff").Create(str(OUT / "legend_plates.tif"), w, h, len(inks.PLATES),
                                               gdal.GDT_Byte, ["COMPRESS=DEFLATE"])
    for i, p in enumerate(inks.PLATES):
        band = out.GetRasterBand(i + 1)
        band.WriteArray(np.clip(plates[p] * 255, 0, 255).astype(np.uint8))
        band.SetDescription(p)
    out = None
    print("legend plates:", w, "x", h, "px,", ", ".join(inks.PLATES))


def main():
    inks = load_inks_module()
    legend(inks)


if __name__ == "__main__":
    main()
