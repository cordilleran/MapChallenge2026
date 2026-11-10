# Day 6 (Vintage): Sheet No. 16, repeated

The Interprovincial Boundary Commission's Sheet No. 16 (Kicking Horse Pass, Waputik Icefield and Yoho Valley; surveyed 1903 to 1913, revised edition 1925), drawn again from 2021 terrain and ice in the sheet's own manner, with the 1913 ice limit read from the sheet's blue contours. Page: `site/day-06.qmd`.

## Source

Office of the Surveyor-General of Canada, *Boundary between Alberta and British Columbia, Sheet 16*, revised edition, 1:62,500 (Ottawa: Surveyor-General's Office, 1925; catalogued as 1924), map, William C. Wonders Map Collection, University of Alberta Library, accessed via the Internet Archive, <https://archive.org/details/AB-BC-sheet16>. Public domain.

The build reads the 600 ppi TIFF master from that item (`AB-BC-sheet16.tif`, 9260 x 11484 px; `MC26_SHEET16`), kept outside the repository. The control points in `georef.py` and `data/check_stations.json` were read on the Internet Archive's JPEG (2315 x 2871 px), exactly a quarter of the master's size; `01_georef.py` scales them to whichever image it is given. The JPEG's colour compression blurred thin blue lines into the brown beside them; the master's sharper ink also needed one change to the red-ink rule in `ink.py` (dense brown had passed as red).

## Pipeline

Run from `day-06/scripts/` with the system Python (GDAL bindings) after `set -a; . ../.env; set +a` (see `env.example`). Step 07 also needs QGIS: `PYTHONPATH=/usr/share/qgis/python` (and `QGIS_PREFIX_PATH` if QGIS is not installed under `/usr`).

Tested with Python 3.14.4, GDAL 3.12.2, QGIS 4.2.3, numpy 2.3.5, scipy 1.16.3, Pillow 12.1.1 and pyproj 3.7.2 (Ubuntu system packages).

| Step | Script | What it does | Writes |
| :--- | :--- | :--- | :--- |
| 0 | `00_fetch.py` | Downloads once, never overwrites: MRDEM-30 window, glacier outlines 1984-2021 (rows in the window only, through the file's spatial index), OSM through Overpass (map layers, and summits), CGNDB names. Records source, licence and sha256. | `raw-261109/`, `manifest.json` |
| 1 | `01_georef.py` | Warps the scan: a bilinear map between the four printed graticule corners (taken as NAD27), plus one mean shift from 11 summit stations (`data/check_stations.json`); reports the held-out error. The warp is a second-order polynomial through a 9 x 9 grid of the model, so it reproduces the model exactly (`warp_check_m`). | `derived/sheet16_26911.tif` (10 m, for reading ink), `sheet16_26911_display.tif` (4 m, for the page), `georef_report.json` |
| 2 | `02_osm.py` | OSM to map layers in EPSG:26911. | `derived/osm.gpkg` |
| 3 | `03_ice1913.py` | Ice in 1913 = where the sheet's contours are blue, not brown (optical density per channel), over a grid of nine settings. Patches at the reviewed points in `data/not_ice.json` (blue creeks) are removed. | `derived/ice1913.gpkg`, `ice1913_metrics.json`, `out/quicklooks/ice1913_check.png` |
| 4 | `04_contours.py` | Contours from MRDEM-30: 100 ft (index every 1,000 ft) and 25 m (index every 250 m). | `derived/contours.gpkg` |
| 5 | `05_compare.py` | Ice areas inside the frame for 1913, 1985 and 2021, and the share of 1985 ice inside the 1913 line. | `derived/modern.gpkg`, `compare_metrics.json` |
| 5b | `peaks.py` | Summits: OSM positions and heights, CGNDB names, checked against every terrain-model summit and its prominence; unnamed high points. Reusable for any map (see its header). Run: `python3 peaks.py --osm $R/osm_peaks.json --names $R/cgndb.json --dem $R/mrdem30_window.tif --crs EPSG:26911 --out $MC26_DAY06_DIR/derived/peaks.gpkg` with `R=$MC26_DAY06_DIR/raw-261109`. Prints the summits to look at. | `derived/peaks.gpkg` |
| 6 | `06_layers.py` | Final layers: contours (feet and metres) split at the 2021 ice margin, outlines simplified for display, summits, high points and lake heights, names (glacier names moved into the 2021 ice with the angle of the contours, stepped apart where crowded, and placed so the whole name fits inside the frame, turned only if it cannot fit along the contours), creek stretches for names lettered along the creek, and a 5-minute NAD83 graticule. | `derived/map.gpkg` |
| 7 | `07_render.py` | QGIS render in feet and in metres. The one source of the style; no label comes closer than 2.5 mm to the map edge; also saves each layer style to `styles/` (feet) and `styles/metric/`. | `out/day06_{modern,sheet}[_m].png`, `out/day06_sheet[_m]_zoom.png` (400 dpi), `out/day06_scan.png`, `styles/` |
| 7b | `07b_scan_colour.py` | The scan re-inked in the repeat's paper and inks (optical density, one 3 x 3 matrix). | `out/day06_scan_matched.png`, `derived/scan_colour.json` |
| 8 | `08_site.py` | Site images (WebP) and the numbers the page quotes. | `site/img/day06/`, `site/data/day06.json` |
| 8b | `08b_scan_tiles.py` | The 600 ppi master scan, margins included, cut into a Deep Zoom pyramid of WebP tiles for the page's scan viewer (OpenSeadragon 5.0.1, loaded from cdnjs). Run again only if the scan changes. | `site/img/day06/scan/` |

Shared modules: `sheet.py` (extent, folders, the ink palette), `georef.py` (pixel to UTM model), `ink.py` (paper, optical density and the four ink plates of the scan; used by 03 and 07b).

Checks: `python3 day-06/tests/test_day06.py` (georeferencing error and warp, area order and range, every number on the page against the data, the summit heights quoted, the reviewed not-ice points, and the colour-match fit).

## Results (2026-11-10 build, from the TIFF master)

- Georeferencing: 157 m RMS on held-out stations (corners only: 188 m). Affine fits did no better. The warp used until 11-10 (a thin-plate spline through the four corners) was within 1.2 m of the model everywhere, so the switch moved nothing.
- Ice inside the frame: 79.0 km² in 1913 (method range 67.5 to 87.9), 53.6 km² in 1985, 46.5 km² in 2021; 89 % of the 1985 ice lies inside the 1913 line. From the JPEG the 1913 reading was 79.7 km² (65.7 to 91.2).
- Every 1913 patch with no 1985 ice was checked on the master scan: five are drawn with blue contours (ice since gone), two were blue creeks (removed, `data/not_ice.json`). Of the 1985 ice outside the 1913 line, some is the georeferencing offset, one small glacier in dense brown hachures is missed by the central setting, and on the north face of Popes Peak and beside The Preacher the sheet draws rock where 1985 had ice.

- Summits (11-10): 57 OSM summits and 7 official names placed from the model; 17 flagged for a look (printed by `peaks.py`). Mount Balfour 10,735 ft (sheet 10,741), Trolltinder Mountain 9,570 (sheet 9,570).
- Using OSM summit positions as georeferencing check points makes the held-out error worse (209 m against 157 m): the printed 1913 stations sit on the model's high points.

## Limits

- The 1913 line is a colour reading of a printed map and carries the sheet's position error. It misses some high icefield edges and small ice inside dense brown rock drawing, and catches blue creeks on brown slopes unless they are listed in `data/not_ice.json`. Its settings are in the script header.
- The graticule is modern (NAD83). The frame is the sheet's own (its corner coordinates read as NAD27, plus the mean shift), so it sits about 120 m west and 115 m south of the modern lines of the same value; the 116°15′ meridian of the east edge falls just outside it. The sheet's own grid, the Dominion Land Survey townships and ranges, is not drawn.
- Datums: the sheet's heights are above mean sea level as levelled before 1928; MRDEM-30 is on CGVD2013, 0.55 to 0.57 m above CGVD28 on this sheet (PROJ, NRCan HT2 grid). Small next to the 100 ft contour interval and the model's summit error. The corner coordinates are taken as NAD27, which the sheet predates; any offset between the two is inside the mean shift.
- Modern lakes are masked out of the 1913 ice (the sheet water-lines lakes in blue), except lakes within 300 m of the 1985 ice, which are taken to have formed since (Takakkaw Lake).
- MRDEM-30 flattens sharp summits by tens of metres, so the map prints summit heights from OSM only, and only where they agree with the model (25 m above to 150 m below it). Lake heights are the model's median over the lake.
- CanVec 50K spot heights were checked as a summit source first: 3 points in this sheet's window, none at Waterton.
- The colour match is one linear map for the whole sheet. Brown on the scan stays lighter than on the repeat, because the scan's brown lines are finer; faint ink below 0.05 OD fades into the paper. The matched scan reads more saturated than the original, so the page shows the scan as scanned by default.

## History

A first attempt built with Gemini agents in Antigravity on 11-09 placed many features at pixel positions typed into the code rather than measured from the scan or taken from data, and quoted checks that had not been run. It is archived outside the repository, with a written assessment.
