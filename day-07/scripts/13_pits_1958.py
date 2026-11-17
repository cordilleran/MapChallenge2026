"""Screen the 1958 sheets for open-pit mine ground on the Mesabi Range; write a check image only.

Inputs:  $MC26_DAY07_DATA/derived/htmc/sheets1958_utm15.tif, ink_brown.tif, ink_green.tif
         (11_htmc_mosaic.py, 12_htmc_inks.py); $MC26_DAY07_DATA/raw/osm_pits.gpkg (modern pits, for context)
Output:  $MC26_DAY07_DATA/derived/htmc/check_pits_1958.png
         top: the scan, Hibbing to Eveleth; bottom: candidate cells (magenta) and modern OSM pits (blue)
How the 1958 sheets show the mines: no pit fill, colour or hachure. A mine is a crossed-pick symbol
with the word "Iron", and the pit is a tangle of closely spaced closed contours (brown ink) in an
unwooded clearing; dumps look the same; "Tailings pond" is lettered. So the only automatic rule is
contour density in clearings: share of brown-ink pixels (> 0.2) in a 300 m window above DENS, where
at least CLEAR of the window has no woodland tint. It finds Hull-Rust, Shenango and the Virginia pits,
but also urban fringes, road verges and rough ground, and it cannot tell pits from dumps.
So no polygons are written: pits_1958.gpkg needs tracing by hand (see the Day 7 report).
"""
import os
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr
from PIL import Image
from scipy import ndimage as ndi

gdal.UseExceptions()
ogr.UseExceptions()

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
DATA = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
OUT = DATA / "derived" / "htmc"
WIN = (-93.05, 47.40, -92.45, 47.58)   # lon/lat: Hibbing to Eveleth
DENS, CLEAR, SIZE = 0.22, 0.7, 15


def main():
    ds = gdal.Open(str(OUT / "sheets1958_utm15.tif"))
    gt = ds.GetGeoTransform()
    g, u = osr.SpatialReference(), osr.SpatialReference()
    g.ImportFromEPSG(4326)
    u.ImportFromEPSG(26915)
    for s in (g, u):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(g, u)
    x0, y1, _ = ct.TransformPoint(WIN[0], WIN[1])
    x1, y0, _ = ct.TransformPoint(WIN[2], WIN[3])
    px0, py0 = int((x0 - gt[0]) / gt[1]), int((y0 - gt[3]) / gt[5])
    w, h = int((x1 - x0) / gt[1]), int((y0 - y1) / gt[1])
    rgb = ds.ReadAsArray(px0, py0, w, h)
    brown = gdal.Open(str(OUT / "ink_brown.tif")).ReadAsArray(px0, py0, w, h) / 255
    green = gdal.Open(str(OUT / "ink_green.tif")).ReadAsArray(px0, py0, w, h) / 255
    dens = ndi.uniform_filter((brown > 0.2).astype(float), SIZE)
    clear = ndi.uniform_filter((green < 0.2).astype(float), SIZE)
    cand = (dens > DENS) & (clear > CLEAR)
    mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Byte)
    mem.SetGeoTransform((gt[0] + px0 * gt[1], gt[1], 0, gt[3] + py0 * gt[5], 0, gt[5]))
    mem.SetProjection(ds.GetProjection())
    src = ogr.Open(str(DATA / "raw" / "osm_pits.gpkg"))
    gdal.RasterizeLayer(mem, [1], src.GetLayer(0), burn_values=[1])
    osm = mem.ReadAsArray() > 0
    img = np.moveaxis(rgb, 0, -1).astype(float)
    ov = img.copy()
    ov[cand] = ov[cand] * 0.4 + np.array([255, 0, 255]) * 0.6
    ov[osm & ~ndi.binary_erosion(osm, iterations=2)] = [0, 0, 255]
    Image.fromarray(np.ascontiguousarray(np.concatenate([img, ov], 0).astype(np.uint8))) \
        .save(OUT / "check_pits_1958.png", optimize=True)
    print(f"window {w} x {h} px; candidate share {cand.mean():.4f}; OSM pit share {osm.mean():.4f}; "
          f"OSM pit px also candidate {(cand & osm).sum() / max(osm.sum(), 1):.3f}")


if __name__ == "__main__":
    main()
