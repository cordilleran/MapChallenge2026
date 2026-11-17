"""Mosaic the four 1958 HTMC sheets into one RGB raster in NAD83 / UTM 15N (EPSG:26915).

Inputs:  $MC26_DAY07_DATA/raw/htmc/*.tif (10_htmc_fetch.py); each sheet is georeferenced by USGS in a
         NAD27 transverse Mercator centred on the sheet.
Outputs: $MC26_DAY07_DATA/derived/htmc/
         sheets1958_utm15.tif     RGB, 20 m, the Day 7 box padded by 0.08 degrees
         sheets1958_seamfill.tif  byte mask, 1 where the seam gap between sheets was filled
         mosaic_report.json       neatline check, datum operation, extent, counts
Method:
1. Neatline. Each sheet spans 1 x 2 degrees of the NAD27 graticule. The corners and 9 points on
   each edge were measured on the scans (neatline_check below): the printed neatline lies within
   about 2 scan pixels (~45 m) of the graticule computed from the USGS georeference.
   Each sheet is cut along its graticule, inset by INSET_M so that no neatline ink survives;
   the gap (2 x INSET_M) is filled from the neighbouring pixels (gdal FillNodata) and flagged.
2. Datum. NAD27 -> NAD83 by EPSG:1174 "NAD27 to WGS 84 (5)" (geocentric translation -9, 161, 179 m;
   area of use: CONUS east of the Mississippi including Minnesota; accuracy 11 m), with WGS 84 taken as
   NAD83(1986) (equal by definition at ~1 m). The NADCON grids are not installed and may not be
   fetched; PROJ's default would otherwise use the Canadian NTv2 grid where it reaches and a
   zero-shift ballpark elsewhere, which differ by ~15 m inside the frame. So the pipeline is explicit.
3. Warp: bilinear, 20 m (scan pixel 21.17 m = 300 dpi at 1:250,000; 20 m keeps the 1-3 pixel
   line work; 25 m would merge adjacent lines).
Rerun-safe: skips if sheets1958_utm15.tif exists.
"""
import json
import os
import sys
import subprocess
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
DATA = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
RAW = DATA / "raw" / "htmc"
OUT = DATA / "derived" / "htmc"
WORK = OUT / "_work"
MOSAIC = OUT / "sheets1958_utm15.tif"
BOX = (-93.30, 46.40, -91.30, 47.72)   # lon/lat, WGS84 (final frame, 11-16)
PAD = 0.08
RES = 20.0
INSET_M = 75.0                          # ~3.5 scan pixels from the graticule line
DST = "EPSG:26915"
HELMERT = "+x=-9 +y=161 +z=179"        # EPSG:1174
SHEETS = {  # file: (south, north, west, east), NAD27 degrees
    "MN_Duluth_804590_1958_250000_geo.tif": (46, 47, -94, -92),
    "WI_Ashland_801370_1958_250000_geo.tif": (46, 47, -92, -90),
    "MN_Hibbing_804696_1958_250000_geo.tif": (47, 48, -94, -92),
    "MN_Two_Harbors_805403_1958_250000_geo.tif": (47, 48, -92, -90),
}


def srs(code):
    s = osr.SpatialReference()
    s.SetFromUserInput(code)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def frame(box, pad=0.0, n=200):
    """UTM bounding rectangle of the densified lon/lat box."""
    w, s, e, nn = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    t = np.linspace(0, 1, n)
    lon = np.concatenate([w + (e - w) * t, np.full(n, e), e - (e - w) * t, np.full(n, w)])
    lat = np.concatenate([np.full(n, s), s + (nn - s) * t, np.full(n, nn), nn - (nn - s) * t])
    ct = osr.CoordinateTransformation(srs("EPSG:4326"), srs(DST))
    xy = np.array(ct.TransformPoints(np.column_stack([lon, lat])))[:, :2]
    return xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max()


