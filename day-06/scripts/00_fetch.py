"""Download the modern data for Sheet No. 16 into raw-261109/ (run once; never overwrites).

- NRCan MRDEM-30 terrain model: a window of the cloud-optimized GeoTIFF, unchanged values.
- Glacier outlines 1984-2021 (Bevington and Menounos 2022, Zenodo 10.5281/zenodo.5900363),
  the features that touch the window, read over HTTP from the 5 GB GeoPackage.
- OpenStreetMap water, roads, trails and railway through the Overpass API.
- Canadian Geographical Names (CGNDB) in the window.
- OpenStreetMap summits (natural=peak) through Overpass, for peaks.py (added 11-10).

Writes raw-261109/manifest.json with the source, licence and sha256 of each file.

Usage: python3 00_fetch.py   (system Python with GDAL; settings from day-06/.env)
"""
import hashlib
import json
import subprocess
import time
import urllib.parse
import urllib.request

from sheet import BBOX_LL, RAW

UA = {"User-Agent": "mapchallenge2026-day06 (one-off download)"}
W, S, E, N = BBOX_LL

SOURCES = {
    "mrdem30_window.tif": {
        "source": "NRCan MRDEM-30 DTM (Medium Resolution Digital Elevation Model), EPSG:3979",
        "url": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif",
        "licence": "Open Government Licence - Canada",
    },
    "glaciers_1984_2021.gpkg": {
        "source": "Bevington, A. R. and Menounos, B. (2022) Accelerated change in the glaciated environments "
                  "of western Canada revealed through trend analysis of optical satellite imagery. Remote "
                  "Sensing of Environment 270, 112862. Polygons: doi:10.5281/zenodo.5900363",
        "url": "https://zenodo.org/records/5900363/files/bca_glaciers_1984-2021.gpkg",
        "licence": "CC BY 4.0",
    },
    "osm.json": {
        "source": "OpenStreetMap contributors, Overpass API",
        "url": "https://overpass-api.de/api/interpreter",
        "licence": "ODbL 1.0",
    },
    "osm_boundary.json": {
        "source": "OpenStreetMap contributors, Overpass API (provincial boundary ways)",
        "url": "https://overpass-api.de/api/interpreter",
        "licence": "ODbL 1.0",
    },
    "osm_peaks.json": {
        "source": "OpenStreetMap contributors, Overpass API (natural=peak nodes)",
        "url": "https://overpass-api.de/api/interpreter",
        "licence": "ODbL 1.0",
    },
    "cgndb.json": {
        "source": "Canadian Geographical Names Database (Natural Resources Canada), geonames API",
        "url": "https://geogratis.gc.ca/services/geoname/en/geonames.json",
        "licence": "Open Government Licence - Canada",
    },
}


def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def fetch_dem(path):
    # Window in the source CRS, padded; reprojection happens in 03, not here.
    subprocess.run(["gdalwarp", "-q", "-t_srs", "EPSG:3979", "-te_srs", "EPSG:4326",
                    "-te", str(W), str(S), str(E), str(N), "-r", "near", "-co", "COMPRESS=DEFLATE",
                    "/vsicurl/" + SOURCES[path.name]["url"], str(path)], check=True)


def fetch_glaciers(path):
    """Copy only the features in the window from the 5 GB remote GeoPackage.

    A plain ogr2ogr -spat over HTTP failed part-way ("database disk image is malformed"), and the
    full download ran at about 70 KB/s. So: ask the R-tree index for the feature ids whose boxes
    meet the window (in the file's CRS, BC Albers), then copy those rows in batches.
    """
    from osgeo import gdal
    from pyproj import Transformer

    url = "/vsicurl/" + SOURCES[path.name]["url"]
    layer = "new_all_join_id_filter_20220120-0835"
    t = Transformer.from_crs("EPSG:4326", "EPSG:3005", always_xy=True)
    xs, ys = zip(*[t.transform(x, y) for x in (W, E) for y in (S, N)], strict=True)
    ds = gdal.OpenEx(url, gdal.OF_VECTOR, open_options=["IMMUTABLE=YES"])
    sql = (f'SELECT id FROM "rtree_{layer}_geom" WHERE maxx >= {min(xs)} AND minx <= {max(xs)} '
           f"AND maxy >= {min(ys)} AND miny <= {max(ys)}")
    res = ds.ExecuteSQL(sql)
    ids = sorted(f.GetField(0) for f in res)
    ds.ReleaseResultSet(res)
    for i in range(0, len(ids), 250):
        batch = ",".join(map(str, ids[i:i + 250]))
        args = ["-append", "-nln", "glaciers"] if i else ["-f", "GPKG", "-nln", "glaciers"]
        subprocess.run(["ogr2ogr", "-q", "-oo", "IMMUTABLE=YES", *args, "-where", f"fid IN ({batch})",
                        str(path), url, layer], check=True)
    print(f"glacier features copied: {len(ids)}")


def fetch_osm(path):
    bb = f"{S},{W},{N},{E}"
    q = f"""[out:json][timeout:180];
(
  way["natural"="water"]({bb}); relation["natural"="water"]({bb});
  way["waterway"~"^(river|stream|canal)$"]({bb});
  way["highway"]({bb});
  way["railway"~"^(rail|disused|abandoned)$"]({bb});
  way["natural"="glacier"]({bb}); relation["natural"="glacier"]({bb});
);
out body; >; out skel qt;"""
    path.write_bytes(get(SOURCES["osm.json"]["url"], urllib.parse.urlencode({"data": q}).encode()))


def fetch_boundary(path):
    """The Alberta-British Columbia boundary (admin_level 4 ways), added after osm.json was taken."""
    bb = f"{S},{W},{N},{E}"
    # The ways carry no tags; the boundary tags sit on the province relations.
    q = (f'[out:json][timeout:180];relation["boundary"="administrative"]["admin_level"="4"]'
         f'["name"="Alberta"];way(r)({bb});out body; >; out skel qt;')
    path.write_bytes(get(SOURCES[path.name]["url"], urllib.parse.urlencode({"data": q}).encode()))


def fetch_peaks(path):
    """Summits mapped in OSM. CanVec 50K spot heights were checked first: 3 points in this window."""
    bb = f"{S},{W},{N},{E}"
    q = f'[out:json][timeout:120];node["natural"="peak"]({bb});out body;'
    path.write_bytes(get(SOURCES["osm.json"]["url"], urllib.parse.urlencode({"data": q}).encode()))


def fetch_names(path):
    qs = urllib.parse.urlencode({"bbox": f"{W},{S},{E},{N}", "num": 1000})
    body = get(SOURCES["cgndb.json"]["url"] + "?" + qs)
    if len(json.loads(body)["items"]) >= 1000:
        raise SystemExit("CGNDB returned a full page; add paging before trusting this file.")
    path.write_bytes(body)


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = {"mrdem30_window.tif": fetch_dem, "glaciers_1984_2021.gpkg": fetch_glaciers,
            "osm.json": fetch_osm, "osm_boundary.json": fetch_boundary, "cgndb.json": fetch_names, "osm_peaks.json": fetch_peaks}
    man_path = RAW / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
    for name, fn in jobs.items():
        p = RAW / name
        if p.exists() and name in manifest:
            print(f"keep {name} (already downloaded)")
            continue
        try:
            fn(p)
        except FileNotFoundError as e:
            print(f"skip {name}: {e}")
            continue
        manifest[name] = dict(SOURCES[name], bbox_wgs84=[W, S, E, N],
                              downloaded=time.strftime("%Y-%m-%d"),
                              sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size)
        man_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"got {name}: {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
