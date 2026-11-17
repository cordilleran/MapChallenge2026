"""Check the georeference of the 1958 mosaic against modern water edges; report offsets in metres.

Inputs:  $MC26_DAY07_DATA/derived/htmc/ink_water.tif (12_htmc_inks.py; the 1958 water tint)
         NOAA NCEI Lake Superior grid (MC26_NCEI_SUPERIOR, else the copy step 01 downloads):
             0 m contour = modern shoreline, east of 92.20 W
         $MC26_DAY07_DATA/raw/osm_clip.gpkg, layer multipolygons, natural=water (inland lakes)
Output:  $MC26_DAY07_DATA/derived/htmc/georef_check.json
Method: the 1958 shoreline is the edge of the water plate (water tint >= 0.5 of the sheet's
reference). For each sheet, distance from every 1958 edge pixel to the nearest modern edge
(Euclidean distance transform, 20 m grid); edges further than CAP_M from any modern edge are
taken as unmatched (lakes drained, flooded or mapped differently) and dropped. Reported: median and
90th percentile distance, and the shift (dx, dy) that minimises the median distance (grid search,
+-300 m, 20 m step) as an estimate of a systematic offset. Distances are unsigned, so a median
of ~1 pixel is the floor set by the 20 m grid and the line-drawn shores.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr
from scipy import ndimage as ndi

gdal.UseExceptions()

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
DATA = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
OUT = DATA / "derived" / "htmc"
LLD = Path(os.environ.get("MC26_NCEI_SUPERIOR", DATA / "raw" / "superior_lld" / "superior_lld.tif")).expanduser()  # as config.R
OSM = DATA / "raw" / "osm_clip.gpkg"
CAP_M = 400.0
MIN_LAKE_M2 = 2e5
SHEETS = ("Duluth", "Ashland", "Hibbing", "Two Harbors")
BOX = (-93.30, 46.40, -91.30, 47.72)


def grid_like(ref):
    drv = gdal.GetDriverByName("MEM")
    d = drv.Create("", ref.RasterXSize, ref.RasterYSize, 1, gdal.GDT_Byte)
    d.SetGeoTransform(ref.GetGeoTransform())
    d.SetProjection(ref.GetProjection())
    return d


def edges(mask):
    return mask & ~ndi.binary_erosion(mask)


def main():
    wds = gdal.Open(str(OUT / "ink_water.tif"))
    gt, w, h = wds.GetGeoTransform(), wds.RasterXSize, wds.RasterYSize
    water = wds.ReadAsArray() >= 128
    water = ndi.binary_opening(water, iterations=1)
    old_edge = edges(water)
    # modern Lake Superior: 0 m contour of the NOAA grid, warped to the mosaic grid
    lld = gdal.Warp("", str(LLD), format="MEM", dstSRS=wds.GetProjection(), outputBounds=(gt[0], gt[3] + gt[5] * h,
                    gt[0] + gt[1] * w, gt[3]), xRes=gt[1], yRes=-gt[5], resampleAlg="bilinear", dstNodata=-9999)
    z = lld.ReadAsArray()
    sup = (z < 0) & (z > -9000)
    sup_valid = z > -9000
    # modern inland lakes from OSM
    d = grid_like(wds)
    src = ogr.Open(str(OSM))
    lyr = src.ExecuteSQL("SELECT geom FROM multipolygons WHERE \"natural\"='water' AND "
                         f"ST_Intersects(geom, BuildMbr({BOX[0] - .1},{BOX[1] - .1},{BOX[2] + .1},{BOX[3] + .1}))",
                         dialect="SQLITE")
    gdal.RasterizeLayer(d, [1], lyr, burn_values=[1], options=["ALL_TOUCHED=FALSE"])
    src.ReleaseResultSet(lyr)
    lakes = d.ReadAsArray() > 0
    lab, n = ndi.label(lakes)
    size = ndi.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1)) * gt[1] ** 2
    lakes = np.isin(lab, np.nonzero(size >= MIN_LAKE_M2)[0] + 1)
    modern_edge = edges(lakes) | (edges(sup) & ndi.binary_erosion(sup_valid, iterations=2))
    dist = ndi.distance_transform_edt(~modern_edge) * gt[1]
    # sheet id
    ct = osr.SpatialReference()
    ct.ImportFromWkt(wds.GetProjection())
    g = osr.SpatialReference()
    g.ImportFromEPSG(4326)
    g.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(ct, g)
    ys, xs = np.nonzero(old_edge)
    ll = np.array(tr.TransformPoints(np.column_stack([gt[0] + gt[1] * (xs + .5), gt[3] + gt[5] * (ys + .5)])))
    sid = (ll[:, 0] > -92).astype(int) + 2 * (ll[:, 1] > 47)
    inbox = (ll[:, 0] >= BOX[0]) & (ll[:, 0] <= BOX[2]) & (ll[:, 1] >= BOX[1]) & (ll[:, 1] <= BOX[3])
    east_sup = ll[:, 0] > -92.20
    rep = {"cap_m": CAP_M, "min_lake_m2": MIN_LAKE_M2, "sheets": {}}
    shifts = np.arange(-15, 16)
    for s, name in enumerate(SHEETS):
        for label, extra in (("all", np.ones_like(inbox)), ("superior_shore", east_sup)):
            sel = inbox & (sid == s) & extra
            if label == "superior_shore":
                near_sup = ndi.distance_transform_edt(~sup) * gt[1]
                sel &= near_sup[ys, xs] < CAP_M if sup.any() else False
            if sel.sum() < 200:
                continue
            yy, xx = ys[sel], xs[sel]
            dd = dist[yy, xx]
            ok = dd <= CAP_M
            best = (np.inf, 0, 0)
            for dy in shifts:
                for dx in shifts:
                    y2, x2 = np.clip(yy + dy, 0, h - 1), np.clip(xx + dx, 0, w - 1)
                    v = dist[y2, x2]
                    v = v[v <= CAP_M]
                    m = np.median(v) if len(v) > 0.5 * len(yy) else np.inf
                    if m < best[0]:
                        best = (m, dx, dy)
            y2, x2 = np.clip(yy + best[2], 0, h - 1), np.clip(xx + best[1], 0, w - 1)
            v2 = dist[y2, x2]
            v2 = v2[v2 <= CAP_M]
            rep["sheets"].setdefault(name, {})[label] = {
                "edge_px": int(sel.sum()), "matched_share": round(float(ok.mean()), 3),
                "median_m": round(float(np.median(dd[ok])), 1), "p90_m": round(float(np.percentile(dd[ok], 90)), 1),
                "best_shift_east_north_m": [int(best[1] * gt[1]), int(-best[2] * gt[1])],
                "median_after_shift_m": round(float(np.median(v2)), 1),
                "p90_after_shift_m": round(float(np.percentile(v2, 90)), 1)}
    (OUT / "georef_check.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
