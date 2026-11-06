# Day 5: Six views on a valley

An interactive map of what could be seen from six camera stations (84 to 89) of M.P. Bridgland's 1914 photographic survey of the upper Blakiston Valley, Waterton Lakes National Park, Alberta, out to 30 km (EPSG:3979, Canada Atlas Lambert). The page shows bare-earth viewsheds computed with GRASS r.viewshed, their overlap, forest canopy scenarios (10, 20 and 30 m, from ESA WorldCover), a 120 m drone view, the effect of terrain-model error (50 random error fields each at 2.6 m and 8 m RMSE), and a switch between the recorded station point and the local high point. For each station a simulated 360-degree panorama from the 30 m terrain model shows the named peaks, and the seven thesis plates sit on it beside their repeat photographs; for plate 597 the skyline is matched to the terrain to test where the camera pointed. A line-of-sight profile tool is built but hidden on the page until it handles the station positions (D95).

Live: <https://cordilleran.github.io/MapChallenge2026/day-05.html>

## Data and Licences

- Mountain Legacy Project (MLP) Station and Location Records: Survey station metadata and vantage point coordinates from the Mountain Legacy Project Explorer API (`https://explore.mountainlegacy.ca`). Read from the public API on 5 November 2026. The ids, positions, bearings and capture ids published in `site/data/day05/` follow the Mountain Legacy Project's terms, not this repository's CC BY licence; free-text capture comments are kept out of the published files until those terms are confirmed.
- Natural Resources Canada (NRCan) Medium Resolution Digital Elevation Model (MRDEM-30): 30 m bare-earth digital terrain model mosaic in EPSG:3979 (CGVD2013 vertical datum). Open Government Licence - Canada (OGL-Canada-2.0).
- Copernicus Sentinel-2 L2A Imagery: Surface reflectance imagery acquired 25 August 2025 (tiles 11UPQ and 11UQQ), retrieved via Earth Search by Element 84 from AWS Open Data. Copernicus Open Sentinel Data Licence (contains modified Copernicus Sentinel data 2025).
- ESA WorldCover 2021 v200: Global 10 m land cover classification (11 classes). Creative Commons Attribution 4.0 International (CC BY 4.0, copyright ESA WorldCover project 2021).
- Canadian Geographical Names Database (CGNDB): Official geographical names for peaks and passes in Alberta and British Columbia. Open Government Licence - Canada (OGL-Canada-2.0). Published summit heights for 16 peaks come from OpenStreetMap (ODbL); all other heights are the MRDEM-30 cell, and the page says which.
- USGS Geographic Names Information System (GNIS): Official US summit and pass gazetteer names from The National Map. Public Domain (US Government work).
- Parks Canada and Alberta Parks Vectors: Waterton Lakes National Park boundary from Alberta Parks and Protected Areas MapServer Layer 14 and CGNDB record IATZN. Open Government Licence - Alberta and Open Government Licence - Canada.
- OpenStreetMap Vectors: Road geometry for the Red Rock Parkway and hiking trail networks in the core study area from OpenStreetMap REST API v0.6. Open Database Licence (ODbL 1.0, copyright OpenStreetMap contributors).
- 2017 Kenow Fire Perimeter: Burned area boundary from Natural Resources Canada Canadian Wildland Fire Information System (CWFIS) National Burned Area Composite (NBAC WFS layer `public:nbac`, fire id 2418). Open Government Licence - Canada (OGL-Canada-2.0).
- Thesis Photographic Plates: Seven 1914 historical plates and repeat photographs published in Graham Watt's 2007 University of Victoria MSc thesis (published as Graham Duff Watt-Gremm) (*Taking a good long look: disturbance, succession, landscape change and repeat photography in the upper Blakiston Valley, Waterton Lakes National Park*, http://hdl.handle.net/1828/2481). Open access thesis repository (`https://dspace.library.uvic.ca/items/4ee99067-c147-4221-9c95-2410b113d969`). Historical survey photographs: Morrison Parsons Bridgland 1914, Library and Archives Canada / Mountain Legacy Project. Repeat photographs copyright Eric Higgs, Mountain Legacy Project. These photographs (`site/img/day05/photos/`) and the plate 597 overlay (`site/img/day05/wedge_plate597.webp`) are not covered by the repository's CC BY licence; see `LICENSE-IMAGES.md`.