def pipeline(sheet_srs):
    """PROJ pipeline: sheet NAD27 TM metres -> NAD83 UTM 15N metres via EPSG:1174."""
    p4 = sheet_srs.ExportToProj4()
    assert "+datum=NAD27" in p4, p4   # else PROJ would add its own grid shift to the Helmert step
    p4 = p4.replace("+datum=NAD27", "+ellps=clrk66").replace("+no_defs", "")
    p4 = p4.replace("+units=m", "").strip()
    return ("+proj=pipeline +step +inv " + p4 + " +step +proj=push +v_3 +step +proj=cart +ellps=clrk66"
            f" +step +proj=helmert {HELMERT} +step +inv +proj=cart +ellps=GRS80 +step +proj=pop +v_3"
            " +step +proj=utm +zone=15 +ellps=GRS80")


def graticule(ds, bounds, n=100):
    """The sheet's NAD27 graticule rectangle in its own CRS (same datum, no shift)."""
    s, nn, w, e = bounds
    t = np.linspace(0, 1, n)
    lon = np.concatenate([w + (e - w) * t, np.full(n, e), e - (e - w) * t, np.full(n, w)])
    lat = np.concatenate([np.full(n, s), s + (nn - s) * t, np.full(n, nn), nn - (nn - s) * t])
    ct = osr.CoordinateTransformation(srs("EPSG:4267"), ds.GetSpatialRef())
    xy = np.array(ct.TransformPoints(np.column_stack([lon, lat])))[:, :2]
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in xy:
        ring.AddPoint_2D(float(x), float(y))
    ring.CloseRings()
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly, xy


def neatline_check(ds, bounds):
    """Offset (scan px) of the printed neatline centre from the graticule: 9 points per edge."""
    s, nn, w, e = bounds
    ct = osr.CoordinateTransformation(srs("EPSG:4267"), ds.GetSpatialRef())
    gt = ds.GetGeoTransform()
    offs = []
    for edge in "NSWE":
        for t in np.linspace(0.1, 0.9, 9):
            lon, lat = (w + (e - w) * t, nn if edge == "N" else s) if edge in "NS" else \
                (w if edge == "W" else e, s + (nn - s) * t)
            x, y, _ = ct.TransformPoint(lon, lat)
            px, py = (x - gt[0]) / gt[1], (y - gt[3]) / gt[5]
            if edge in "NS":
                a = ds.ReadAsArray(int(px) - 3, int(py) - 12, 7, 25).astype(float)
                prof, ref = (a.max(0) < 120).mean(1), py - int(py) + 12
            else:
                a = ds.ReadAsArray(int(px) - 12, int(py) - 3, 25, 7).astype(float)
                prof, ref = (a.max(0) < 120).mean(0), px - int(px) + 12
            idx = np.where(prof > 0.7)[0]
            if len(idx):
                c = idx[np.argmin(abs(idx - 12))]
                lo, hi = c, c
                while lo - 1 in idx:
                    lo -= 1
                while hi + 1 in idx:
                    hi += 1
                offs.append((lo + hi + 1) / 2 - ref)
    offs = np.abs(offs)
    return {"points": len(offs), "median_px": round(float(np.median(offs)), 2),
            "max_px": round(float(offs.max()), 2), "max_m": round(float(offs.max() * gt[1]), 1)}


