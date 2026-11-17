# Day 7 (10 minute map): Ten Minutes in April, 1962

*A geography of Blowin' in the Wind.* Bob Dylan said he wrote "Blowin' in the Wind" in ten minutes, in a Greenwich Village café in April 1962. This map asks the song's questions of the country he came from, Duluth to Hibbing, Minnesota. The base is the four USGS 1:250,000 sheets of 1958, redrawn from their own inks and laid out the way those sheets were. Each question is answered with a public dataset:
- the roads out: the 1958 roads, and the miles to the next town where a road leaves the map;
- the seas: the three continental drainages that meet near Hibbing;
- the mountain: the Mesabi iron pits;
- the dove: April records of mourning doves;
- the sand: Minnesota Point;
- the wind: ERA5, April 1962.

"Ten minutes" is the theme, not the time the map took.

This README is also a design brief: it gives the page, the inks and the method in enough detail to draw the map again in another tool.

## The map

| The song asks | Layer | Source | Drawn as |
|---|---|---|---|
| How many roads | the 1958 road, rail, town and name inks; miles to the next town in the collar | USGS 1958 sheets; OSM roads beyond the map | charcoal, as printed; "COOK 9 MI." in the collar, with an arrow on the road at the neatline |
| How many seas | the continental divides and the point where they meet | USGS Watershed Boundary Dataset (HUC8 dissolved to HUC2) | dashed charcoal line; a ringed point; "to Hudson Bay", "to the Gulf of Mexico", "to the Atlantic" in hand |
| Washed to the sea | woods, water, contours, relief | 1958 green, blue and brown inks; AWS Terrain Tiles; NOAA NCEI Lake Superior bathymetry | watercolour washes for woods and water; suede contours; faint grey hillshade |
| How many years can a mountain exist | the iron pits of the Mesabi | OSM quarries, filtered to the Mesabi (2026) | a light rust fill (16 %), a rust outline and rust dots (55 %) over the 1958 print, where that year's pits show as tight brown contours; set a little above the lakes, not above everything |
| The white dove, the sand | mourning dove records, April, 1981 to 2026; Minnesota Point | GBIF (CC0 and CC BY records) | small white dots with a charcoal edge |
| The answer is blowin' in the wind | the wind of April 1962 at Duluth, at 10 m and at 700 hPa (about 10,000 ft) | ERA5 (Copernicus) | double rose on the lake: 10 m filled, 700 hPa outline, rings at 10 and 20 % of hours |
| | the waves of 10 to 16 April 1962, the week of Dylan's first Gerde's performance of the song | estimated from the ERA5 wind and the fetch across the lake | short crests across the direction of travel, longer where higher |
| | Duluth (born 1941), Hibbing (grew up), the 1920 lynching of Elias Clayton, Elmer Jackson and Isaac McGhie | OSM place names | handwritten notes with leaders |

The story under the map states that this is Anishinaabe (Ojibwe) land, ceded by the treaties of 1842, 1854 and 1855. Which treaty applies to each town was checked against the USFS Royce cession polygons (`06_cessions_check.py`).

## Design brief

**Page.** Tabloid portrait, 279.4 x 431.8 mm (11 x 17 in). Outputs:
- `out/day07_B.pdf`, without grain, for print;
- `out/day07_B.png`, at 300 dpi with grain, kept local.

Top to bottom:
- the title block, from 12 mm;
- the map, 240 mm wide and centred, its top edge 57 mm from the top of the page;
- the collar, 14.5 mm wide all round between the neatline and a heavy outer border;
- the lower collar, in two columns, each read top to bottom (no imprint line).

**Frame and projection.**
- The frame is 93.30 to 91.30 W, 46.40 to 47.72 N, drawn as the rectangle that box makes in NAD83 / UTM zone 15N (EPSG:26915): 153.7 x 148.0 km, 1:641,000 on the page.
- Every source is fetched 0.08 degrees wider, so the projected rectangle has no empty corners.
- The UTM grid itself is not drawn: the map carries latitude and longitude, and imperial units only.

**Palette.**