## Pipeline

| Script | What it does | Inputs | Outputs | Needs network | Approximate run time |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `00_fetch_mlp.py` | Fetches station and location JSON records from the public MLP API with a 1 req/sec rate limit. | Public MLP API endpoints | `$MC26_DAY05_DIR/mlp_locations/station_<id>.json`, `loc_<id>.json` | Yes | ~30 s |
| `01_stations.py` | Parses MLP records, classifies candidate locations, transforms coordinates to EPSG:3979, and writes stations table. | `$MC26_DAY05_DIR/mlp_locations/*.json` | `slice_a/derived/stations.csv`, `slice_a/stations.csv` | No | < 1 s |
| `02_dem.py` | Clips NRCan MRDEM-30 COG to viewshed box and core box without resampling, and extracts station cell elevations. | NRCan MRDEM-30 COG (/vsicurl/), `slice_a/derived/stations.csv` | `slice_a/raw/mrdem30_viewshed_raw.tif`, `slice_a/derived/dem_viewshed_30m_epsg3979.tif`, `dem_core_30m_epsg3979.tif`, `boxes_meta.json`, `station_dem.csv` | Yes | not timed |
| `03_imagery.py` | Queries STAC for 2025-08-25 Sentinel-2 L2A tiles, downloads raw UTM clips, and warps core-box 10 m TCI, B04, and B08. | Earth Search STAC API, Sentinel-2 COGs (/vsicurl/) | `slice_a/raw/stac_sentinel2_20250825.json`, `slice_a/raw/*_utm11.tif`, `slice_a/derived/s2_20250825_*_core_10m_epsg3979.tif` | Yes | not timed |
| `04_landcover.py` | Clips ESA WorldCover 2021 tiles, warps to 10 m EPSG:3979, and derives 30 m forest fraction and binary forest mask rasters. | ESA WorldCover 2021 COGs (/vsicurl/), `slice_a/derived/dem_viewshed_30m_epsg3979.tif` | `slice_a/raw/ESA_WorldCover_*.tif`, `slice_a/derived/worldcover_2021_viewshed_10m_epsg3979.tif`, `forest_fraction_*_30m_epsg3979.tif`, `forest_mask_*_30m_epsg3979.tif`, `forest_stats.json` | Yes | not timed |
| `05_names.py` | Filters CGNDB and GNIS gazetteer points to viewshed box, samples DEM elevations, and attaches published summit heights with their source. | `slice_a/raw/cgndb_viewshed_raw.json`, `slice_a/raw/gnis_viewshed_raw.json` (downloaded by hand, see Reproduce), `slice_a/derived/dem_viewshed_30m_epsg3979.tif` | `slice_a/derived/names_peaks_passes.geojson`, `slice_a/names_peaks_passes.geojson` | No | a few seconds |
| `06_parks.py` | Fetches park boundary, Red Rock Parkway, core trails, and 2017 Kenow fire perimeter vectors. | Alberta Titan MapServer, CGNDB, CWFIS NBAC WFS, OpenStreetMap REST API v0.6 | `slice_a/raw/*`, `slice_a/derived/waterton_lakes_np_boundary.geojson`, `kenow_fire_2017_perimeter.geojson`, `red_rock_parkway.geojson`, `trails_core.geojson` | Yes | not timed |
| `07_quicklooks.py` | Computes hillshades and exports six quick-look verification figures under 1500 px. | `slice_a/derived/*` rasters and GeoJSON vectors | `slice_a/derived/hillshade_*`, `slice_a/quicklooks/ql_01..06_*.png` | No | not timed |
| `08_manifest.py` | Generates data inventory with SHA-256 hashes, file sizes, timestamps, and pipeline caveats. | All files in `slice_a/` | `slice_a/MANIFEST.md` | No | < 2 s |
| `09_viewsheds.py` | Computes GRASS r.viewshed deterministic runs: main, position variants, cumulative, GDAL cross-check, forest, drone. `--position highpoint` moves each observer to the highest cell of its 3x3 window and writes to `viewsheds_highpoint/`. | `slice_a/derived/dem_viewshed_30m_epsg3979.tif`, `forest_mask_viewshed_30m_epsg3979.tif`, `slice_a/stations.csv` | `$MC26_DAY05_DIR/viewsheds/vs_*`, `cum_*`, `variants.csv`, `deterministic_metrics.json` | No | ~1 to 2 min (mean 2.5 s per single viewshed run across 20 workers) |
| `10_probable_viewsheds.py` | Monte Carlo probable viewsheds (50 runs per station) with 2D FFT spatially correlated DEM errors (RMSE 2.6 m, or 8 m with `--rmse 8` into `viewsheds_rmse8/`; L 150 m, assumed). | `slice_a/derived/dem_viewshed_30m_epsg3979.tif`, `slice_a/stations.csv` | `$MC26_DAY05_DIR/viewsheds/prob_<stn>.tif`, `probable_metrics.json` | No | ~1 to 2 min (mean 2.8 s per realization across 20 workers) |
| `11_checks_and_plots.py` | Compiles verification metrics into CHECKS.md and generates four comparison plots. | `$MC26_DAY05_DIR/viewsheds/*_metrics.json`, `slice_a/derived/*` | `$MC26_DAY05_DIR/viewsheds/CHECKS.md`, `ql_*.png` | No | ~5 s |
| `run_viewsheds.sh` | Shell runner: 09, then 10 at 2.6 m and 8 m, then 09 from the high point, then 11. | Same as 09 to 11 | Same as 09 to 11 | No | not timed |
| `12_crop_thesis_plates.py` | Crops historic, repeat, and caption plates from 300 dpi thesis pages, stretches levels, and saves WebP assets. | Rendered thesis pages in `$MC26_DAY05_DIR/thesis_pages/` | `$MC26_DAY05_DIR/photos/*.webp`, `crops.json`, `contact_sheet.png`, `photos.json` | No | ~5 s |
| `13_base_overlays.py` | Warps viewshed hillshade and Sentinel-2 / hillshade core blend to Web Mercator (EPSG:3857). | `slice_a/derived/hillshade_viewshed_30m_epsg3979.tif`, `dem_core_30m_epsg3979.tif`, `s2_20250825_TCI_core_10m_epsg3979.tif` | `site/img/day05/base_viewshed.webp`, `base_core.webp`, `site/data/day05/base_bounds.json` | No | ~10 s |
| `14_viewshed_rasters.py` | Packs viewshed scenario masks into bit-packed greyscale PNGs and converts probable viewsheds to 8-bit PNGs. | `$MC26_DAY05_DIR/viewsheds/*`, `viewsheds_rmse8/*` | `site/img/day05/vs_pack_*.png`, `prob_*.png`, `vs_*_unc.png`, `site/data/day05/viewsheds_index.json`, `variants.json` | No | ~15 s |
| `15_profile_dem.py` | Exports core DEM grid as little-endian Int16 decimetres raw binary and writes grid metadata. | `slice_a/derived/dem_core_30m_epsg3979.tif`, `slice_a/stations.csv`, `slice_a/names_peaks_passes.geojson` | `site/data/day05/profile_dem.bin`, `site/data/day05/profile_dem.json` | No | < 2 s |
| `16_vectors.py` | Simplifies park, road, trail, and fire vectors, bundles stations and peaks, and samples line-of-sight test cases. | `slice_a/*` GeoJSON files, `slice_a/stations.csv`, `viewsheds/deterministic_metrics.json`, `vs_*_main.tif` | `site/data/day05/vectors.geojson`, `day-05/tests/los_sampled_20.json` | No | a few seconds |
| `17_render_panoramas.py` | Simulates 360-degree panoramic landscapes and skylines at 0.1 degree azimuth resolution for the six stations. | `slice_a/derived/dem_viewshed_30m_epsg3979.tif`, `worldcover_2021_viewshed_10m_epsg3979.tif`, `names_peaks_passes.geojson`, `viewsheds/vs_*_main.tif` | `$MC26_DAY05_DIR/pano/pano_<stn>.webp`, `pano_<stn>_grey.webp`, `skyline_<stn>.json` (with `D5_PANO_POSITION=highpoint` and `D5_VS_DIR=$MC26_DAY05_DIR/viewsheds_highpoint`: the same with `_hp`) | No | about 8 s per position |
| `18_fit_wedges.py` | Fits azimuth center, horizontal field of view, and camera roll for seven 1914 plates against synthetic skylines. | `$MC26_DAY05_DIR/photos/plate*_1914.webp`, `$MC26_DAY05_DIR/pano/skyline_*.json`, `pano_*.webp` | `$MC26_DAY05_DIR/pano/wedges.json`, `$MC26_DAY05_DIR/wedges.json`, `wedge_plate*.png` | No | not timed |
| `19_satellite_landcover.py` | Warps full viewshed-box Sentinel-2 true-colour mosaic and ESA WorldCover classification to Web Mercator. | Earth Search STAC, Sentinel-2 COGs (/vsicurl/), `slice_a/derived/worldcover_2021_viewshed_10m_epsg3979.tif`, `site/img/day05/base_viewshed.webp` | `site/img/day05/s2_viewshed.webp`, `landcover_viewshed.webp`, `site/data/day05/layers.json`, `$MC26_DAY05_DIR/s2full/*` | Yes | not timed |
| `20_highpoint_assets.py` | Copies both panorama sets and their peak tables to the site, packs the high-point viewsheds, and writes both observer positions per station. | `viewsheds/`, `viewsheds_highpoint/`, `pano/` | `site/img/day05/vs_pack_hp_*.png`, `site/img/day05/pano/pano_<stn>[_hp]*.webp`, `site/data/day05/pano_peaks[_hp].json`, `positions.json` | No | a few seconds |

