#!/usr/bin/env bash
# Run Day 2 from the FWA stream network to the finished map and the site images (about 30 seconds).
# Required environment variables: day-02/README.md and day-02/env.example (MC26_DAY02_DATA, MC26_FWA, MC26_DEM_TIF).
set -euo pipefail
cd "$(dirname "$0")/.."
Rscript day-02/scripts/01_windows.R          # windows, sinuosity and gradient
Rscript day-02/scripts/02_map.R              # the Letter map (PNG kept local, PDF)
Rscript day-02/scripts/03_site_images.R      # page, detail and calendar images (WebP)
mkdir -p site/files && cp -f day-02/out/day02_final.pdf site/files/
Rscript site/calendar.R                      # the calendar, from site/days.yml
echo "Done. Build the site with: quarto render site"
