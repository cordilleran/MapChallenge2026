# Day 17: Mountain's Shadow (Light and dark)

How much of the daylight year each place in the Grand Forks valley spends in shadow, cast by hills, trees and buildings, from airborne LiDAR. The page is `site/day-17.qmd`; the 3D map is `site/day17_shade.html` with `site/js/day17_shade.js` and `site/css/day17_shade.css` (three.js, vendored).

| File | What it is |
| :--- | :--- |
| `scripts/s1b_us_lidar.py` | US LiDAR south of the border: a 2 m DSM (highest return) from the USGS 3DEP EPT tiles, through PDAL. Prints the grid line that `run_all_with_us.sh` reads. It also writes ground-return DEM tiles, which the run does not use: the 3DEP 1 m DEM (below) is the US bare earth. |
| `scripts/s1_surfaces.py` | The near surfaces at 2 m (BC LiDAR 2025 and the US tiles), datum shifts to GEM-15, gaps filled from GEM-15, the DSM despiked (D349); the regional ring from GEM-15 at 15 m. |
| `scripts/horizon.py`, `scripts/sun.py` | Horizon angles by a convex-hull sweep along parallel lines (numba), and sun positions from pvlib every 5 minutes through 2026. |
| `scripts/s2_checks.py`, `scripts/s2_share_check.py` | Checks: noon sun on 21 December, horizons against a brute-force ray march, and the effect on shade share. |
| `scripts/s3_shade.py` | Shade share for the year, December and June, on the DSM and on the bare earth. |
| `scripts/s3_weekly.py`, `scripts/s3_weekly_check.py` | 27 weekly declination steps (December to June solstice, each standing for its mirror date), and the check that they rebuild the year. |
| `scripts/s4_export.py` | The page data in `site/data/day17/`: shade layers as WebP, heights, the readout grid, labels, and the weekly stacks as a temporal PCA basis (mean plus 6 components and a weight table; D353). |
| `scripts/run_all_with_us.sh` | Merges the US tiles, then reruns S1 to S4. |

## Run

```bash
set -a; . ./your.env; set +a            # see env.example
python -I scripts/s1b_us_lidar.py > grid.txt
# the US bare earth: USGS 3DEP 1 m DEM tiles (The National Map), averaged onto the 2 m grid
curl -s "https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Digital%20Elevation%20Model%20(DEM)%201%20meter&bbox=-118.55,48.93,-118.38,49.0&max=50&outputFormat=JSON" \
  | python3 -c "import json,sys; [print('/vsicurl/' + i['downloadURL']) for i in json.load(sys.stdin)['items']]" > dem_vsi.txt
PROJ_NETWORK=ON gdalwarp -t_srs EPSG:2955 -te 388445 5421997 399547 5428351 -tr 2 2 -r average \
  -co COMPRESS=DEFLATE -co TILED=YES $(cat dem_vsi.txt) "$MC26_DAY17_DATA/us/us_dem_raw.tif"
MC26_PY=/path/to/venv/bin/python scripts/run_all_with_us.sh grid.txt
python -I scripts/s2_checks.py; python -I scripts/s2_share_check.py
```

The GEM-15 crops in `raw/` (`gem15_dtm_15m_region.tif`, `gem15_dsm_mean_15m_region.tif`) are the regional window from Google's GEM-15 v1 (CC BY 4.0). Decision numbers (D334 to D354) refer to the project's decision log, kept outside this repository.
