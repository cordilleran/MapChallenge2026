#!/usr/bin/env python3
"""Day 5 (13): Base map overlays in Web Mercator (EPSG:3857) for Leaflet.

Produces:
  site/img/day05/base_viewshed.webp   plain hillshade over the viewshed box (EPSG:3857, 50 m Mercator / ~32.7 m ground)
  site/img/day05/base_core.webp       Sentinel-2 true colour (TCI) blended with hillshade over the core box (EPSG:3857, 25 m Mercator / ~16.4 m ground)
  site/data/day05/base_bounds.json    lat/lon bounds, EPSG:3857 bounds, pixel sizes and attribution metadata

Environment:
  MC26_DAY05_DIR   input directory holding slice_a/, viewsheds/, viewsheds_rmse8/, stations.csv
                   (defaults to <repo_root>/../in if unset)
"""
import json
import math
import os
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from PIL import Image

gdal.UseExceptions()
osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
IN_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()

OUT_IMG = ROOT / "site" / "img" / "day05"
OUT_DATA = ROOT / "site" / "data" / "day05"
OUT_IMG.mkdir(parents=True, exist_ok=True)
OUT_DATA.mkdir(parents=True, exist_ok=True)

# Target Mercator pixel sizes (at lat ~49.13 N, cos(lat) ~ 0.6543, so 50 m Mercator = 32.7 m ground)
TR_VIEWSHED_3857 = 50.0
TR_CORE_3857 = 25.0


def mercator_bounds_to_latlon(xmin, ymin, xmax, ymax):
    """Convert EPSG:3857 [xmin, ymin, xmax, ymax] to Leaflet [[south, west], [north, east]] in EPSG:4326."""
    s3857 = osr.SpatialReference()
    s3857.ImportFromEPSG(3857)
    s4326 = osr.SpatialReference()
    s4326.ImportFromEPSG(4326)
    s4326.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(s3857, s4326)
    west, south, _ = tr.TransformPoint(xmin, ymin)
    east, north, _ = tr.TransformPoint(xmax, ymax)
    return [[round(south, 6), round(west, 6)], [round(north, 6), round(east, 6)]]


