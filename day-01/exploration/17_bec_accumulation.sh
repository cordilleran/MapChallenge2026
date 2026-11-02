#!/usr/bin/env bash
# Day 1 step 17 (GRASS 8.4): accumulate the BEC wetness weight down the DEM (same settings as acc_ro). Own mapset.
set -euo pipefail
LOC=${MC26_GRASS_LOC:?set MC26_GRASS_LOC to the GRASS location folder (projected, EPSG:3005)}
DATA=${MC26_DATA:?set MC26_DATA to the Day 1 working folder}
MAPSET=${MC26_MAPSET:-mapchallenge2026}                                  # GRASS mapset for this project's own rasters
DEM=${MC26_DEM:?set MC26_DEM to the DEM raster as name@mapset}
export DATA DEM
[ -e "$DATA/acc_bec.tif" ] && { echo "exists: $DATA/acc_bec.tif"; exit 1; }
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: its variables expand inside GRASS, from the exported environment
grass "$LOC/$MAPSET" --exec bash -c '
  set -euo pipefail
  g.mapsets mapset="${DEM##*@}" operation=add
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  r.in.gdal input="$DATA"/bec_w.tif output=bec_w --overwrite
  r.watershed -a elevation=$DEM flow=bec_w accumulation=acc_bec convergence=5 memory=6000 --overwrite
  r.out.gdal -f input=acc_bec output="$DATA"/acc_bec.tif format=GTiff type=Float64 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
  echo ALLDONE
'