## Tools

- GRASS GIS 8.4 (commands: `r.viewshed`, `r.out.gdal`, `r.external`)
- GDAL 3.12 (commands: `gdal_translate`, `gdalwarp`, `gdaldem`, `gdal_viewshed`, `gdalsrsinfo`, `gdaltransform`)
- Python 3 with numpy, scipy, Pillow, matplotlib (quick looks and checks) and GDAL python bindings (`osgeo.gdal`, `osgeo.ogr`, `osgeo.osr`); the system Python that ships with GDAL is simplest
- Node.js (for running `core_test.js` and `los_test.js`)
- Poppler utilities (`pdftoppm` for rendering thesis PDF pages)
- `curl` (two hand downloads), Quarto (the page), and for the smoke test Chromium and the Python package `websocket-client`
- The DejaVu Sans font for the plate 597 overlay labels (set `D5_FONT` to another TrueType file; a built-in font is used if none is found)

## Reproduce

1. Copy `env.example` to `.env` or export `MC26_DAY05_DIR` pointing to your data directory.
2. Render thesis pages 93 to 100 at 300 dpi grayscale from the open-access thesis PDF into `$MC26_DAY05_DIR/thesis_pages/`:
   ```bash
   mkdir -p "$MC26_DAY05_DIR/thesis_pages"
   pdftoppm -r 300 -png -gray -f 93 -l 100 /path/to/thesis.pdf "$MC26_DAY05_DIR/thesis_pages/page"
   ```
   Two downloads have no script; fetch them by hand into `$MC26_DAY05_DIR/slice_a/raw/` (the same commands are recorded in `08_manifest.py`):
   ```bash
   curl -s "https://geogratis.gc.ca/services/geoname/en/geonames.json?bbox=-114.68,48.74,-113.48,49.52&num=1000" -o "$MC26_DAY05_DIR/slice_a/raw/cgndb_viewshed_raw.json"
   curl -s "https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/5/query?geometry=-114.68,48.74,-113.48,49.52&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&outSR=4326&f=json" -o "$MC26_DAY05_DIR/slice_a/raw/gnis_viewshed_raw.json"
   ```
   `12_crop_thesis_plates.py` also needs `mlp_manifest.json`, the MLP capture records for the seven plates (plate, capture ids, LAC copy number, 2004 bearing). It was assembled from the MLP API during reconnaissance on 5 November 2026 and checked by hand against the API; no script in this folder rebuilds it yet.