def main():
    mem_drv = gdal.GetDriverByName("MEM")

    # 1. Viewshed Box plain hillshade (warped to EPSG:3857 at 50 m Mercator / ~32.7 m ground)
    hs_vs_path = IN_DIR / "slice_a" / "derived" / "hillshade_viewshed_30m_epsg3979.tif"
    ds_hs_src = gdal.Open(str(hs_vs_path))
    hs_copy = mem_drv.CreateCopy("", ds_hs_src)
    hs_copy.GetRasterBand(1).DeleteNoDataValue()  # preserve valid dark shadow pixels (0) inside the box

    ds_vs_3857 = gdal.Warp(
        "",
        hs_copy,
        format="MEM",
        dstSRS="EPSG:3857",
        xRes=TR_VIEWSHED_3857,
        yRes=TR_VIEWSHED_3857,
        resampleAlg="bilinear",
        dstAlpha=True,
    )
    vs_w, vs_h = ds_vs_3857.RasterXSize, ds_vs_3857.RasterYSize
    vs_gt = ds_vs_3857.GetGeoTransform()
    vs_xmin, vs_ymax = vs_gt[0], vs_gt[3]
    vs_xmax = vs_xmin + vs_w * vs_gt[1]
    vs_ymin = vs_ymax + vs_h * vs_gt[5]
    vs_bounds_ll = mercator_bounds_to_latlon(vs_xmin, vs_ymin, vs_xmax, vs_ymax)

    hs_arr = ds_vs_3857.ReadAsArray()  # shape (2, H, W): band 0 = grey, band 1 = alpha
    grey = hs_arr[0]
    alpha = hs_arr[1]
    vs_rgba = np.dstack([grey, grey, grey, alpha])
    out_vs_webp = OUT_IMG / "base_viewshed.webp"
    Image.fromarray(vs_rgba, "RGBA").save(out_vs_webp, "WEBP", quality=82, method=6)

    # 2. Core Box Sentinel-2 true colour (TCI) blended with core hillshade (EPSG:3857)
    tci_path = IN_DIR / "slice_a" / "derived" / "s2_20250825_TCI_core_10m_epsg3979.tif"
    hs_core_path = IN_DIR / "slice_a" / "derived" / "hillshade_core_30m_epsg3979.tif"
    ds_tci_src = gdal.Open(str(tci_path))
    ds_hsc_src = gdal.Open(str(hs_core_path))
    hsc_copy = mem_drv.CreateCopy("", ds_hsc_src)
    hsc_copy.GetRasterBand(1).DeleteNoDataValue()

    ds_tci_3857 = gdal.Warp(
        "",
        ds_tci_src,
        format="MEM",
        dstSRS="EPSG:3857",
        xRes=TR_CORE_3857,
        yRes=TR_CORE_3857,
        resampleAlg="bilinear",
        dstAlpha=True,
    )
    c_w, c_h = ds_tci_3857.RasterXSize, ds_tci_3857.RasterYSize
    c_gt = ds_tci_3857.GetGeoTransform()
    c_xmin, c_ymax = c_gt[0], c_gt[3]
    c_xmax = c_xmin + c_w * c_gt[1]
    c_ymin = c_ymax + c_h * c_gt[5]
    c_bounds_ll = mercator_bounds_to_latlon(c_xmin, c_ymin, c_xmax, c_ymax)

    ds_hsc_3857 = gdal.Warp(
        "",
        hsc_copy,
        format="MEM",
        dstSRS="EPSG:3857",
        outputBounds=(c_xmin, c_ymin, c_xmax, c_ymax),
        width=c_w,
        height=c_h,
        resampleAlg="bilinear",
    )

    tci_arr = ds_tci_3857.ReadAsArray()  # (4, H, W)
    rgb = np.transpose(tci_arr[:3], (1, 2, 0)).astype(np.float32)
    c_alpha = tci_arr[3]
    hsc = ds_hsc_3857.ReadAsArray().astype(np.float32) / 255.0

    # Luminance-preserving hillshade modulation of Sentinel-2 TCI
    shade_factor = (0.35 + 0.65 * hsc[..., None]) * 1.15
    blended_rgb = np.clip(rgb * shade_factor, 0, 255).astype(np.uint8)
    core_rgba = np.dstack([blended_rgb, c_alpha])
    out_core_webp = OUT_IMG / "base_core.webp"
    Image.fromarray(core_rgba, "RGBA").save(out_core_webp, "WEBP", quality=85, method=6)

    cos_lat = math.cos(math.radians(49.13))
    meta = {
        "crs": "EPSG:3857",
        "bounds_crs": "EPSG:4326",
        "note": "Leaflet L.imageOverlay bounds as [[south, west], [north, east]] in EPSG:4326; rasters warped to EPSG:3857.",
        "viewshed": {
            "url": "img/day05/base_viewshed.webp",
            "width": vs_w,
            "height": vs_h,
            "mercator_res_m": TR_VIEWSHED_3857,
            "ground_res_approx_m": round(TR_VIEWSHED_3857 * cos_lat, 2),
            "bounds_3857": [round(vs_xmin, 2), round(vs_ymin, 2), round(vs_xmax, 2), round(vs_ymax, 2)],
            "bounds": vs_bounds_ll,
            "size_bytes": out_vs_webp.stat().st_size,
        },
        "core": {
            "url": "img/day05/base_core.webp",
            "width": c_w,
            "height": c_h,
            "mercator_res_m": TR_CORE_3857,
            "ground_res_approx_m": round(TR_CORE_3857 * cos_lat, 2),
            "bounds_3857": [round(c_xmin, 2), round(c_ymin, 2), round(c_xmax, 2), round(c_ymax, 2)],
            "bounds": c_bounds_ll,
            "size_bytes": out_core_webp.stat().st_size,
        },
    }
    out_json = OUT_DATA / "base_bounds.json"
    out_json.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {out_vs_webp.name}: {vs_w}x{vs_h}, {out_vs_webp.stat().st_size / 1024:.1f} KB")
    print(f"Wrote {out_core_webp.name}: {c_w}x{c_h}, {out_core_webp.stat().st_size / 1024:.1f} KB")
    print(f"Wrote {out_json.name}: {out_json.stat().st_size} B")


if __name__ == "__main__":
    main()
