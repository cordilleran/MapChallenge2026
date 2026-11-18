#!/usr/bin/env bash
# Day 17: merge the US tiles (D348), then rerun S1 -> S4 with the extended near grid.
# Usage: set -a; . ./your.env; set +a; day-17/scripts/run_all_with_us.sh GRID_FILE   (GRID_FILE holds the 'grid x0 x1 y0 y1 ny' line from s1b)
set -euo pipefail
: "${MC26_DAY17_DATA:?set it (see day-17/env.example)}"
US=$MC26_DAY17_DATA/us
L=$MC26_DAY17_DATA/derived
P=${MC26_PY:-python3}   # the Day 17 environment (day-17/requirements.txt)
cd "$(dirname "$0")"
read -r X0 X1 Y0 Y1 NY < <(grep '^grid' "$1" | awk '{print $2,$3,$4,$5,$6}')
[ -n "${NY:-}" ] || { echo "no grid line in $1"; exit 1; }
# DSM: EPT tiles (s1b_us_lidar.py); DEM: 3DEP 1 m bare earth, warped to the same grid (us_dem_raw.tif; see README)
gdalbuildvrt -q -overwrite -srcnodata -9999 -vrtnodata -9999 "$US/us_dsm.vrt" "$US"/dsm_t??.tif
gdal_translate -q -projwin "$X0" "$Y1" "$X1" "$Y0" -a_nodata -9999 "$US/us_dsm.vrt" "$US/us_dsm_raw.tif"
for k in dsm dem; do
  gdal_fillnodata -q -md 6 -co COMPRESS=DEFLATE -co TILED=YES "$US/us_${k}_raw.tif" "$US/us_${k}_2m.tif"
done
"$P" -I s1_surfaces.py > "$L/s1.log" 2>&1
"$P" s3_shade.py > "$L/s3.log" 2>&1
"$P" s3_weekly.py > "$L/s3w.log" 2>&1
"$P" s3_weekly_check.py > "$L/s3wc.log" 2>&1
"$P" s4_export.py > "$L/s4.log" 2>&1
echo DONE
