#!/usr/bin/env bash
# Full batch execution script for Slice (b): 1914 Bridgland Camera Station Viewsheds
# Runs all 6 stations (84, 85, 86, 87, 88, 89):
#   1. Deterministic viewsheds (09_viewsheds.py: main, variants + position uncertainty, cumulative,
#      GDAL cross-check, forest 10/20/30m canopy scenarios, 120m drone scenario)
#   2. Probable viewsheds (10_probable_viewsheds.py: 50 Monte Carlo realizations per station, L=150m, r=30km),
#      once with RMSE=2.6m (into viewsheds/) and once with RMSE=8m (into viewsheds_rmse8/)
#   3. Deterministic viewsheds from the local high point (09_viewsheds.py --position highpoint, into viewsheds_highpoint/)
#   4. Quality checks (11_checks_and_plots.py: CHECKS.md and quick-look PNGs in $MC26_DAY05_DIR/viewsheds)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
WORKERS="${WORKERS:-20}"

echo "=== [1/4] Running deterministic viewsheds across all 6 stations ==="
"$PYTHON" "$SCRIPT_DIR/09_viewsheds.py" --stations 84 85 86 87 88 89 --workers "$WORKERS"

echo "=== [2/4] Running probable viewsheds (50 realizations/station, r=30000m, RMSE 2.6 m then 8 m) ==="
"$PYTHON" "$SCRIPT_DIR/10_probable_viewsheds.py" --stations 84 85 86 87 88 89 --n-runs 50 --rmse 2.6 --corr-len 150.0 --max-distance 30000 --workers "$WORKERS"
"$PYTHON" "$SCRIPT_DIR/10_probable_viewsheds.py" --stations 84 85 86 87 88 89 --n-runs 50 --rmse 8.0 --corr-len 150.0 --max-distance 30000 --workers "$WORKERS"

echo "=== [3/4] Running deterministic viewsheds from the local high point ==="
"$PYTHON" "$SCRIPT_DIR/09_viewsheds.py" --stations 84 85 86 87 88 89 --workers "$WORKERS" --position highpoint

echo "=== [4/4] Generating CHECKS.md and quick-look PNGs ==="
"$PYTHON" "$SCRIPT_DIR/11_checks_and_plots.py"

echo "=== All viewshed outputs and checks completed successfully ==="
