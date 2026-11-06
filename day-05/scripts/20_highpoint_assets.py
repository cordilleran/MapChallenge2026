#!/usr/bin/env python3
"""Day 5 (20): panorama site assets for both observer positions, and the 'local high point' layers (D93).

Run after `09_viewsheds.py --position highpoint` and `17_render_panoramas.py` in both modes
(default, then `D5_PANO_POSITION=highpoint`).

Produces:
  site/img/day05/vs_pack_hp_<scenario>.png   packed viewsheds (bit i = station i), same grid as vs_pack_<scenario>.png
  site/img/day05/pano/pano_<stn>[_hp].webp   panoramas from the station point and the high point (and _grey)
  site/data/day05/pano_peaks[_hp].json       peak tables for those panoramas
  site/data/day05/positions.json             both observer positions per station: EPSG:3979 and lat/lon,
                                             DEM cell value, observer height, visible area (bare earth)

Environment:
  MC26_DAY05_DIR          data root (viewsheds/, viewsheds_highpoint/, pano/)
  MC26_VIEWSHEDS_HP_DIR   default $MC26_DAY05_DIR/viewsheds_highpoint
  D5_PANO_HP_DIR          folder holding pano_<stn>_hp*.webp and skyline_<stn>_hp.json
                          (default $MC26_DAY05_DIR/pano)
"""
import importlib.util
import json
import os
import shutil
from pathlib import Path

import numpy as np
from osgeo import osr

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vr", HERE / "14_viewshed_rasters.py")
vr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vr)  # reuses its warp, PNG writer and paths; its main() is not run

DATA = vr.IN_DIR
VS = DATA / "viewsheds"
VS_HP = Path(os.environ.get("MC26_VIEWSHEDS_HP_DIR", str(DATA / "viewsheds_highpoint")))
PANO_HP = Path(os.environ.get("D5_PANO_HP_DIR", str(DATA / "pano")))
OUT_IMG, OUT_DATA = vr.OUT_IMG, vr.OUT_DATA


def pack(scen):
    packed = None
    for bit, stn in enumerate(vr.STATIONS):
        arr = vr.warp_nearest_3857(VS_HP / f"vs_{stn}_{scen}.tif").ReadAsArray()
        if packed is None:
            packed = np.zeros(arr.shape, np.uint8)
        packed |= (arr > 0).astype(np.uint8) << bit
    out = OUT_IMG / f"vs_pack_hp_{scen}.png"
    size = vr.save_grey_png(packed, out)
    return {"url": f"img/day05/{out.name}", "size_bytes": size}


def positions():
    a = json.loads((VS / "deterministic_metrics.json").read_text())["stations"]
    b = json.loads((VS_HP / "deterministic_metrics.json").read_text())["stations"]
    src = osr.SpatialReference(); src.ImportFromEPSG(3979)
    dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    out = {}
    for stn in vr.STATIONS:
        rec = {}
        for key, m in (("station", a[stn]), ("highpoint", b[stn])):
            x, y = m["x"], m["y"]
            lon, lat, _ = ct.TransformPoint(x, y)
            rec[key] = {"x": round(x, 2), "y": round(y, 2), "lat": round(lat, 6), "lon": round(lon, 6),
                        "dem_m": round(m["dem_m"], 2), "observer_m": round(m["dem_m"] + 1.6, 2),
                        "visible_km2": round(m["main_visible_area_km2"], 1),
                        "area_km2": {"main": round(m["main_visible_area_km2"], 2),
                                     **{f"forest{h}": round(m["forest"][str(h)]["visible_area_km2"], 2) for h in (10, 20, 30)},
                                     "drone": round(m["drone_visible_area_km2"], 2)}}
        dx = rec["highpoint"]["x"] - rec["station"]["x"]; dy = rec["highpoint"]["y"] - rec["station"]["y"]
        rec["offset_m"] = round(float(np.hypot(dx, dy)), 1)
        out[stn] = rec
    return out


def main():
    files = {s: pack(s) for s in vr.SCENARIOS}
    (OUT_IMG / "pano").mkdir(exist_ok=True)
    for suf in ("", "_hp"):
        peaks = {}
        for stn in vr.STATIONS:
            for f in (f"pano_{stn}{suf}.webp", f"pano_{stn}{suf}_grey.webp"):
                shutil.copy2(PANO_HP / "pano" / f if (PANO_HP / "pano" / f).exists() else PANO_HP / f, OUT_IMG / "pano" / f)
            sk = PANO_HP / "pano" / f"skyline_{stn}{suf}.json"
            sk = sk if sk.exists() else PANO_HP / f"skyline_{stn}{suf}.json"
            d = json.loads(sk.read_text())
            peaks[stn] = {"observer_elev_m": d["observer_elev_m"], "image": d["image"], "peaks": d["peaks"]}
        (OUT_DATA / f"pano_peaks{suf}.json").write_text(json.dumps(peaks, separators=(",", ":")))
    pos = positions()
    (OUT_DATA / "positions.json").write_text(json.dumps(
        {"note": "station: the MLP station point as recorded, observer on its 30 m DEM cell + 1.6 m. "
                 "highpoint: the highest DEM cell of the 3x3 window around it, + 1.6 m (D93).",
         "packs_highpoint": files, "stations": pos}, indent=1))
    for stn, r in pos.items():
        print(stn, r["offset_m"], "m;", r["station"]["visible_km2"], "->", r["highpoint"]["visible_km2"], "km2")


if __name__ == "__main__":
    main()
