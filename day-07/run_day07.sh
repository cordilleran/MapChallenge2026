#!/usr/bin/env bash
# Run Day 7 from public sources to the finished map (see day-07/README.md).
# Required: MC26_DAY07_DATA (a working folder outside the repo). Optional: MC26_NCEI_SUPERIOR
# (a local copy of the NOAA NCEI Lake Superior grid). Step 05 needs a Copernicus CDS key in
# ~/.cdsapirc and a Python with cdsapi; steps 10 to 13 need a Python with GDAL, numpy and scipy.
# PY_NC is a Python with xarray, netCDF4 and shapely (rose, cession check). Set PY_CDS, PY_NC and PY_GDAL to those interpreters if `python3` is not the right one.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${MC26_DAY07_DATA:?set MC26_DAY07_DATA}"
PY_CDS="${PY_CDS:-python3}"
PY_GDAL="${PY_GDAL:-python3}"
PY_NC="${PY_NC:-$PY_GDAL}"
Rscript day-07/scripts/01_fetch.R              # relief, lake floor, OSM, WBD, GBIF, Open-Meteo wind
Rscript day-07/scripts/02_prepare.R            # layers in UTM 15N, drainages, triple point
"$PY_CDS" day-07/scripts/05_era5_cds.py        # ERA5 fetch (skips the rose without xarray)
"$PY_NC" day-07/scripts/05_era5_cds.py         # the double rose (skips the fetch if files exist)
"$PY_NC" day-07/scripts/06_cessions_check.py   # treaty cessions under the towns (needs shapely)
"$PY_GDAL" day-07/scripts/10_htmc_fetch.py      # the four 1958 USGS 1:250,000 sheets
"$PY_GDAL" day-07/scripts/11_htmc_mosaic.py     # neatlines, NAD27 to UTM 15N, mosaic
"$PY_GDAL" day-07/scripts/12_htmc_inks.py       # ink plates
"$PY_GDAL" day-07/scripts/11b_htmc_georef_check.py  # 1958 water edges against today's
"$PY_GDAL" day-07/scripts/13_pits_1958.py       # 1958 pits screen (check image only, D323)
"$PY_GDAL" day-07/scripts/14_legend.py          # the 1958 legend as ink plates
Rscript day-07/scripts/07_waves.R              # waves of 10-16 April 1962 (estimate)
Rscript day-07/scripts/08_roads_out.R          # road notes for the border
Rscript day-07/scripts/03_map.R B              # the map (PDF, and PNG with grain)
Rscript day-07/scripts/04_site_images.R        # page, detail and calendar WebP
"$PY_GDAL" day-07/scripts/04b_tiles.py B       # Deep Zoom tiles for the site's zoom viewer (needs pdftoppm, Pillow)
