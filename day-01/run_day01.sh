#!/usr/bin/env bash
# Run the Day 1 pipeline from the DEM to the finished maps. A step is skipped when its main output already exists, so the script can be rerun.
# Required environment variables are listed in day-01/README.md and in day-01/env.example (MC26_DATA, MC26_GRASS_LOC, MC26_DEM, MC26_FWA, MC26_BC50K, MC26_3DHP).
set -euo pipefail
cd "$(dirname "$0")/.."
D="${MC26_DATA:?set MC26_DATA to the Day 1 working folder}"
step() { local out="$1"; shift; if [ -e "$out" ]; then echo "skip (exists): $out"; else echo ">> $*"; "$@"; fi; }

step "$D/acc_area.tif"        bash   day-01/scripts/04_weighted_accumulation.sh     # flow accumulation and DEM export (GRASS)
step "$D/units_t5km2.tif"     bash   day-01/scripts/07_derive_units.sh 5            # streams and local basins at a 5 km2 threshold (GRASS)
step "$D/reaches_t5.csv"      bash   day-01/scripts/10_reach_tables.sh              # reach table for the chain rule (GRASS)
step "$D/units_a16.gpkg"      Rscript day-01/scripts/12_make_units_a16.R            # local units, area-chain rule, A = 16 km2
step "$D/us_3dhp.gpkg"        Rscript day-01/scripts/20_clip_3dhp.R                 # 3DHP flowlines inside the basin
step "$D/network3dhp.gpkg"    env MC26_TAG="" MC26_MINAREA=0 Rscript day-01/scripts/21_build_graph_3dhp.R   # unthinned network (for the density check)
step "$D/seg_area_end.csv"    Rscript day-01/scripts/23_density_calibration.R       # junction density by side; shows why 1.5 km2
step "$D/network3dhp_a15.gpkg" Rscript day-01/scripts/21_build_graph_3dhp.R         # thinned network (default MC26_TAG=_a15, MC26_MINAREA=1.5)
step "$D/arms3dhp_a15_mag.csv" Rscript day-01/scripts/22_shreve.R                    # Shreve magnitude on the arms
step "$D/arms3dhp_mag.csv"    env MC26_TAG="" Rscript day-01/scripts/22_shreve.R    # the same on the unthinned network (page comparison only)
# The remaining steps rebuild their outputs every run (the outputs are committed, so a skip test would never fire on a fresh clone)
env MC26_VARIANT=strahler Rscript day-01/scripts/24_final_static.R
env MC26_VARIANT=shreve   Rscript day-01/scripts/24_final_static.R
env MC26_TAG="" MC26_MINAREA=0 MC26_VARIANT=shreve Rscript day-01/scripts/24_final_static.R         # unthinned render, cropped for the page comparison
Rscript day-01/scripts/25_export_leaflet_data.R                                      # data for the Leaflet map
Rscript day-01/scripts/25a_check_upstream_area.R                                     # check only: why area is shown per junction, not per arm
Rscript day-01/scripts/26_relief.R                                                   # shaded relief for the Leaflet map
Rscript day-01/scripts/27_site_images.R                                              # page images, crops, calendar thumbnail
mkdir -p site/files
for f in day-01/out/day01_final_strahler.pdf day-01/out/day01_final_shreve.pdf; do cp -f "$f" site/files/; done   # PDFs are served from site/files
Rscript site/calendar.R                                                              # the calendar, from site/days.yml
echo "Done. Build the site with: quarto render site"
