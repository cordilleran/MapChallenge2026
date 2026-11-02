#!/usr/bin/env bash
# Day 1 step 7 (GRASS 8.4): local drainage units cut at every confluence of a threshold stream network,
# the same construction as the BC 1:50k WDIC units. One run per threshold (km2 of upstream area).
# Purpose: (a) find the threshold that best reproduces the 125 official Kettle units on the BC side,
#          (b) apply it to the US side, where no 1:50k set exists.
# Own mapset only. Safe rerun: skips thresholds whose GeoTIFF exists.
set -euo pipefail
LOC=${MC26_GRASS_LOC:?set MC26_GRASS_LOC to the GRASS location folder (projected, EPSG:3005)}
DATA=${MC26_DATA:?set MC26_DATA to the Day 1 working folder}
MAPSET=${MC26_MAPSET:-mapchallenge2026}                                  # GRASS mapset for this project's own rasters
DEM=${MC26_DEM:?set MC26_DEM to the DEM raster as name@mapset}
export DATA DEM
THRESH=${*:-5 10 20}
export THRESH
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: its variables expand inside GRASS, from the exported environment
grass "$LOC/$MAPSET" --exec bash -c '
  set -euo pipefail
  g.mapsets mapset="${DEM##*@}" operation=add
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  for T in $THRESH; do
    OUT="$DATA"/units_t${T}km2.tif
    [ -e "$OUT" ] && { echo "exists, skip $OUT"; continue; }
    CELLS=$(awk -v t="$T" "BEGIN{print int(t*1e6/900)}")
    r.stream.extract elevation=$DEM threshold=$CELLS memory=6000 stream_raster=str_t$T direction=dir_t$T --overwrite
    r.stream.basins direction=dir_t$T stream_rast=str_t$T basins=units_t$T memory=6000 --overwrite
    r.out.gdal input=units_t$T output=$OUT format=GTiff type=Int32 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
    r.out.gdal input=str_t$T output="$DATA"/streams_t${T}km2.tif format=GTiff type=Int32 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
  done
'
