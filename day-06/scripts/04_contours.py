"""Contours from MRDEM-30: 100 ft as on the 1925 sheet (index every 1,000 ft), and a metric set.

The metric set is 25 m with an index every 250 m: close to the density of 100 ft (30.5 m), and
like the sheet an index line every tenth contour.

The 30 m model is resampled to 10 m (cubic) and smoothed a little (Gaussian, 1.5 cells) so that
contours do not show the 30 m stair steps. Elevations are converted to feet before contouring.

Writes derived/terrain_10m.tif (metres) and derived/contours.gpkg: layer contours (elev_ft, idx)
and layer contours_m (elev_m, idx).
"""
import subprocess

import numpy as np
from osgeo import gdal
from scipy import ndimage as ndi
from sheet import CRS, DERIVED, FT, RAW

gdal.UseExceptions()
INTERVAL_FT = 100
INTERVAL_M = 25
SMOOTH_CELLS = 1.5


def main():
    DERIVED.mkdir(parents=True, exist_ok=True)
    ds = gdal.Warp("", str(RAW / "mrdem30_window.tif"), format="MEM", dstSRS=CRS, xRes=10, yRes=10,
                   resampleAlg="cubic", srcNodata=-32767, dstNodata=-32767)
    z = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nod = z == -32767
    z = np.where(nod, np.nan, z)
    zs = ndi.gaussian_filter(np.nan_to_num(z, nan=float(np.nanmean(z))), SMOOTH_CELLS)
    zs[nod] = -32767
    out = DERIVED / "terrain_10m.tif"
    t = gdal.GetDriverByName("GTiff").Create(str(out), ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32,
                                             options=["COMPRESS=DEFLATE", "TILED=YES"])
    t.SetGeoTransform(ds.GetGeoTransform())
    t.SetProjection(ds.GetProjection())
    b = t.GetRasterBand(1)
    b.SetNoDataValue(-32767)
    b.WriteArray(zs)
    t = None

    feet = DERIVED / "terrain_10m_ft.tif"
    subprocess.run(["gdal_calc", "--quiet", "--overwrite", "-A", str(out), "--outfile", str(feet),
                    f"--calc=where(A==-32767,-32767,A/{FT})", "--NoDataValue=-32767", "--type=Float32",
                    "--co=COMPRESS=DEFLATE"], check=True)
    cont = DERIVED / "contours.gpkg"
    cont.unlink(missing_ok=True)
    for layer, field, step, src in (("contours", "elev_ft", INTERVAL_FT, feet), ("contours_m", "elev_m", INTERVAL_M, out)):
        tmp = DERIVED / f"{layer}_tmp.gpkg"
        tmp.unlink(missing_ok=True)
        subprocess.run(["gdal_contour", "-q", "-a", field, "-i", str(step), "-nln", layer, str(src), str(tmp)],
                       check=True)
        subprocess.run(["ogr2ogr", *(["-update"] if cont.exists() else []), str(cont), str(tmp)], check=True)
        tmp.unlink()
        c = gdal.OpenEx(str(cont), gdal.OF_VECTOR | gdal.OF_UPDATE)
        c.ExecuteSQL(f"ALTER TABLE {layer} ADD COLUMN idx INTEGER")
        c.ExecuteSQL(f"UPDATE {layer} SET idx = CASE WHEN CAST({field} AS INTEGER) % {step * 10} = 0 THEN 1 ELSE 0 END")
        c = None
    print("contours written:", cont)


if __name__ == "__main__":
    main()