3. Run the data retrieval and preparation pipeline:
   ```bash
   python3 day-05/scripts/00_fetch_mlp.py
   python3 day-05/scripts/01_stations.py
   python3 day-05/scripts/02_dem.py
   python3 day-05/scripts/03_imagery.py
   python3 day-05/scripts/04_landcover.py
   python3 day-05/scripts/05_names.py
   python3 day-05/scripts/06_parks.py
   python3 day-05/scripts/07_quicklooks.py
   python3 day-05/scripts/08_manifest.py
   ```
4. Run the GRASS viewshed calculations and checks:
   ```bash
   # 09 (recorded points), 10 at 2.6 m and 8 m, 09 from the local high point, then 11
   bash day-05/scripts/run_viewsheds.sh
   ```
5. Crop thesis plates and generate web assets:
   ```bash
   python3 day-05/scripts/12_crop_thesis_plates.py
   python3 day-05/scripts/13_base_overlays.py
   python3 day-05/scripts/14_viewshed_rasters.py
   python3 day-05/scripts/15_profile_dem.py
   python3 day-05/scripts/16_vectors.py
   python3 day-05/scripts/17_render_panoramas.py
   D5_PANO_POSITION=highpoint D5_VS_DIR="$MC26_DAY05_DIR/viewsheds_highpoint" python3 day-05/scripts/17_render_panoramas.py
   python3 day-05/scripts/18_fit_wedges.py
   python3 day-05/scripts/19_satellite_landcover.py
   python3 day-05/scripts/20_highpoint_assets.py
   ```
