#!/usr/bin/env bash
# Day 1 step 4 (GRASS 8.4): flow accumulation weighted by elevation, on the 30 m DEM named in MC26_DEM
# (a patched 30 m DEM, extended south over the US reach). Runs in OWN mapset "mapchallenge2026" inside
# the GRASS location in MC26_GRASS_LOC; nothing is written to the DEM mapset.
#   acc_area : upstream area in cells (900 m2 each), MFD, same settings as accum_south_ext
#   acc_z    : sum of upstream cell elevations (m); acc_z/acc_area = mean upstream elevation
# Exports GeoTIFFs for R to $DATA. Safe rerun: stops if the outputs exist.
set -euo pipefail
LOC=${MC26_GRASS_LOC:?set MC26_GRASS_LOC to the GRASS location folder (projected, EPSG:3005)}
DATA=${MC26_DATA:?set MC26_DATA to the Day 1 working folder}
MAPSET=${MC26_MAPSET:-mapchallenge2026}                                  # GRASS mapset for this project's own rasters
DEM=${MC26_DEM:?set MC26_DEM to the DEM raster as name@mapset}
export DATA DEM
[ -e "$DATA/acc_area.tif" ] && { echo "exists, not overwriting: $DATA/acc_area.tif"; exit 1; }
[ -d "$LOC/$MAPSET" ] || grass -c "$LOC/$MAPSET" -e
# shellcheck disable=SC2016  # the inner script is single-quoted on purpose: its variables expand inside GRASS, from the exported environment
grass "$LOC/$MAPSET" --exec bash -c '
  set -euo pipefail
  g.mapsets mapset="${DEM##*@}" operation=add
  g.region n=612000 s=420000 e=1595000 w=1465000 align=$DEM
  g.region -p | grep -E "rows|cols"
  r.watershed -a elevation=$DEM accumulation=acc_area convergence=5 memory=6000
  r.watershed -a elevation=$DEM flow=$DEM accumulation=acc_z convergence=5 memory=6000
  r.mapcalc "dem = $DEM"
  for m in acc_area acc_z dem; do r.out.gdal input=$m output="$DATA"/$m.tif format=GTiff type=Float64 createopt=COMPRESS=DEFLATE,TILED=YES --overwrite; done
'
