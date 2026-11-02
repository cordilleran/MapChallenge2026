#!/usr/bin/env bash
# Day 1 step 10 (GRASS 8.4): reach attribute tables (id, downstream reach, Strahler, Shreve) for the
# 5, 10 and 20 km2 networks, for the chain construction in 11_chain_units.R. Own mapset only.
set -euo pipefail
LOC=${MC26_GRASS_LOC:?set MC26_GRASS_LOC to the GRASS location folder (projected, EPSG:3005)}
DATA=${MC26_DATA:?set MC26_DATA to the Day 1 working folder}
MAPSET=${MC26_MAPSET:-mapchallenge2026}                                  # GRASS mapset for this project's own rasters
DEM=${MC26_DEM:?set MC26_DEM to the DEM raster as name@mapset}
THRESH=${*:-5}                                                           # thresholds in km2; only 5 is needed for the Day 1 maps
export DATA DEM THRESH
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: its variables expand inside GRASS, from the exported environment
grass "$LOC/$MAPSET" --exec bash -c '
  set -euo pipefail
  g.mapsets mapset="${DEM##*@}" operation=add
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  for NET in $THRESH; do
    OUT="$DATA"/reaches_t${NET}.csv
    [ -e "$OUT" ] && continue
    r.stream.order stream_rast=str_t$NET direction=dir_t$NET strahler=ordx_t$NET shreve=magx_t$NET elevation=$DEM accumulation=acc_area stream_vect=sv_t$NET memory=6000 --overwrite
    v.db.select map=sv_t$NET separator=comma file=$OUT --overwrite
  done
  echo ALLDONE
'
