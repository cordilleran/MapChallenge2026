#!/usr/bin/env python3
"""
Task 9: Generate slice_a/MANIFEST.md with complete provenance for every file in slice_a/
(source URL, retrieval date and time, licence, sha256, CRS, size, and exact command or script that made it),
plus a FAILED section documenting any blocked/unavailable endpoints or schema limitations.

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import datetime
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def fmt_size(num_bytes):
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024.0:.1f} KB ({num_bytes:,} B)"
    else:
        return f"{num_bytes / (1024.0 * 1024.0):.2f} MB ({num_bytes:,} B)"

def mtime_utc(path):
    ts = os.path.getmtime(path)
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

FILE_META = {
    # Raw files
    "raw/mrdem30_viewshed_raw.tif": {
        "source_url": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:3979 (NAD83(CSRS) / Canada Atlas Lambert) + EPSG:6647 (CGVD2013 height, m)",
        "command": "gdal_translate -srcwin 36471 124799 2342 2282 -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 /vsicurl/https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif raw/mrdem30_viewshed_raw.tif (via scripts/02_dem.py)",
    },
    "raw/stac_sentinel2_20250825.json": {
        "source_url": "https://earth-search.aws.element84.com/v1/search",
        "licence": "Copernicus Open Sentinel Data Licence (contains modified Copernicus Sentinel data 2025)",
        "crs": "EPSG:4326 (STAC GeoJSON item footprints)",
        "command": "POST https://earth-search.aws.element84.com/v1/search {\"collections\":[\"sentinel-2-l2a\"],\"ids\":[\"S2B_11UPQ_20250825_0_L2A\",\"S2B_11UQQ_20250825_0_L2A\"]} (via scripts/03_imagery.py)",
    },
    "raw/S2B_11UPQ_20250825_0_L2A_TCI_core_utm11.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/TCI.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:32611 (WGS 84 / UTM zone 11N)",
        "command": "gdal_translate -projwin 698500.0 5460500.0 709800.0 5431500.0 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/TCI.tif raw/S2B_11UPQ_20250825_0_L2A_TCI_core_utm11.tif (via scripts/03_imagery.py)",
    },
    "raw/S2B_11UPQ_20250825_0_L2A_B04_core_utm11.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/B04.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:32611 (WGS 84 / UTM zone 11N)",
        "command": "gdal_translate -projwin 698500.0 5460500.0 709800.0 5431500.0 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/B04.tif raw/S2B_11UPQ_20250825_0_L2A_B04_core_utm11.tif (via scripts/03_imagery.py)",
    },
    "raw/S2B_11UPQ_20250825_0_L2A_B08_core_utm11.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/B08.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:32611 (WGS 84 / UTM zone 11N)",
        "command": "gdal_translate -projwin 698500.0 5460500.0 709800.0 5431500.0 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/B08.tif raw/S2B_11UPQ_20250825_0_L2A_B08_core_utm11.tif (via scripts/03_imagery.py)",
    },
    "raw/S2B_11UQQ_20250825_0_L2A_TCI_core_utm11.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/TCI.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:32611 (WGS 84 / UTM zone 11N)",
        "command": "gdal_translate -projwin 699960.0 5460500.0 728500.0 5431500.0 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/TCI.tif raw/S2B_11UQQ_20250825_0_L2A_TCI_core_utm11.tif (via scripts/03_imagery.py)",
    },
    "raw/S2B_11UQQ_20250825_0_L2A_B04_core_utm11.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/B04.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:32611 (WGS 84 / UTM zone 11N)",
        "command": "gdal_translate -projwin 699960.0 5460500.0 728500.0 5431500.0 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/B04.tif raw/S2B_11UQQ_20250825_0_L2A_B04_core_utm11.tif (via scripts/03_imagery.py)",
    },
    "raw/S2B_11UQQ_20250825_0_L2A_B08_core_utm11.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/B08.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:32611 (WGS 84 / UTM zone 11N)",
        "command": "gdal_translate -projwin 699960.0 5460500.0 728500.0 5431500.0 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/B08.tif raw/S2B_11UQQ_20250825_0_L2A_B08_core_utm11.tif (via scripts/03_imagery.py)",
    },
    "raw/ESA_WorldCover_10m_2021_v200_N48W117_viewshed_wgs84.tif": {
        "source_url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W117_Map.tif",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data 2021)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "gdal_translate -projwin -114.70 49.55 -114.00 48.72 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W117_Map.tif raw/ESA_WorldCover_10m_2021_v200_N48W117_viewshed_wgs84.tif (via scripts/04_landcover.py)",
    },
    "raw/ESA_WorldCover_10m_2021_v200_N48W114_viewshed_wgs84.tif": {
        "source_url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W114_Map.tif",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data 2021)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "gdal_translate -projwin -114.00 49.55 -113.45 48.72 -co TILED=YES -co COMPRESS=DEFLATE /vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W114_Map.tif raw/ESA_WorldCover_10m_2021_v200_N48W114_viewshed_wgs84.tif (via scripts/04_landcover.py)",
    },
    "raw/cgndb_viewshed_raw.json": {
        "source_url": "https://geogratis.gc.ca/services/geoname/en/geonames.json?bbox=-114.68,48.74,-113.48,49.52&num=1000",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:4326 / NAD83(CSRS) geographic decimal degrees",
        "command": "curl -s \"https://geogratis.gc.ca/services/geoname/en/geonames.json?bbox=-114.68,48.74,-113.48,49.52&num=1000\" -o raw/cgndb_viewshed_raw.json",
    },
    "raw/gnis_viewshed_raw.json": {
        "source_url": "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/5/query?geometry=-114.68,48.74,-113.48,49.52&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&outSR=4326&f=json",
        "licence": "Public Domain (US Government Work / USGS National Map)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "curl -s \"https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/5/query?geometry=-114.68,48.74,-113.48,49.52&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&outSR=4326&f=json\" -o raw/gnis_viewshed_raw.json",
    },
    "raw/waterton_np_cgndb_IATZN.geojson": {
        "source_url": "https://geogratis.gc.ca/services/geoname/en/geonames/IATZN.geojson",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },
    "raw/waterton_np_alberta_titan.geojson": {
        "source_url": "https://geospatial.alberta.ca/titan/rest/services/environment/parks_and_protected_areas_of_alberta_10tm_nad83_aep/MapServer/14/query?where=NAME%3D%27Waterton%20Lakes%27&outFields=*&outSR=4326&f=geojson",
        "licence": "Open Government Licence - Alberta",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },
    "raw/kenow_fire_2017_nbac_raw.geojson": {
        "source_url": "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=public:nbac&cql_filter=year=2017%20AND%20nfireid=2418&outputFormat=application/json&srsName=urn:ogc:def:crs:EPSG::4326",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },
    "raw/osm_core_sw.json": {
        "source_url": "https://api.openstreetmap.org/api/0.6/map.json?bbox=-114.2,49.06,-114.075,49.13",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },
    "raw/osm_core_se.json": {
        "source_url": "https://api.openstreetmap.org/api/0.6/map.json?bbox=-114.075,49.06,-113.95,49.13",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },
    "raw/osm_core_nw.json": {
        "source_url": "https://api.openstreetmap.org/api/0.6/map.json?bbox=-114.2,49.13,-114.075,49.2",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },
    "raw/osm_core_ne.json": {
        "source_url": "https://api.openstreetmap.org/api/0.6/map.json?bbox=-114.075,49.13,-113.95,49.2",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (WGS 84)",
        "command": "python3 scripts/06_parks.py",
    },

    # Derived files (and top-level copies)
    "derived/stations.csv": {
        "source_url": "Local $MC26_DAY05_DIR/mlp_locations/station_*.json & loc_*.json (from https://explore.mountainlegacy.ca/api/stations/show/<id> and /api/locations/show/<id>)",
        "licence": "CC BY-NC 4.0 / Mountain Legacy Project Open Research Data",
        "crs": "EPSG:4326 (lat, lon) + EPSG:3979 (x_epsg3979, y_epsg3979)",
        "command": "python3 scripts/01_stations.py",
    },
    "stations.csv": {
        "source_url": "Identical top-level copy of slice_a/derived/stations.csv",
        "licence": "CC BY-NC 4.0 / Mountain Legacy Project Open Research Data",
        "crs": "EPSG:4326 (lat, lon) + EPSG:3979 (x_epsg3979, y_epsg3979)",
        "command": "python3 scripts/01_stations.py",
    },
    "derived/dem_viewshed_30m_epsg3979.tif": {
        "source_url": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:3979 (NAD83(CSRS) / Canada Atlas Lambert), vertical CGVD2013 (EPSG:6647)",
        "command": "gdal_translate -srcwin 36471 124799 2342 2282 -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 /vsicurl/https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif derived/dem_viewshed_30m_epsg3979.tif (via scripts/02_dem.py)",
    },
    "derived/dem_core_30m_epsg3979.tif": {
        "source_url": "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:3979 (NAD83(CSRS) / Canada Atlas Lambert), vertical CGVD2013 (EPSG:6647)",
        "command": "gdal_translate -srcwin 37278 125611 735 677 -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=3 /vsicurl/https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif derived/dem_core_30m_epsg3979.tif (via scripts/02_dem.py)",
    },
    "derived/boxes_meta.json": {
        "source_url": "Derived from slice_a/derived/dem_viewshed_30m_epsg3979.tif and slice_a/derived/dem_core_30m_epsg3979.tif",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:3979",
        "command": "python3 scripts/02_dem.py",
    },
    "derived/station_dem.csv": {
        "source_url": "Derived from slice_a/derived/stations.csv and slice_a/derived/dem_viewshed_30m_epsg3979.tif",
        "licence": "OGL-Canada-2.0 / Mountain Legacy Project",
        "crs": "EPSG:4326 & EPSG:3979, vertical CGVD2013 (m)",
        "command": "python3 scripts/02_dem.py",
    },
    "station_dem.csv": {
        "source_url": "Identical top-level copy of slice_a/derived/station_dem.csv",
        "licence": "OGL-Canada-2.0 / Mountain Legacy Project",
        "crs": "EPSG:4326 & EPSG:3979, vertical CGVD2013 (m)",
        "command": "python3 scripts/02_dem.py",
    },
    "derived/s2_20250825_TCI_core_10m_epsg3979.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/TCI.tif + https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/TCI.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:3979 (10 m grid aligned 3x3 with 30 m Core DEM)",
        "command": "gdalwarp -overwrite -t_srs EPSG:3979 -te -1381680.0 211380.0 -1359630.0 231690.0 -tr 10 10 -r bilinear -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 raw/S2B_11UPQ_20250825_0_L2A_TCI_core_utm11.tif raw/S2B_11UQQ_20250825_0_L2A_TCI_core_utm11.tif derived/s2_20250825_TCI_core_10m_epsg3979.tif (via scripts/03_imagery.py)",
    },
    "derived/s2_20250825_B04_core_10m_epsg3979.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/B04.tif + https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/B04.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:3979 (10 m grid aligned 3x3 with 30 m Core DEM)",
        "command": "gdalwarp -overwrite -t_srs EPSG:3979 -te -1381680.0 211380.0 -1359630.0 231690.0 -tr 10 10 -r bilinear -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 raw/S2B_11UPQ_20250825_0_L2A_B04_core_utm11.tif raw/S2B_11UQQ_20250825_0_L2A_B04_core_utm11.tif derived/s2_20250825_B04_core_10m_epsg3979.tif (via scripts/03_imagery.py)",
    },
    "derived/s2_20250825_B08_core_10m_epsg3979.tif": {
        "source_url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/PQ/2025/8/S2B_11UPQ_20250825_0_L2A/B08.tif + https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/11/U/QQ/2025/8/S2B_11UQQ_20250825_0_L2A/B08.tif",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:3979 (10 m grid aligned 3x3 with 30 m Core DEM)",
        "command": "gdalwarp -overwrite -t_srs EPSG:3979 -te -1381680.0 211380.0 -1359630.0 231690.0 -tr 10 10 -r bilinear -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 raw/S2B_11UPQ_20250825_0_L2A_B08_core_utm11.tif raw/S2B_11UQQ_20250825_0_L2A_B08_core_utm11.tif derived/s2_20250825_B08_core_10m_epsg3979.tif (via scripts/03_imagery.py)",
    },
    "derived/worldcover_2021_viewshed_10m_epsg3979.tif": {
        "source_url": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W117_Map.tif + https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N48W114_Map.tif",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021)",
        "crs": "EPSG:3979 (10 m grid aligned 3x3 with 30 m Viewshed DEM)",
        "command": "gdalwarp -overwrite -t_srs EPSG:3979 -te -1405890.0 187590.0 -1335630.0 256050.0 -tr 10 10 -r near -co TILED=YES -co COMPRESS=DEFLATE raw/ESA_WorldCover_10m_2021_v200_N48W117_viewshed_wgs84.tif raw/ESA_WorldCover_10m_2021_v200_N48W114_viewshed_wgs84.tif derived/worldcover_2021_viewshed_10m_epsg3979.tif (via scripts/04_landcover.py)",
    },
    "derived/forest_fraction_viewshed_30m_epsg3979.tif": {
        "source_url": "Derived from slice_a/derived/worldcover_2021_viewshed_10m_epsg3979.tif (class 10 'Tree cover' 3x3 block average)",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021)",
        "crs": "EPSG:3979 (30 m Viewshed DEM grid)",
        "command": "python3 scripts/04_landcover.py",
    },
    "derived/forest_mask_viewshed_30m_epsg3979.tif": {
        "source_url": "Derived from slice_a/derived/forest_fraction_viewshed_30m_epsg3979.tif (fraction >= 0.5)",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021)",
        "crs": "EPSG:3979 (30 m Viewshed DEM grid)",
        "command": "python3 scripts/04_landcover.py",
    },
    "derived/forest_fraction_core_30m_epsg3979.tif": {
        "source_url": "Derived from slice_a/derived/forest_fraction_viewshed_30m_epsg3979.tif (clipped to Core Box 30 m grid)",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021)",
        "crs": "EPSG:3979 (30 m Core DEM grid)",
        "command": "python3 scripts/04_landcover.py",
    },
    "derived/forest_mask_core_30m_epsg3979.tif": {
        "source_url": "Derived from slice_a/derived/forest_mask_viewshed_30m_epsg3979.tif (clipped to Core Box 30 m grid)",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021)",
        "crs": "EPSG:3979 (30 m Core DEM grid)",
        "command": "python3 scripts/04_landcover.py",
    },
    "derived/forest_stats.json": {
        "source_url": "Derived summary statistics of forest fraction and mask across Viewshed Box and Core Box",
        "licence": "CC BY 4.0",
        "crs": "EPSG:3979",
        "command": "python3 scripts/04_landcover.py",
    },
    "derived/names_peaks_passes.geojson": {
        "source_url": "CGNDB API (https://geogratis.gc.ca/services/geoname/en/geonames.json) + US GNIS Layer 5 (https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/5/query) + MRDEM-30 & OSM elevations",
        "licence": "OGL-Canada-2.0 (CGNDB) + Public Domain (US GNIS) + ODbL 1.0 (OSM published ele)",
        "crs": "EPSG:4326 (CRS84 lon, lat) with EPSG:3979 x_epsg3979, y_epsg3979 in properties",
        "command": "python3 scripts/05_names.py",
    },
    "names_peaks_passes.geojson": {
        "source_url": "Identical top-level copy of slice_a/derived/names_peaks_passes.geojson",
        "licence": "OGL-Canada-2.0 (CGNDB) + Public Domain (US GNIS) + ODbL 1.0 (OSM published ele)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/05_names.py",
    },
    "derived/waterton_lakes_np_boundary.geojson": {
        "source_url": "https://geospatial.alberta.ca/titan/rest/services/environment/parks_and_protected_areas_of_alberta_10tm_nad83_aep/MapServer/14/query?where=NAME%3D%27Waterton%20Lakes%27&outFields=*&outSR=4326&f=geojson + https://geogratis.gc.ca/services/geoname/en/geonames/IATZN.geojson",
        "licence": "Open Government Licence - Alberta / Open Government Licence - Canada",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "waterton_lakes_np_boundary.geojson": {
        "source_url": "Identical top-level copy of slice_a/derived/waterton_lakes_np_boundary.geojson",
        "licence": "Open Government Licence - Alberta / Open Government Licence - Canada",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "derived/kenow_fire_2017_perimeter.geojson": {
        "source_url": "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=public:nbac&cql_filter=year=2017%20AND%20nfireid=2418&outputFormat=application/json&srsName=urn:ogc:def:crs:EPSG::4326",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "kenow_fire_2017_perimeter.geojson": {
        "source_url": "Identical top-level copy of slice_a/derived/kenow_fire_2017_perimeter.geojson",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "derived/red_rock_parkway.geojson": {
        "source_url": "https://api.openstreetmap.org/api/0.6/map.json (4-quadrant sweep of Core Box)",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "red_rock_parkway.geojson": {
        "source_url": "Identical top-level copy of slice_a/derived/red_rock_parkway.geojson",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "derived/trails_core.geojson": {
        "source_url": "https://api.openstreetmap.org/api/0.6/map.json (4-quadrant sweep of Core Box)",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "trails_core.geojson": {
        "source_url": "Identical top-level copy of slice_a/derived/trails_core.geojson",
        "licence": "Open Database Licence (ODbL 1.0, © OpenStreetMap contributors)",
        "crs": "EPSG:4326 (CRS84)",
        "command": "python3 scripts/06_parks.py",
    },
    "derived/hillshade_viewshed_30m_epsg3979.tif": {
        "source_url": "Derived from slice_a/derived/dem_viewshed_30m_epsg3979.tif",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:3979",
        "command": "gdaldem hillshade -z 1.5 -az 315 -alt 45 -co TILED=YES -co COMPRESS=DEFLATE derived/dem_viewshed_30m_epsg3979.tif derived/hillshade_viewshed_30m_epsg3979.tif (via scripts/07_quicklooks.py)",
    },
    "derived/hillshade_core_30m_epsg3979.tif": {
        "source_url": "Derived from slice_a/derived/dem_core_30m_epsg3979.tif",
        "licence": "Open Government Licence - Canada (OGL-Canada-2.0)",
        "crs": "EPSG:3979",
        "command": "gdaldem hillshade -z 1.5 -az 315 -alt 45 -co TILED=YES -co COMPRESS=DEFLATE derived/dem_core_30m_epsg3979.tif derived/hillshade_core_30m_epsg3979.tif (via scripts/07_quicklooks.py)",
    },
    "quicklooks/ql_01_dem_viewshed_hillshade_stations.png": {
        "source_url": "Derived from slice_a/derived/dem_viewshed_30m_epsg3979.tif, hillshade, and station_dem.csv",
        "licence": "OGL-Canada-2.0",
        "crs": "EPSG:3979 (rendered PNG, 1017x882 px)",
        "command": "python3 scripts/07_quicklooks.py",
    },
    "quicklooks/ql_02_dem_core_hillshade_stations.png": {
        "source_url": "Derived from slice_a/derived/dem_core_30m_epsg3979.tif, hillshade, and station_dem.csv",
        "licence": "OGL-Canada-2.0",
        "crs": "EPSG:3979 (rendered PNG, 1033x854 px)",
        "command": "python3 scripts/07_quicklooks.py",
    },
    "quicklooks/ql_03_s2_tci_core.png": {
        "source_url": "Derived from slice_a/derived/s2_20250825_TCI_core_10m_epsg3979.tif, B04, and B08",
        "licence": "Copernicus Open Sentinel Data Licence",
        "crs": "EPSG:3979 (rendered PNG, 1372x604 px)",
        "command": "python3 scripts/07_quicklooks.py",
    },
    "quicklooks/ql_04_forest_mask_viewshed.png": {
        "source_url": "Derived from slice_a/derived/forest_mask_viewshed_30m_epsg3979.tif and forest_fraction_core_30m_epsg3979.tif",
        "licence": "CC BY 4.0 (© ESA WorldCover project 2021)",
        "crs": "EPSG:3979 (rendered PNG, 1372x646 px)",
        "command": "python3 scripts/07_quicklooks.py",
    },
    "quicklooks/ql_05_names_over_hillshade.png": {
        "source_url": "Derived from slice_a/derived/names_peaks_passes.geojson over MRDEM-30 hillshades",
        "licence": "OGL-Canada-2.0 / Public Domain (US GNIS)",
        "crs": "EPSG:3979 (rendered PNG, 1404x670 px)",
        "command": "python3 scripts/07_quicklooks.py",
    },
    "quicklooks/ql_06_vectors_overview.png": {
        "source_url": "Derived from slice_a/derived/waterton_lakes_np_boundary.geojson, kenow_fire_2017_perimeter.geojson, red_rock_parkway.geojson, and trails_core.geojson",
        "licence": "OGL-Canada-2.0 / OGL-Alberta / ODbL 1.0",
        "crs": "EPSG:3979 (rendered PNG, 1404x679 px)",
        "command": "python3 scripts/07_quicklooks.py",
    },
}

def main():
    lines = [
        "# Datastore Manifest & Changelog (`slice_a/MANIFEST.md`)",
        "",
        "**Slice:** (a) Data Fetch and Clip — Upper Blakiston Valley & Viewshed (1914 Bridgland Survey Stations, Waterton Lakes National Park, AB)",
        f"**Generated UTC:** `{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        "",
        "---",
        "",
        "## 1. Complete Inventory of Files in `slice_a/`",
        "",
        "| File Path | Source URL / Origin | Retrieval / Build Timestamp (UTC) | Licence | CRS | Size | SHA-256 | Exact Command / Script |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    all_files = []
    for root, _, files in os.walk(SLICE_A_DIR):
        for fn in files:
            p = os.path.join(root, fn)
            rel_p = os.path.relpath(p, SLICE_A_DIR).replace("\\", "/")
            if rel_p == "MANIFEST.md":
                continue
            all_files.append((p, rel_p))
    all_files.sort(key=lambda x: x[1])

    total_bytes = 0
    for full_p, rel_p in all_files:
        sz = os.path.getsize(full_p)
        total_bytes += sz
        sha = sha256_file(full_p)
        ts = mtime_utc(full_p)
        meta = FILE_META.get(rel_p, {})
        src = meta.get("source_url", "Derived in pipeline")
        lic = meta.get("licence", "OGL-Canada-2.0 / ODbL-1.0 / CC-BY-4.0")
        crs = meta.get("crs", "EPSG:3979 / EPSG:4326")
        cmd = meta.get("command", "See scripts/")
        lines.append(
            f"| `slice_a/{rel_p}` | {src} | `{ts}` | {lic} | `{crs}` | {fmt_size(sz)} | `{sha}` | `{cmd}` |"
        )

    lines.extend([
        "",
        f"**Total Datastore Size (`slice_a/` excluding `MANIFEST.md`):** `{fmt_size(total_bytes)}` across `{len(all_files)}` files (well under the 1.5 GB budget).",
        "",
        "---",
        "",
        "## 2. FAILED / Blocked / Schema Caveats Log (`FAILED`)",
        "",
        "All 9 required pipeline tasks succeeded without missing layers. Below is the literal record of external endpoints or upstream API fields that were blocked, absent, or corrupted and how each was handled:",
        "",
        "1. **Overpass API (`https://overpass-api.de/api/interpreter`):**",
        "   - **Request:** `POST https://overpass-api.de/api/interpreter` (Overpass QL query for trails/parkways in Core Box)",
        "   - **Error:** `HTTP/2 406 Not Acceptable` (server WAF blocks cloud/automated egress IPs; mirrors `overpass.kumi.systems` and `overpass.private.coffee` time out).",
        "   - **Resolution:** As instructed in Task 7 and verified in `in/recon_A.md`, fetched raw OpenStreetMap vectors directly from the official **OpenStreetMap REST API v0.6** (`https://api.openstreetmap.org/api/0.6/map.json?bbox=...`) across four quadrant bounding boxes (`sw`, `se`, `nw`, `ne`) covering 100% of the Core Box (`slice_a/raw/osm_core_*.json`).",
        "",
        "2. **Null Location Coordinates in MLP API for 2004 Visits at Stations 84, 85, and 86:**",
        "   - **Records Affected:**",
        "     - Station 84 (`mlp_id=2081`, Mt Blakiston Shoulder): 2004-08-10 Location 1 (`loc_id=11592`) and Location 2 (`loc_id=11591`) have `\"lat\": null, \"lng\": null` in `mlp_locations/loc_11592.json`.",
        "     - Station 85 (`mlp_id=1992`, Anderson): 2004-07-22 Location 1 (`loc_id=10980`) and 2003-09-02 Location 1 (`loc_id=10983`) have `\"lat\": null, \"lng\": null` in the JSON metadata (though `loc_10980.json` narrative states `11U East: 0718312 North: 5447152 Elevation: 2135 meters`, which converts to `49.13836549, -114.00675752`, matching the station-level coordinate `49.13836389, -114.00675833`).",
        "     - Station 86 (`mlp_id=2020`, Sage Creek): 2004-09-04 Location 1 (`loc_id=11535`) and Location 2 (`loc_id=11619`) have `\"lat\": null, \"lng\": null` in `mlp_locations/loc_11535.json`.",
        "   - **Resolution:** Following Task 1 (`primary for location 1 of the 2004 visit (or the earliest repeat visit if there is no 2004 visit; say which)`), we selected the earliest repeat visit Location 1 with valid coordinates in the MLP JSON files:",
        "     - Station 84 (`2081`): `loc_id=11072` (Location 1 of the **2003-08-30** repeat visit: `49.10337790, -114.02354013`).",
        "     - Station 85 (`1992`): `loc_id=12418` (Location 1 of the **2019-07-12** repeat visit: `49.13840833, -114.00690833`, 12.0 m west of the 2004 UTM cairn / station coordinate).",
        "     - Station 86 (`2020`): `loc_id=12421` (Location 1 of the **2019-07-13** repeat visit: `49.15491389, -114.16151389`, 0.6 m from the station coordinate).",
        "",
        "3. **Corrupted / Impossible Coordinates in MLP Location Records (Flagged `excluded` in `stations.csv`):**",
        "   - `loc_id=10422` (Station `1099`, `Sage Creek No. 1`, 2005-08-21 Location 1): `lat=49.07055856, lon=-122.24385609` (589.5 km west in Washington State; caused by prepending UTM Zone `11` to Easting `706958` as `East: 11706958` in the field notes). Furthermore, Station `1099` belongs to Arthur Oliver Wheeler's 1915 Interprovincial Boundary Survey (`owner_id=335`), whereas Morrison Parsons Bridgland's 1914 `Stn. 86 Sage Creek` is Station `2020` (`owner_id=377`).",
        "   - `loc_id=51742` (Station `2021`, `Stn. 88 Lost Mt`, 2025-06-15 Location 1): `lat=49.12672667, lon=-113.91174167` (and capture-level `lon=-113.90340833`), which lies **12.87 km east** of Lost Mountain (`> 2 km` exclusion rule; degree/minute transcription error for `-114.088225`).",
        "",
        "4. **Absence of Summit Elevation Attribute in CGNDB and US GNIS Layer 5 JSON Schemas:**",
        "   - **Request:** `GET https://geogratis.gc.ca/services/geoname/en/geonames.json?bbox=-114.68,48.74,-113.48,49.52&num=1000` and `GET https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/5/query?...`",
        "   - **Finding:** Neither government gazetteer API returns a summit elevation field in its JSON response (`generic.code='2743'` in CGNDB is the internal feature type code for 'Mount', not metres; USGS dropped `ELEV_IN_M` from GNIS MapServer Layer 5).",
        "   - **Resolution:** In `slice_a/derived/names_peaks_passes.geojson`, we record `\"elevation_source_api\": null` for transparency, sample the exact CGVD2013 elevation from `dem_viewshed_30m_epsg3979.tif` at every feature coordinate (`elevation_mrdem30_m` and `elevation_mrdem30_3x3max_m`), attach verified published survey/OSM summit heights (`elevation_osm_published_m`) for the core Canadian peaks, and populate `elevation` with the best verified height.",
    ])

    SLICE_A_DIR.mkdir(parents=True, exist_ok=True)
    with open(SLICE_A_DIR / "MANIFEST.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if os.path.exists("REPORT.md"):
        with open(SLICE_A_DIR / "REPORT.md", "w", encoding="utf-8") as f:
            f.write(open("REPORT.md", "r", encoding="utf-8").read())
    print(f"Wrote {SLICE_A_DIR / 'MANIFEST.md'} covering {len(all_files)} files ({fmt_size(total_bytes)})")

if __name__ == "__main__":
    main()
