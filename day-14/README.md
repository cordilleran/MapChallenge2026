# Day 14: The Bath, Drained (Borgesian map)

A Landlab model of the mud film left on a bathtub floor after a muddy-dog bath drained, drawn as a zoomable map down to 0.25 mm and compared with a photograph of the real floor. The page is `site/day-14.qmd`; the map is `site/day14_tub.html` with `site/js/day14.js`.

| File | What it is |
| :--- | :--- |
| `sim.py` | The model. Settling (rule), drawdown with Landlab `OverlandFlow` and threshold shear stripping, film drainage routed with Landlab `FlowAccumulator` (D-infinity) to the retreating shoreline with threshold channel cutting, and two rules (dewetting, tide lines). `python sim.py -h` lists the options; the defaults are the published run. |
| `scripts/photo_metrics.py` | Squares the photo to the 1280 x 520 mm model frame, flattens the lighting and measures it: share of pale floor along and across the tub, and channel orientation relative to the drain in three zones. |
| `scripts/compare.py` | Scores a run against the photo on the same measures. |
| `scripts/run_set.sh` | The published runs (19 at once, so about 19 cores): the base run at 2 mm, the same at 1 and 4 mm (grid test), and a 16-run sweep of the stripping rate `K` and the channel-cutting rate `Kr` at 4 mm. |
| `scripts/render_tiles.py` | Downscales a run to 0.25 mm (cubic enlargement plus synthesised sub-2 mm texture, rescaled so each 2 mm cell averages back to the model), shades it (vertical exaggeration 150) in three looks (sepia; grey with the mud tinted; wet mud, thickness as Beer-Lambert tone with gentle relief), and cuts light and dark tile pyramids of each, plus the photo's, for Leaflet. Also writes the drain-replay grid and the "added by rule" overlay. |
| `thinfilm.py` | A second model, for one patch: the mud as a thin film with a yield stress (Bingham lubrication flux, gravity, surface tension) on a 0.5 mm grid, started from the Landlab mud. `python thinfilm.py -h` lists the options. The disjoining-pressure (contact-angle) term is in the code, but at 0.5 mm the contact line is unresolved, so the published runs use `--theta 0.001` (fully wetting). |
| `scripts/fine_measures.py` | Measures of the 1-5 mm pattern for photo and model: edge length and Euler number of the palest fractions, and correlation length. |
| `scripts/tf_look.py`, `scripts/tf_figure.py` | Quick looks at thin-film runs, and the page's figure and measures (`site/data/day14/thinfilm.webp`, `thinfilm.json`). |
| `scripts/build_eda.py` | Gathers the charts' data (`site/data/day14/eda.json`) and the sweep thumbnails. |
| `requirements.in` | Direct dependencies. The environment is the Day 10 one (`day-10/requirements.txt`, Python 3.13, Landlab 2.11.0). |

## Run

```bash
export OMP_NUM_THREADS=1                      # single-threaded maths: about 12x faster for these grids
python -I scripts/photo_metrics.py            # reads the photo in data/source/
PY=../day-10/.venv/bin/python sh scripts/run_set.sh   # 19 runs at once; base 2 mm about 6 min, 1 mm about 45 min
python -I scripts/compare.py runs/base_2mm
python -I scripts/render_tiles.py runs/base_2mm ../site/data/day14 --photo   # without the photo: no photo tiles, slope -3.5
python -I scripts/build_eda.py
# the thin-film patch runs on the page (80 x 80 mm of the upper flank, 20 s, about 1-2 min each)
for t in 0.6 6; do python -I thinfilm.py runs/base_2mm runs/tf/s3/t$t --dx 0.5 --patch 300 30 80 80 --t-end 20 --mu 0.002 --tau $t --theta 0.001 --noise 0.6 --noise-corr 1; done
python -I thinfilm.py runs/base_2mm runs/tf/s2/n0.6_c1_t0.03 --dx 0.5 --patch 300 30 80 80 --t-end 20 --mu 0.002 --tau 0.03 --theta 0.001 --noise 0.6 --noise-corr 1
python -I scripts/tf_figure.py
```

`compare.py` and `build_eda.py` need `photo_metrics.py`'s outputs. `sim.py` and `render_tiles.py` also run without the photo.

## Assumptions (not measured)

- The wetted footprint in the photo is 1280 x 520 mm (the rim is 1360 x 610 mm; the photo shows the floor and lower walls). The photo is squared to it by its outline; its slight tilt and the wall curvature are not corrected.
- The floor falls 0.8 % toward the drain and dishes 3 mm across; the drain is 120 mm from the left end on the centre line.
- Mean settled mud 0.4 mm; pool 12 mm deep at the drain when the model starts; film 0.3 mm draining over 8 s.
- `K`, `tau_c`, `Kr` and `theta` are calibrated against the photo, not measured. The sweep shows the photo constrains `K` but hardly `Kr`.

## Data and licence

The photograph (18 March 2026) is GW's: `data/source/tub_20260318_noexif.jpg`, with its EXIF (which held a location) removed, so the whole chain can be repeated. Its rectified tiles are in `site/data/day14/tiles/photo/`. Code MIT; map, tiles, model output and text CC BY 4.0. No third-party data. Software: Landlab, NumPy, SciPy, Pillow; Leaflet on the page.