| Ink | Hex | Used for |
|---|---|---|
| paper | `#EFECE6` | page, halos under text |
| charcoal | `#22201E` | 1958 black and red inks, divides, notes, frame, collar |
| graphite | `#5A554C` | survey numbers, wave crests |
| suede | `#6E5340` | 1958 brown ink (contours), subtitle, the 10 m rose |
| woods | `#93A86E` | wash: the 1958 woodland tint |
| water | `#8FB0BC` | wash: the 1958 water tint and Lake Superior |
| stream | `#3F6577` | 1958 blue line ink: streams, shorelines, marsh tufts |
| rust | `#8B4513` | the pits, and this map on the location diagram |
| dove | `#FAF8F5` | dove records |

**The base: multiply blending.** The base is one RGB image at print resolution: paper, multiplied by each layer in turn. Each layer is a 0 to 1 opacity raster that is scaled to a maximum and coloured with one ink. In order:

| Layer | Ink | Max opacity | Wash |
|---|---|---|---|
| hillshade (NW 315°, altitude 40°, vertical x2) | charcoal | 0.20 | |
| wetland (NWI emergent and forested/shrub, 10 acres and more; D330) | water | 0.20 | yes |
| water (Lake Superior from NCEI joined with OSM water areas, which add the St. Louis estuary and some small pieces; plus the 1958 water plate for the inland lakes; plate density 0.6 = full) | water | 0.55 | yes |
| 1958 green (woodland) | woods | 0.28 | yes |
| 1958 urban fill | charcoal | 0.16 | |
| 1958 brown | suede | 0.70 | |
| 1958 blue | stream | 0.75 | |
| 1958 black | charcoal | 0.95 | |
| 1958 red | charcoal | 0.80 | |

The watercolour wash has three parts:
1. The opacity is multiplied by a smooth noise field, varying by ±20 % at about 3 mm on the page.
2. Pigment pools at the inner edges: 0.9 x the amount by which a cell exceeds the mean of its 9 x 9 neighbours.
3. The edge is softened by a 3 x 3 mean.

So the 1958 sheet is redrawn in its own hues, muted, with one accent added for the pits.

**Vector layers, bottom to top.**
1. Seas.
2. Pits.
3. Wave crests.
4. Doves.
5. Places.
6. The rose.
7. Neatline and outer border.
8. Handwritten notes.
9. Collar.
10. Title.
11. Lower collar.

**Type.**
- Title: Special Elite, 34 pt.
- Subtitle: Caveat, 17 pt, suede.
- Handwritten notes: Caveat, 9.8 to 12.4 pt, with a 0.3 mm paper halo. A note's leader leaves from the middle of the side of the text block nearest its feature, so it never crosses the writing.
- Collar and lower collar: Jost, a geometric grotesque close to the sheets' lettering; road notes in Jost Italic.
- Story: EB Garamond, 8.6 pt.

The fonts and their licences are in `fonts/`: Special Elite is Apache 2.0; Caveat, EB Garamond and Jost are OFL.

