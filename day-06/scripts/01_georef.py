"""Warp the scan of Sheet No. 16 to EPSG:26911 and report the georeferencing error.

The transformation (georef.py): the four printed graticule corners, taken as NAD27 latitude and
longitude and projected to UTM, define a bilinear map from scan pixels to UTM; one mean shift,
from 11 summit stations, moves it onto the terrain model. The warp reproduces that map exactly:
a 9 x 9 grid of points computed from it, fitted by a second-order polynomial (which contains the
bilinear terms). Until 11-10 the warp was a thin-plate spline through the four corners only, which
agrees with the model at the corners but not between them (warp_check_m in the report).

Writes derived/sheet16_26911.tif (10 m, cell average, for reading the inks) and
derived/sheet16_26911_display.tif (4 m, Lanczos, for the page), and derived/georef_report.json.
The error is leave-one-out: each station is tested with a shift computed from the other ten.
"""
import json
import subprocess

import georef
import numpy as np
from osgeo import gdal
from sheet import CRS, DERIVED, SCAN

gdal.UseExceptions()


def loo_rms():
    r = georef.residuals()
    out = [r[i] - np.delete(r, i, 0).mean(axis=0) for i in range(len(r))]
    d = np.hypot(*np.array(out).T)
    return float(np.sqrt(np.mean(d ** 2))), float(d.max())


def warp_check(vrt, scale):
    """Largest distance, metres, between the fitted warp and the model at the stations and corners."""
    t = gdal.Transformer(gdal.Open(str(vrt)), None, ["METHOD=GCP_POLYNOMIAL", "MAX_GCP_ORDER=2"])
    pts = [(p["px"], p["py"]) for p in georef.stations()] + list(georef.CORNER_PX.values())
    e, n = georef.model(*np.array(pts).T)
    got = [t.TransformPoint(0, x * scale, y * scale)[1][:2] for x, y in pts]
    return float(np.max(np.hypot(*(np.array(got) - np.column_stack([e, n])).T)))


def main():
    DERIVED.mkdir(parents=True, exist_ok=True)
    src = gdal.Open(str(SCAN))
    scale = src.RasterXSize / georef.REF_WIDTH
    if abs(src.RasterYSize / scale - 2871) > 1:
        raise SystemExit(f"{SCAN.name}: {src.RasterXSize} x {src.RasterYSize} px is not the reference scan, rescaled")
    src = None
    r0 = np.hypot(*georef.residuals().T)
    rms, worst = loo_rms()
    vrt = DERIVED / "sheet16_gcp.vrt"
    gcp = [a for g in georef.grid_gcps(scale) for a in ("-gcp", *map(str, g))]
    subprocess.run(["gdal_translate", "-q", "-of", "VRT", "-b", "1", "-b", "2", "-b", "3", "-a_srs", CRS, *gcp,
                    str(SCAN), str(vrt)], check=True)
    report = {
        "scan": SCAN.name,
        "scan_scale": scale,
        "model": "printed graticule corners (NAD27) bilinear + mean shift at 11 stations; warp: 9 x 9 model grid, "
                 "polynomial order 2",
        "shift_m": [round(v, 1) for v in georef.mean_shift()],
        "corners_only_rms_m": round(float(np.sqrt(np.mean(r0 ** 2))), 1),
        "held_out_rms_m": round(rms, 1),
        "held_out_max_m": round(worst, 1),
        "warp_check_m": round(warp_check(vrt, scale), 2),
    }
    for out, res, method in ((DERIVED / "sheet16_26911.tif", 10, "average"),
                             (DERIVED / "sheet16_26911_display.tif", 4, "lanczos")):
        subprocess.run(["gdalwarp", "-q", "-overwrite", "-order", "2", "-r", method, "-tr", str(res), str(res),
                        "-t_srs", CRS, "-dstalpha", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", str(vrt), str(out)],
                       check=True)
    vrt.unlink()
    (DERIVED / "georef_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