def main():
    if MOSAIC.exists():
        print(f"{MOSAIC} exists; skipping")
        return
    WORK.mkdir(parents=True, exist_ok=True)
    fx = frame(BOX)
    ext = frame(BOX, PAD)
    ext = (np.floor(ext[0] / RES) * RES, np.floor(ext[1] / RES) * RES,
           np.ceil(ext[2] / RES) * RES, np.ceil(ext[3] / RES) * RES)
    report = {"frame_utm15": [round(v, 1) for v in fx], "frame_km": [round((fx[2] - fx[0]) / 1e3, 2),
              round((fx[3] - fx[1]) / 1e3, 2)], "mosaic_extent_utm15": ext, "res_m": RES,
              "datum_op": "EPSG:1174 NAD27 to WGS 84 (5) geocentric translation " + HELMERT + "; WGS 84 = NAD83",
              "inset_m": INSET_M, "sheets": {}}
    parts = []
    for name, bounds in SHEETS.items():
        src = RAW / name
        ds = gdal.Open(str(src))
        poly, _ = graticule(ds, bounds)
        cut = poly.Buffer(-INSET_M, 8)
        wkt_srs = WORK / (src.stem + "_srs.wkt")
        wkt_srs.write_text(ds.GetSpatialRef().ExportToWkt())
        part = WORK / (src.stem + "_utm15.tif")
        pipe = pipeline(ds.GetSpatialRef())
        if not part.exists():
            subprocess.run(["gdalwarp", "-q", "-overwrite", "-ct", pipe, "-t_srs", DST,
                            "-cutline", cut.ExportToWkt(), "-cutline_srs", str(wkt_srs),
                            "-te", *map(str, ext), "-tr", str(RES), str(RES), "-r", "bilinear",
                            "-dstalpha", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", str(src), str(part)],
                           check=True)
        report["sheets"][name] = {"neatline": neatline_check(ds, bounds), "pipeline": pipe,
                                  "src_crs": ds.GetSpatialRef().ExportToProj4()}
        parts.append(part)
    # Combine: the cutlines do not overlap; a pixel takes the sheet whose alpha is highest.
    first = gdal.Open(str(parts[0]))
    w, h = first.RasterXSize, first.RasterYSize
    rgb = np.zeros((3, h, w), np.uint8)
    best = np.zeros((h, w), np.uint8)
    for p in parts:
        a = gdal.Open(str(p)).ReadAsArray()
        take = a[3] > best
        rgb[:, take] = a[:3, take]
        best = np.maximum(best, a[3])
    valid = best >= 128
    gap = ~valid
    drv = gdal.GetDriverByName("GTiff")
    tmp = drv.Create(str(WORK / "mosaic_tmp.tif"), w, h, 3, gdal.GDT_Byte)
    tmp.SetGeoTransform(first.GetGeoTransform())
    tmp.SetProjection(first.GetProjection())
    mask = drv.Create(str(WORK / "mask_tmp.tif"), w, h, 1, gdal.GDT_Byte)
    mask.GetRasterBand(1).WriteArray(valid.astype(np.uint8))
    for i in range(3):
        b = tmp.GetRasterBand(i + 1)
        b.WriteArray(rgb[i])
        gdal.FillNodata(b, mask.GetRasterBand(1), maxSearchDist=8, smoothingIterations=0)
    out = drv.CreateCopy(str(MOSAIC), tmp, options=["COMPRESS=DEFLATE", "TILED=YES", "PHOTOMETRIC=RGB"])
    for i, c in enumerate((gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand)):
        out.GetRasterBand(i + 1).SetColorInterpretation(c)
    out = None
    seam = drv.Create(str(OUT / "sheets1958_seamfill.tif"), w, h, 1, gdal.GDT_Byte,
                      options=["COMPRESS=DEFLATE", "TILED=YES"])
    seam.SetGeoTransform(first.GetGeoTransform())
    seam.SetProjection(first.GetProjection())
    seam.GetRasterBand(1).WriteArray(gap.astype(np.uint8))
    seam = tmp = mask = None
    for f in ("mosaic_tmp.tif", "mask_tmp.tif"):
        (WORK / f).unlink()
    report.update(size_px=[w, h], seam_filled_px=int(gap.sum()), seam_filled_share=round(float(gap.mean()), 5))
    (OUT / "mosaic_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "sheets"}, indent=1))
    for k, v in report["sheets"].items():
        print(k, v["neatline"])


if __name__ == "__main__":
    main()
