# Day 15: The Underside of the World (Inside out)

The ground seen from the centre of the Earth, coloured by how far away it is. The page is `site/day-15.qmd`; the zoom viewer is `site/js/day15.js` (OpenSeadragon).

| File | What it is |
| :--- | :--- |
| `static/inside_common.py` | Distance from the centre (WGS84 ellipsoid + EGM2008 geoid + Earth2014 bedrock), sampling, inward normals, shadows cast from inside, colour and index lines. |
| `static/render_global.py` | The world on a mirrored Equal Earth map, three views, for the zoom viewer. Each point is lit from inside, raking from the upper left. |
| `static/render_inside.py` | Close-ups on a mirrored Lambert azimuthal equal-area map, lit by a lamp inside the Earth. |
| `static/site_assets.py` | Deep Zoom tiles (the Day 6 method), WebP stills, the thumbnail and `site/data/day15.json`. |

## Run

```bash
pip install -r static/requirements.txt
python -I static/render_global.py RAW OUT --width 9000
python -I static/render_inside.py RAW OUT andes -15 -70
python -I static/render_inside.py RAW OUT fennoscandia 63 30.5
python -I static/site_assets.py OUT ../site
```

Blue Marble NG, August 2004 (NASA Earth Observatory), saved as `RAW/bmng_200408_5400.jpg` (sha256 begins `2048023ccc62250c`):

```bash
curl -L -o RAW/bmng_200408_5400.jpg https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/bmng-base/august/world.200408.3x5400x2700.jpg
```

Tested with Python 3.12. pyshtools downloads Earth2014 (bedrock, degree 2,160) and EGM2008 into its cache on first use. Decision numbers (D389 to D393) refer to the project's decision log, kept outside this repository.
