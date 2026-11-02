#!/usr/bin/env bash
# Day 1 step 14 (GRASS 8.4): accumulate the ERA5-Land 1991-2020 mean annual runoff depth down the DEM.
#   ro30   : ERA5-Land ro (mm/yr, 0.1 deg, bilinear to 1 km in R) resampled bicubic to the 30 m grid
#   acc_ro : sum of upstream cell runoff depths (mm); acc_ro / acc_area = mean upstream runoff depth (mm)
# Own mapset only. Safe rerun: stops if the output exists.
set -euo pipefail
LOC=${MC26_GRASS_LOC:?set MC26_GRASS_LOC to the GRASS location folder (projected, EPSG:3005)}
DATA=${MC26_DATA:?set MC26_DATA to the Day 1 working folder}
MAPSET=${MC26_MAPSET:-mapchallenge2026}                                  # GRASS mapset for this project's own rasters
DEM=${MC26_DEM:?set MC26_DEM to the DEM raster as name@mapset}
export DATA DEM
[ -e "$DATA/acc_ro.tif" ] && { echo "exists: $DATA/acc_ro.tif"; exit 1; }
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: its variables expand inside GRASS, from the exported environment
grass "$LOC/$MAPSET" --exec bash -c '
  set -euo pipefail
  g.mapsets mapset="${DEM##*@}" operation=add
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  r.in.gdal input="$DATA"/ro_mm_1991_2020_3005_1km.tif output=ro1km --overwrite
  g.region raster=ro1km -p | head -3
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  r.resamp.interp input=ro1km output=ro30 method=bicubic --overwrite
  r.mapcalc "ro30f = if(isnull(ro30), 0, ro30)" --overwrite
  r.watershed -a elevation=$DEM flow=ro30f accumulation=acc_ro convergence=5 memory=6000 --overwrite
  r.out.gdal input=acc_ro output="$DATA"/acc_ro.tif format=GTiff type=Float64 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
  r.out.gdal input=ro30 output="$DATA"/ro30.tif format=GTiff type=Float32 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
  echo ALLDONE
'
