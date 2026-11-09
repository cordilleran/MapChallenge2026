"""Corpus geography: settlement composition of countries and provinces (spec R4, D130).

For every Natural Earth admin-0 country (1:50m) and admin-1 province or state
(1:10m), the share of land cells (1 km, GHS-SMOD 2020) that are urban centres
(class 30), towns and suburbs (21 to 23) and rural (11 to 13), and the share
of the area's people living in each (GHS-POP 2020, same grid), when that file
is present. Water (10) and no-data cells are left out. Land shares turned out
to say almost nothing (median rural land share 0.98 for countries and for
provinces, D130); population shares are the informative lens. A regional study then inherits its area's mix
when its own text gives no setting.

Runs with the system Python (GDAL bindings and numpy). Polygons are
rasterised once onto the SMOD grid (Mollweide, 1 km) as zone ids; the grid is
then read in strips and counted with numpy. Writes
`derived-261108/area_settlement.csv` (zone type, code, cells by class).

Usage: /usr/bin/python3 15_area_settlement.py
"""
import csv
import os
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
RAW = OUT_DIR / "raw-261108"
DER = OUT_DIR / "derived-261108"
SMOD = next((RAW / "ghs" / "x").glob("*.tif"))
POP = next((RAW / "ghs" / "xpop").glob("*.tif"), None) if (RAW / "ghs" / "xpop").exists() else None
LAYERS = {
    "admin0": (next((RAW / "ne" / "x_ne_50m_admin_0_countries").glob("*.shp")), "ISO_A2_EH"),
    "admin1": (next((RAW / "ne" / "x_ne_10m_admin_1").glob("*.shp")), "gn_id"),
}
CLASSES = {"urban": [30], "town": [21, 22, 23], "rural": [11, 12, 13], "water": [10]}


def zones(kind, src, field, ref):
    """Rasterise one layer to zone ids (1..n) on the SMOD grid; return the path and the id-to-code list."""
    out = DER / f"zones_{kind}.tif"
    ds = ogr.Open(str(src))
    lyr = ds.GetLayer()
    codes = [str(f.GetField(field)) for f in lyr]
    if not out.exists():
        mem = gdal.VectorTranslate("/vsimem/z.gpkg", str(src), format="GPKG", dstSRS="ESRI:54009",
                                   SQLStatement=f"SELECT *, rowid + 1 AS zid FROM \"{lyr.GetName()}\"", SQLDialect="SQLITE")
        mem = None
        gt = ref.GetGeoTransform()
        gdal.Rasterize(str(out), "/vsimem/z.gpkg", format="GTiff", outputType=gdal.GDT_UInt16,
                       outputBounds=[gt[0], gt[3] + gt[5] * ref.RasterYSize, gt[0] + gt[1] * ref.RasterXSize, gt[3]],
                       xRes=gt[1], yRes=-gt[5], attribute="zid", noData=0, initValues=0,
                       creationOptions=["COMPRESS=DEFLATE", "TILED=YES"])
        gdal.Unlink("/vsimem/z.gpkg")
    return out, codes


def main():
    DER.mkdir(exist_ok=True)
    ref = gdal.Open(str(SMOD))
    sb = ref.GetRasterBand(1)
    pds = gdal.Open(str(POP)) if POP else None
    if pds and (pds.RasterXSize, pds.RasterYSize, pds.GetGeoTransform()) != (ref.RasterXSize, ref.RasterYSize, ref.GetGeoTransform()):
        sys.exit("GHS-POP grid differs from GHS-SMOD; resample first")
    pb = pds.GetRasterBand(1) if pds else None
    rows = []
    for kind, (src, field) in LAYERS.items():
        zpath, codes = zones(kind, src, field, ref)
        zds = gdal.Open(str(zpath))
        zb = zds.GetRasterBand(1)
        n = len(codes) + 1
        counts = np.zeros((n, 31), dtype=np.int64)
        people = np.zeros((n, 31), dtype=np.float64)
        step = 1000
        for y in range(0, ref.RasterYSize, step):
            h = min(step, ref.RasterYSize - y)
            s = sb.ReadAsArray(0, y, ref.RasterXSize, h)
            z = zb.ReadAsArray(0, y, ref.RasterXSize, h).astype(np.int64)
            ok = (z > 0) & (s >= 10) & (s <= 30)
            idx = z[ok] * 31 + s[ok].astype(np.int64)
            counts += np.bincount(idx, minlength=n * 31).reshape(n, 31)
            if pb:
                pop = pb.ReadAsArray(0, y, ref.RasterXSize, h)
                people += np.bincount(idx, weights=np.clip(pop[ok], 0, None), minlength=n * 31).reshape(n, 31)
        for i, code in enumerate(codes, 1):
            c = {k: int(counts[i, v].sum()) for k, v in CLASSES.items()}
            pp = {k: round(float(people[i, v].sum())) for k, v in CLASSES.items() if k != "water"}
            rows.append([kind, code, c["urban"], c["town"], c["rural"], c["water"],
                         pp["urban"], pp["town"], pp["rural"]])
        print(kind, len(codes), "zones", flush=True)
    with open(DER / "area_settlement.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["zone", "code", "urban", "town", "rural", "water", "pop_urban", "pop_town", "pop_rural"])
        w.writerows(rows)
    print(DER / "area_settlement.csv", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