6. Run validation test suite:
   ```bash
   node day-05/tests/core_test.js
   node day-05/tests/los_test.js
   python3 day-05/tests/compare_los_samples.py
   ```
7. Render and verify the web page:
   ```bash
   (cd site && quarto render day-05.qmd)
   python3 -m http.server 8767 -d site/_site &
   python3 day-05/tests/smoke_d5.py http://127.0.0.1:8767/ /tmp/day05-shots
   kill %1
   ```

## How made

I chose the theme, the valley and the camera stations from my MSc thesis, and directed Claude Code (Anthropic; Claude Opus 5.5) to plan and audit the build. Claude Code handed most of the coding to Google's Gemini models through the agy command line (Gemini 4 Argon medium, and Gemini 3.8 Flash high after Argon reached its quota), then read and tested each piece before it entered the repository; Claude Haiku 5.5 checked the script port and the Stockdale reading. Before publishing, the code was reviewed blind by Claude Sonnet 5.5 and Gemini 3.8 Flash high, and each finding was checked against the code. I reviewed the page and its text before publishing.

## Tests

- `day-05/tests/core_test.js`: Validates `site/js/day05core.js`: (a) tests coordinates transformation from WGS84 (EPSG:4326) to Canada Atlas Lambert (EPSG:3979) against 20 reference points computed with GDAL 3.12 `gdaltransform` (asserts maximum horizontal position error < 0.05 m), and (b) checks line-of-sight visibility at the far end of 20 sampled station-to-target profiles against `vs_<stn>_main.tif` viewshed ground truth.
- `day-05/tests/los_test.js`: compares the visible flag of every 15 m sample along 60 stratified profiles (30 to visible targets, 30 to hidden ones, from `los_cases_60.json`, made by `make_los_cases.py`) with the r.viewshed raster, and times each profile. It prints the far-end agreement (59 of 60 on 5 November 2026) and writes every sample to `los_samples_out.json`; `compare_los_samples.py` then checks each sample against the raster cell it falls in. On 5 November 2026, 98.4% of 30,467 samples agreed, below the 99% target; the misses fall on visibility edges, where the browser samples the terrain bilinearly and r.viewshed by cell.
- `day-05/tests/smoke_d5.py`: Drives the rendered Day 5 site page in headless Chromium through the Chrome DevTools Protocol; asserts zero browser console errors, verifies zero requests to external hosts, tests the controls (station toggles and the visible area, scenarios, uncertainty layers, base layers, observer position, the station panel with panorama, peak tooltips and plate 597, the text fold-downs; the profile is checked to stay hidden), verifies the phone layout, and saves visual regression screenshots in light and dark mode.
