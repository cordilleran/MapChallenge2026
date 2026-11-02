#!/usr/bin/env bash
# Day 1 step 9 (GRASS 8.4): local units cut only at confluences of streams at or above a Strahler order N
# (or Shreve magnitude M), on the area-threshold networks made in step 7 (str_t*, dir_t*).
# Reaches below the cut drain into the unit that receives them, as in the BC 1:50k set.
# Own mapset only. Safe rerun: skips outputs that exist.
set -euo pipefail
LOC=${MC26_GRASS_LOC:?set MC26_GRASS_LOC to the GRASS location folder (projected, EPSG:3005)}
DATA=${MC26_DATA:?set MC26_DATA to the Day 1 working folder}
MAPSET=${MC26_MAPSET:-mapchallenge2026}                                  # GRASS mapset for this project's own rasters
DEM=${MC26_DEM:?set MC26_DEM to the DEM raster as name@mapset}
export DATA DEM MAPSET
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: its variables expand inside GRASS, from the exported environment
grass "$LOC/$MAPSET" --exec bash -c '
  set -euo pipefail
  g.mapsets mapset="${DEM##*@}" operation=add
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  for NET in 5 10; do
    g.findfile element=cell file=ord_t$NET mapset="$MAPSET" >/dev/null 2>&1 || r.stream.order stream_rast=str_t$NET direction=dir_t$NET strahler=ord_t$NET shreve=mag_t$NET memory=6000
    for N in 2 3 4 5; do
      OUT="$DATA"/units_o${NET}_${N}.tif
      [ -e "$OUT" ] && continue
      r.mapcalc "sub_o${NET}_${N} = if(ord_t$NET >= $N, str_t$NET, null())" --overwrite
      r.stream.basins direction=dir_t$NET stream_rast=sub_o${NET}_${N} basins=units_o${NET}_${N} memory=6000 --overwrite
      r.out.gdal input=units_o${NET}_${N} output=$OUT format=GTiff type=Int32 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
    done
    for M in 10 20; do
      OUT="$DATA"/units_m${NET}_${M}.tif
      [ -e "$OUT" ] && continue
      r.mapcalc "sub_m${NET}_${M} = if(mag_t$NET >= $M, str_t$NET, null())" --overwrite
      r.stream.basins direction=dir_t$NET stream_rast=sub_m${NET}_${M} basins=units_m${NET}_${M} memory=6000 --overwrite
      r.out.gdal input=units_m${NET}_${M} output=$OUT format=GTiff type=Int32 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite
    done
  done
  r.out.gdal input=ord_t5 output="$DATA"/ord_t5.tif format=GTiff type=Int32 createopt=COMPRESS=DEFLATE --overwrite
  echo ALLDONE
'
