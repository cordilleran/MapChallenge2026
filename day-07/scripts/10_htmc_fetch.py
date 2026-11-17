"""Fetch the four 1958 USGS HTMC 1:250,000 sheets (Duluth, Ashland, Hibbing, Two Harbors) as GeoTIFFs.

Input:  the TNM products API (Historical Topographic Maps over the Day 7 box).
Output: $MC26_DAY07_DATA/raw/htmc/
        tnm_query.json             the full API answer, as returned
        tnm_items_1958.json        the four records used
        <name>.tif                 each GeoTIFF as downloaded (USGS file name kept)
        sheets_info.json           CRS, resolution, size and georeference of each download
Rerun-safe: skips the query and any file that already exists.
Each sheet has exactly one 1958 1 x 2 degree item in the API (checked 2026-11-16); the script stops if
that changes, so a reprint is never picked silently.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from osgeo import gdal, osr

gdal.UseExceptions()

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
DATA = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
RAW = DATA / "raw" / "htmc"
API = ("https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Historical%20Topographic%20Maps"
       "&bbox=-93.30,46.40,-91.30,47.72&max=500&outputFormat=JSON")
SHEETS = ("Duluth, MN", "Ashland, WI", "Hibbing, MN", "Two Harbors, MN")
EDITION = "1958"


def get(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "mapchallenge-day07-fetch"})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def describe(path):
    ds = gdal.Open(str(path))
    gt = ds.GetGeoTransform()
    srs = ds.GetSpatialRef()
    return {
        "file": path.name, "size_px": [ds.RasterXSize, ds.RasterYSize], "bands": ds.RasterCount,
        "dtype": gdal.GetDataTypeName(ds.GetRasterBand(1).DataType),
        "colour_interp": [gdal.GetColorInterpretationName(ds.GetRasterBand(i + 1).GetColorInterpretation())
                          for i in range(ds.RasterCount)],
        "crs_name": srs.GetName() if srs else None,
        "crs_epsg": srs.GetAuthorityCode(None) if srs else None,
        "datum": srs.GetAttrValue("DATUM") if srs else None,
        "geotransform": gt, "res": [gt[1], -gt[5]],
        "georeferenced": bool(srs) and gt != (0, 1, 0, 0, 0, 1),
        "gcps": ds.GetGCPCount(),
    }


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    q = RAW / "tnm_query.json"
    get(API, q)
    items = json.loads(q.read_text())["items"]
    chosen = []
    for name in SHEETS:
        hits = [i for i in items if i.get("extent") == "1 x 2 degree" and f"for {name} " in i["title"]
                and i["publicationDate"].startswith(EDITION)]
        if len(hits) != 1:
            raise SystemExit(f"{name}: {len(hits)} items of the {EDITION} edition; choose one by hand and record why")
        chosen.append(hits[0])
    (RAW / "tnm_items_1958.json").write_text(json.dumps(chosen, indent=1) + "\n")
    info = []
    for it in chosen:
        url = it["urls"]["GeoTIFF"]
        dest = RAW / url.rsplit("/", 1)[1].replace("%20", "_")
        get(url, dest)
        d = describe(dest)
        d.update(title=it["title"], sourceId=it["sourceId"], url=url, api_bbox=it["boundingBox"])
        info.append(d)
        print(d["title"], d["size_px"], d["crs_name"], [round(v, 3) for v in d["res"]])
    (RAW / "sheets_info.json").write_text(json.dumps(info, indent=1) + "\n")


if __name__ == "__main__":
    main()