**Collar, in the manner of the 1958 sheets** (checked on the Duluth sheet's own collar).
- Tier 1, starting 2.8 mm out from the neatline:
  - latitude and longitude every 15 minutes, at black ticks 2.2 mm long that follow the meridian or parallel where it meets the neatline;
  - whole degrees in full (`93°00′`), the rest as minutes only (`45′`);
  - township numbers on the sides and range numbers on the top and bottom (`T. 52 N.`, `R. 21 W.`). Each is set at the middle of its row or column, between short graphite ticks where one row ends and the next begins.
- Tier 2, 6.6 mm out on the top and bottom and 11.5 mm out on the sides, clear of the widest township label, so the turned road notes keep their own outer column as on the sheets (up the west edge, down the east):
  - where a numbered road leaves the map, the town it leads to and the miles (`COOK 9 MI.`), with a 2 mm arrow on the road at the neatline;
  - on the sides these notes run along the edge, as on the sheets.
- Placement, one edge and tier at a time:
  - graticule labels always print;
  - survey numbers print where they fit;
  - road notes, nearest town first, slide along the edge in 2 mm steps (up to 40 mm) until they clear the others.

**Lower collar.** Two columns, each read top to bottom (GW's markup of 11-16): the old legend centred above the new; the descriptions at the foot, side by side.

Left column:
1. **The 1958 legend**: the Duluth sheet's own legend, cut from the scan, separated into the same ink plates as the map and printed at 66 % of its size in the map's inks, centred over the next item.
2. **Added in 2026**: a legend of every mark this map adds.
3. **Story, the song**: the song and its weather.
4. **Production note**: who drew the map, from what; datum. Small, in grey, its last line level with the data credits.

Right column:
1. **Scale block**:
   - "Scale 1:641,000";
   - statute-mile and nautical-mile bars in the sheets' manner: two thin rules with every other division filled, and five single units left of zero;
   - "CONTOUR INTERVAL 50 FEET WITH SUPPLEMENTARY CONTOURS AT 25 FOOT INTERVALS" (true of the 1958 base);
   - "TRANSVERSE MERCATOR PROJECTION", with the zone and datum.
2. **Declination**:
   - The April 1962 magnetic declination at the centre of the map's west and east edges.
   - It is interpolated linearly from the 1955 values and annual changes printed on the four sheets (`DECLINATION_1955` in `config.R`).
   - A diagram shows true north (a star) and magnetic north (MN) at the mean declination. It stands in for a north arrow.
3. **Location diagram**:
   - the 1:250,000 sheet grid (2° x 1°) from 98 to 88 W and 44 to 49 N;
   - the four sheets named with their numbers (NL 15-2 Hibbing, 15-3 Two Harbors, 15-5 Duluth, 15-6 Ashland);
   - state outlines, Lake Superior, and this map in rust.
4. **Sectionized township**: the 36 sections numbered as the survey numbers them.
5. **Story, the land**: the treaties and the roads of 1958.
6. **Data credits**: small, in grey.

**Grain.** On the PNG only: one charcoal noise raster at 150 dpi over the whole page, alpha |N(0, 0.045)| capped at 0.12, seed 1963.

## Data

All sources are public; nothing needs an API key except the Copernicus Climate Data Store for step 05. Raw files go to `$MC26_DAY07_DATA/raw/` as fetched and are never edited; every step is logged in the data change log.

| Source | Endpoint | Licence | File |
|---|---|---|---|
| USGS Historical Topographic Map Collection, 1:250,000, 1958: Duluth, Ashland, Hibbing, Two Harbors | TNM products API | public domain | `raw/htmc/*.tif` |
| AWS Terrain Tiles, zoom 10 | via `elevatr` | see the Terrain Tiles attribution (public sources) | `raw/dem_terrain_z10.tif` |
| NOAA NCEI Great Lakes Bathymetry, Lake Superior 3″ | ngdc.noaa.gov | public domain | `raw/superior_lld/superior_lld.tif` |
| OpenStreetMap, Geofabrik Minnesota and Wisconsin extracts of 2026-11-15 | download.geofabrik.de | ODbL | `raw/*-261115.osm.pbf`, `raw/osm_*.gpkg` |
| USGS Watershed Boundary Dataset, HUC8 | hydro.nationalmap.gov ArcGIS REST | public domain | `raw/wbd_huc8.geojson` |
| USFWS National Wetlands Inventory: emergent and forested/shrub wetlands of 10 acres or more | fwspublicservices.wim.usgs.gov Wetlands MapServer, layer 0 (500 a request, by object id; outlines generalised to about 20 m) | public domain | `raw/nwi_wetlands.gpkg` |
| BLM PLSS CadNSDI: townships (layer 1) and state boundaries (layer 0) | gis.blm.gov ArcGIS REST | public domain | `raw/plss_townships.geojson`, `raw/states.geojson` |
| GBIF occurrence search, *Zenaida macroura*, April, CC0 and CC BY 4.0; cite as GBIF.org (16 November 2026), derived dataset https://doi.org/10.15468/dd.8w6ahv | api.gbif.org | CC0 / CC BY 4.0 | `raw/gbif_doves.csv`; the 2,051 used are in the repo, `data/gbif_doves_used.csv` |
| ERA5 hourly, April 1962, 10 m wind (0.25° grid) | Open-Meteo archive API, `models=era5` | CC BY 4.0 | `raw/wind_hourly.csv` |
| ERA5 hourly, April 1962, 10 m and 700 hPa u and v | Copernicus CDS (key needed) | Copernicus licence | `raw/era5_1962_04_*.nc` |
| USFS Royce cessions; Census TIGERweb reservations | USFS EDW, TIGERweb REST | public domain | `raw/cessions/` |

## Method

1. **`01_fetch.R`** fetches the sources:
   - Terrain Tiles and the NCEI grid.
   - The Geofabrik extracts, clipped to the box in one GDAL pass. The public Overpass server refused scripted queries.
   - From the clip: quarries and four named places. (Roads, rail and rivers come from the 1958 sheets; OSM roads beyond the frame feed the road notes, step 08.)
   - WBD HUC8, GBIF doves and the Open-Meteo hourly wind.
   - The PLSS townships and the state outlines.
   - NWI emergent and forested/shrub wetlands of 10 acres or more, 500 a request by object id.
   - Numbered roads and towns 1 degree round the frame.

   A file already on disk is not fetched again.
2. **`02_prepare.R`** builds the layers, all in UTM 15N:
   - A 100 m grid: land from Terrain Tiles, and the lake floor as lake level (183.2 m) plus NCEI where NCEI is below 0.
   - Hillshade.
   - Water: Lake Superior from NCEI, joined with OSM water areas of 0.05 km² and more (the St. Louis estuary and 57 small pieces in the frame). The inland lakes are washed from the 1958 water plate in step 03 (D330).
   - Wetlands: the NWI polygons in the frame (a draft wash, D330).
   - The seas: HUC8 dissolved to HUC2 (04 Great Lakes, 07 Upper Mississippi, 09 Souris-Red-Rainy), with the divides as their shared edges. The meeting point is the HUC2 04 vertex nearest both others: 94 m miss, 5.8 km from Hibbing.
   - Mesabi pits only: OSM quarries north of 47.25° N, of 0.4 km² or more, without "gravel" in the name.
   - The whole lake at about 2 km, for the location diagram.
   - The 10 m wind rose at the ERA5 cell nearest Duluth.
   - Every number the map quotes, in `summary.csv`.
3. **`05_era5_cds.py`** fetches ERA5 10 m and 700 hPa u and v for April 1962 from the CDS. It writes the double rose: 16 sectors, share of the 720 hours by the direction the wind came from, at the cell 46.75 N, 92.00 W.
4. **`06_cessions_check.py`** places Hibbing, Duluth, Superior and Cloquet in the Royce cession polygons:
   - Hibbing in Royce 357 (1855); Duluth and Cloquet in 332 (1854); Superior in 261 (1842).
   - The Fond du Lac Reservation lies wholly inside the frame.
   - Royce 242 (1837), 455 (1855 and 1864) and 482 (1866) touch the frame's edges only, at 0.1 % of its area or less: slivers within the error of the 1899 maps.
5. **`07_waves.R`** estimates the waves of 10 to 16 April 1962:
   - Fetch: rays in 16 directions on a 1 km water mask of the whole lake (NCEI).
   - Height and period: JONSWAP deep-water fetch-limited growth, capped at a fully developed sea, from the nearest ERA5 cell's hourly wind.
   - Week summary: the mean height, and the mean direction weighted by wave energy.
6. **`10_htmc_fetch.py` to `14_legend.py`** turn the 1958 sheets into ink plates:
   - Fetch: one 1958 item exists per sheet.
   - Cut each sheet 75 m inside its graticule; the printed neatline sits within 1 px of it at the median.
   - NAD27 to NAD83 by EPSG:1174 (a geocentric shift of -9, 161, 179 m), as an explicit PROJ pipeline. Without the NADCON grids installed, PROJ's default mixes a Canadian grid shift with none.
   - Warp to 20 m (bilinear) and mosaic.
   - Line inks: optical density against a local background, classed by colour.
   - Tints (woodland green, water, urban orange): fitted per sheet against that sheet's own colours, so the four printings match.
   - `11b` measures the 1958 water edges against today's: medians of 40 to 57 m.
   - `13` screens for 1958 pits. No rule separates pits from dumps on these sheets, so it writes a check image only.
   - `14` cuts the Duluth sheet's legend and separates it with the same rule.
7. **`08_roads_out.R`** builds the road notes:
   - For each US, MN or WI route leaving the frame: the shortest path along that route's own ways, outside the frame, to the first town beyond the edge.
   - The town is the nearest city or town within 80 km, else the nearest village, and must lie within 1.5 km of the road. Notes over 50 miles are left out.
   - Interstates are left out: they were not built here in 1958.
8. **`03_map.R`** draws the page, variant A or B (B adds the memorial note). It also writes `out/day07_B_layout.json`, the pixel positions that `04_site_images.R` crops the page, detail and calendar images from.
9. **`04b_tiles.py`** rasterises the PDF at 762 dpi with `pdftoppm` (so the collar text is as sharp as the map) and cuts a Deep Zoom WebP pyramid for the site's zoom viewer (`site/img/day07/tiles/`, 8,382 x 12,954 px, 620 tiles, 11 MB). The viewer (`site/js/day07.js`, OpenSeadragon 5.0.1) stops at three times its opening view.

## Reproduce

The map raster is built at 762 dpi (21.2 m a pixel, the scans' own resolution), so the 1958 lettering keeps its shape in the PDF. Step 03 then needs about 15 GB of memory and 2 minutes for each variant; the PNG is written at 300 dpi.

```sh
export MC26_DAY07_DATA=/path/to/a/working/folder      # outside the repository
export MC26_NCEI_SUPERIOR=/path/to/superior_lld.tif    # optional; else step 01 downloads it
Rscript day-07/install_packages.R                      # optional, opt-in installer
PY_CDS=... PY_NC=... PY_GDAL=... bash day-07/run_day07.sh
```

**The three Pythons.** Each can be the same interpreter if it has every package.

| Variable | Used by | Needs |
|---|---|---|
| `PY_CDS` | fetch in step 05 | `cdsapi`, and a CDS key in `~/.cdsapirc` |
| `PY_NC` | the rose in step 05, and step 06 | `xarray`, `netCDF4` and `shapely` |
| `PY_GDAL` | steps 04b, 10 to 14 | GDAL Python bindings, `numpy`, `scipy` and Pillow |

Every step is safe to rerun:
- Fetched files are kept.
- Steps 02 and 07 refuse to overwrite their outputs; delete them to rebuild.

The working folder grows to about 1.2 GB: about 0.7 GB of raw files, most of it the two state extracts, and 0.5 GB for the 1958 plates. The per-sheet warps in `derived/htmc/_work/` (0.2 GB) can be deleted. Steps 03 and 04b take about 2 minutes and 1 minute.

**Built with:**
- R 4.6.2: sf 1.1.1 (GDAL 3.12.2, GEOS 3.14.1, PROJ 9.7.1), terra 1.9.34, ggplot2 4.0.3, dplyr 1.2.1, purrr 1.2.2, tidyr, igraph, showtext 0.9.8, sysfonts 0.8.9, systemfonts, magick 2.9.1, elevatr 0.99.1, httr2 1.2.3, jsonlite 2.0.0.
- Python, steps 10 to 14: 3.14.4 with GDAL 3.12.2, numpy 2.3.5 and scipy 1.16.3.
- Python, the rose and step 06: 3.14.4 with xarray 2026.7.0, netCDF4 1.7.4 and shapely 2.1.2.
- Python, the CDS fetch: 3.13.13 with cdsapi.
- Step 04b: poppler-utils (`pdftoppm`) and Pillow.

## Results (2026-11-16 build)

- **Frame:** 153.7 x 148.0 km, 1:641,000 on the page. Land 179 to 630 m. Lake Superior to 287 m deep. Water 1,954 km² in frame.
- **Wind, April 1962, at the cell 46.75 N, 92.00 W:**
  - At 10 m: mean speed 4.4 m/s, but a mean vector of only 1.1 m/s, from 347°. The surface wind came from every side.
  - At 700 hPa: mean speed 12.3 m/s, mean vector 7.6 m/s from 296°. Aloft, it held from the west and north-west.
- **Waves, 10 to 16 April 1962 (estimate):** mean significant height 0.21 m at the 80 lake points (0.06 to 0.30 m), the week's highest 0.84 m, mean direction of travel 153°.
- **Magnetic declination, April 1962** (from the sheets' 1955 values): 4°51′ E at the centre of the west edge, 2°53′ E at the east edge.
- **Doves:** 2,051 April records in the frame, 1981 to 2026 (2,096 fetched in the padded box).
- **Pits:** 17 Mesabi pits from 107 quarries.
- **Road notes:** 19, from Silver Bay 1 mi to Mora 37 mi.
- **Survey grid:** 319 townships (T. 44 N. to T. 61 N.).

## Limits

- **The wind is a reanalysis.** ERA5 in 1962 had no satellite input, so the wind is a model fit to sparse surface and upper-air observations on a 0.25° grid. It shows the month's flow, not a day in Greenwich Village.
- **The waves are an estimate, not a record.** ERA5 waves have no Lake Superior cells, and the buoys came later. The estimate ignores how long each wind blew (so it is an upper bound for short blows) and any ice.
- **The doves are modern.** Most records come from eBird after 2000; they show where people saw doves, not where doves were in 1962.
- **The pits are today's**, as mapped in OSM and filtered by size and place. A small iron pit or an unmapped one is missed. The 1958 pits are left as the sheets drew them.
- **The wetland wash is modern.** The sheets show marsh only as small tufts, which no rule here could turn into areas. The wash is the National Wetlands Inventory, which matches the sheets' tuft fields roughly (tuft density 1.4 per km² where NWI covers under 5 % of a 3 km cell, 4.9 where it covers over 60 %), with less than the sheets in the north-west. The tufts still print as the sheets printed them.
- **The road notes use today's roads.** A 1958 alignment may differ by a mile or two, and some routes have been renumbered (US 61 north of Duluth is MN 61 since 1991).
- **The declination is interpolated** linearly between the values printed for the sheets' edge centres, and carried from 1955 to 1962 by their printed annual change. It is not a geomagnetic model.
- **The 1958 inks are colour readings of scans.** Some ink lands in the wrong plate:
  - red streets break up the Duluth urban fill;
  - red fringes show in the brown;
  - blue lettering on water falls partly into black;
  - marsh tufts on woodland print charcoal rather than slate.
- **The 1958 water edges** sit a median 40 to 57 m from today's (90th percentile up to 220 m). That is mostly the sheets' own generalisation at 1:250,000; no shift was applied.
- **The wave fetch uses a 1 km lake mask,** too coarse to hold Minnesota Point; fetch across the spit is open water.
- **The OSM extracts are dated (2026-11-15).** Geofabrik keeps dated files for a limited time; a later rerun may need the `-latest` extract and get slightly different roads.
- **The four sheets are split on the NAD83 graticule,** about 40 m from their NAD27 neatlines; a strip that narrow takes the neighbouring sheet's ink references.
- **The three-waters point** is where the WBD polygons meet at their mapping scale, not a surveyed spot.
- **The NCEI grid stops at 92.20° W.** West of it, the St. Louis River estuary is OSM water without depth.

## How it was made

GW's brief started from a design conversation with Gemini (Google). Claude Code (Anthropic) then:
- reviewed that design and checked its facts. It corrected US 61 to MN 61, the scale, and a raptor site the design had placed doves at.
- wrote the specification;
- ran an objection review by two Gemini models;
- built the pipeline, with two Claude subagents for the 1958 sheets and the ERA5 and treaty checks. Their outputs were checked against the files.

GW made the design calls, including:
- the 1958 base and its collar;
- the Tabloid page;
- the watercolour washes;
- the double rose and the wave estimate;
- the frame;
- naming the three men of the 1920 lynching and their memorial;
- the title.

Code MIT; map CC BY 4.0 (see the repository licences).
