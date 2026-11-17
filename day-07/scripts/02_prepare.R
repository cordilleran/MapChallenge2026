#!/usr/bin/env Rscript
# Day 7 step 02: from the raw sources to the layers the map draws, all in UTM 15N.
# In : $MC26_DAY07_DATA/raw (step 01)
# Out: $MC26_DAY07_DATA/derived/day07.gpkg (vector layers), relief.tif (hillshade),
#      wind_rose.csv (the 10 m rose, used if step 05's double rose is missing),
#      summary.csv (every number the map or README quotes)
#
# Layout: main() first, the helpers follow; main() is called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({
  library(dplyr)
  library(purrr)
  library(sf)
  library(terra)
})

GPKG_FINAL <- file.path(DERIVED_DIR, "day07.gpkg")
GPKG <- paste0(GPKG_FINAL, ".partial")   # renamed to GPKG_FINAL only when every layer is written
CELL_M <- 100            # relief grid, about the Terrain Tiles z10 cell here
MIN_WATER_KM2 <- 0.05    # OSM water polygons smaller than this are left out
TRIPLE_TOL_M <- 250      # the three drainages must meet within this distance
MESABI_MIN_LAT <- 47.25  # pits: only quarries north of this (the Mesabi Range) ...
MESABI_MIN_KM2 <- 0.4    # ... and larger than this; the smallest iron-tagged pit is 0.6 km²

main <- function() {
  if (file.exists(GPKG_FINAL)) stop("Delete ", GPKG_FINAL, " to rebuild it (rerun-safe).", call. = FALSE)
  unlink(GPKG)   # a partial file from a failed run
  frame <- frame_utm()
  st_write(st_sf(id = 1, geometry = frame), GPKG, "frame", driver = "GPKG", quiet = TRUE)

  elev <- build_elevation(frame)
  relief <- shade_relief(elev)
  writeRaster(relief, file.path(DERIVED_DIR, "relief.tif"), overwrite = TRUE)

  water <- build_water(elev$lake_depth, frame)
  write_layer(water, "water")
  lake_whole() |> write_layer("lake_whole")
  read_wetlands(frame) |> write_layer("wetlands")

  seas <- build_seas(frame)
  write_layer(seas$regions, "drainage")
  write_layer(seas$divides, "divides")
  write_layer(seas$triple, "three_waters")

  osm_layers(frame) |> iwalk(write_layer)
  doves <- read_doves(frame)
  write_layer(doves, "doves")

  wind <- read_wind()
  places <- st_read(file.path(RAW_DIR, "osm_places.gpkg"), quiet = TRUE) |> st_transform(DISPLAY_CRS)
  write_layer(places, "places")
  rose <- wind_rose(wind, places)
  utils::write.csv(rose$bins, file.path(DERIVED_DIR, "wind_rose.csv"), row.names = FALSE)

  summarise_numbers(frame, elev, water, seas, doves, wind, rose, places) |>
    utils::write.csv(file.path(DERIVED_DIR, "summary.csv"), row.names = FALSE)
  stopifnot(file.rename(GPKG, GPKG_FINAL))
  message("Step 02 done: ", GPKG_FINAL)
}

write_layer <- function(x, layer) st_write(x, GPKG, layer, driver = "GPKG", quiet = TRUE, append = FALSE)

# The frame: Argon's lon/lat box, densified so its curved sides survive projection, then
# the projected bounding rectangle. The fetch box is padded, so the corners have data.
frame_utm <- function() {
  st_bbox(FRAME_LL, crs = 4326) |>
    st_as_sfc() |>
    st_segmentize(units::set_units(1000, "m")) |>
    st_transform(DISPLAY_CRS) |>
    st_bbox() |>
    st_as_sfc()
}

# Land from Terrain Tiles; the lake floor from NCEI (metres relative to lake level),
# both resampled onto one 100 m UTM grid.
build_elevation <- function(frame) {
  template <- rast(ext(vect(frame)), resolution = CELL_M, crs = paste0("EPSG:", DISPLAY_CRS))
  land <- rast(file.path(RAW_DIR, "dem_terrain_z10.tif")) |> project(template, method = "bilinear")
  ncei <- rast(NCEI_TIF)
  ncei <- crop(ncei, ext(project(ext(template), crs(template), crs(ncei))) * 1.05) |>
    project(template, method = "bilinear")
  lake_depth <- ifel(ncei < 0, ncei, NA)          # negative metres below lake level
  surface <- ifel(is.na(lake_depth), land, LAKE_LEVEL_M + lake_depth)
  list(land = land, lake_depth = lake_depth, surface = surface)
}

# NW light, one direction, vertical exaggeration 2 to lift the gentle range
shade_relief <- function(elev) {
  z <- elev$surface * 2
  slope <- terrain(z, "slope", unit = "radians")
  aspect <- terrain(z, "aspect", unit = "radians")
  shade(slope, aspect, angle = 40, direction = 315, normalize = TRUE)
}

# One water layer: the NCEI lake (below lake level) and OSM water areas, so St. Louis Bay
# is not cut at 92.20 W where NCEI ends (D310).
build_water <- function(lake_depth, frame) {
  lake <- as.polygons(!is.na(lake_depth) & lake_depth < 0, dissolve = TRUE) |>
    st_as_sf() |> filter(.data[[names(lake_depth)]] == 1) |> select()
  osm <- st_read(file.path(RAW_DIR, "osm_clip.gpkg"), quiet = TRUE, query =
    "SELECT osm_id, osm_way_id, name, natural, geom FROM multipolygons
     WHERE natural = 'water' OR other_tags LIKE '%\"water\"=>%'") |>
    st_transform(DISPLAY_CRS) |> st_make_valid()
  osm <- osm[as.numeric(st_area(osm)) >= MIN_WATER_KM2 * 1e6, ]
  bind_rows(lake |> mutate(source = "NCEI"), osm |> transmute(source = "OSM")) |>
    st_union() |> st_make_valid() |> st_intersection(frame) |>
    st_cast("MULTIPOLYGON") |> st_sf(geometry = _)
}

# Three seas: HUC8 basins dissolved to HUC2 regions, the divides between them, and the
# point where all three meet (the Hill of Three Waters), computed not typed.
build_seas <- function(frame) {
  regions <- st_read(file.path(RAW_DIR, "wbd_huc8.geojson"), quiet = TRUE) |>
    st_transform(DISPLAY_CRS) |> st_make_valid() |>
    mutate(huc2 = substr(huc8, 1, 2)) |>
    group_by(huc2) |> summarise(.groups = "drop") |>
    st_make_valid() |>
    mutate(sea = SEA_NAMES[huc2])
  stopifnot(setequal(regions$huc2, names(SEA_NAMES)))
  pairs <- list(c("04", "07"), c("04", "09"), c("07", "09"))
  divides <- pairs |> map(\(p) {
    a <- st_boundary(regions[regions$huc2 == p[1], ])
    b <- regions[regions$huc2 == p[2], ] |> st_buffer(TRIPLE_TOL_M / 5)
    st_intersection(st_geometry(a), st_geometry(b)) |>
      lines_only() |> st_union() |> st_cast("MULTILINESTRING") |> st_line_merge() |>
      st_sf(geometry = _) |> mutate(pair = paste(p, collapse = "-"))
  }) |> bind_rows()
  triple <- triple_point(regions)
  list(regions = st_intersection(regions, frame), divides = st_intersection(divides, frame),
       triple = triple)
}

# Keep the line parts of an intersection (it can also return touching points)
lines_only <- function(x) {
  if (all(st_geometry_type(x) %in% c("LINESTRING", "MULTILINESTRING"))) return(x)
  st_collection_extract(x, "LINESTRING")
}

SEA_NAMES <- c("04" = "to the Atlantic, by the Great Lakes and the St. Lawrence",
               "07" = "to the Gulf of Mexico, by the Mississippi",
               "09" = "to Hudson Bay, by the Rainy and the Nelson")

# The vertex of the 04 boundary closest to both other regions; it must be within
# TRIPLE_TOL_M of each.
triple_point <- function(regions) {
  geom <- \(h) st_geometry(regions[regions$huc2 == h, ])
  verts <- st_boundary(geom("04")) |> st_cast("POINT")
  d07 <- as.numeric(st_distance(verts, geom("07")))
  d09 <- as.numeric(st_distance(verts, geom("09")))
  best <- which.min(pmax(d07, d09))
  stopifnot(max(d07[best], d09[best]) <= TRIPLE_TOL_M)
  st_sf(name = "Hill of Three Waters", miss_m = max(d07[best], d09[best]), geometry = verts[best])
}

# Today's pits from OSM (the 1958 sheets carry the roads, rail and rivers since v2)
osm_layers <- function(frame) {
  pits <- st_read(file.path(RAW_DIR, "osm_pits.gpkg"), quiet = TRUE) |>
    st_transform(DISPLAY_CRS) |> st_make_valid() |> st_intersection(frame)
  list(pits = pits |> select(osm_id, osm_way_id, name) |> mesabi_only())
}

# NWI wetlands (step 01), in the frame, in UTM; a draft wash for GW to judge (D327)
read_wetlands <- function(frame) {
  path <- file.path(RAW_DIR, "nwi_wetlands.gpkg")
  if (!file.exists(path)) return(st_sf(geometry = st_sfc(crs = DISPLAY_CRS)))
  st_read(path, quiet = TRUE) |>
    st_transform(DISPLAY_CRS) |>
    st_make_valid() |>
    st_filter(frame) |>
    select(WETLAND_TYPE, ACRES)
}

# The whole of Lake Superior, coarse (about 2 km), in lon/lat: the location diagram's lake
lake_whole <- function() {
  ncei <- rast(NCEI_TIF)
  wet <- aggregate(ncei, fact = round(0.02 / res(ncei)[1]), fun = "mean", na.rm = TRUE) < 0
  as.polygons(classify(wet, cbind(0, NA))) |>
    st_as_sf() |>
    st_union() |>
    st_simplify(dTolerance = 1000) |>   # metres: sf measures on the sphere in lon/lat
    st_sf(geometry = _) |>
    st_set_crs(4269) |>          # NCEI is NAD83 lon/lat
    st_transform(4326)
}

# The iron pits of the Mesabi, not every quarry: large quarries north of MESABI_MIN_LAT, without
# "gravel" in the name. This leaves out the gravel pits round Duluth and on the Wisconsin shore.
mesabi_only <- function(pits) {
  lat <- st_coordinates(st_transform(st_centroid(st_geometry(pits)), 4326))[, 2]
  km2 <- as.numeric(st_area(pits)) / 1e6
  keep <- lat >= MESABI_MIN_LAT & km2 >= MESABI_MIN_KM2 & !grepl("gravel", pits$name, ignore.case = TRUE)
  message("Pits: ", sum(keep), " of ", nrow(pits), " quarries kept as Mesabi pits")
  pits[keep, ]
}

read_doves <- function(frame) {
  utils::read.csv(file.path(RAW_DIR, "gbif_doves.csv")) |>
    filter(is.na(coordinateUncertaintyInMeters) |
           coordinateUncertaintyInMeters <= DOVE_MAX_UNCERTAINTY_M) |>
    st_as_sf(coords = c("decimalLongitude", "decimalLatitude"), crs = 4326) |>
    st_transform(DISPLAY_CRS) |>
    st_filter(frame)
}

# Hourly wind as vectors toward which it blows (u east, v north), at the asked grid points
read_wind <- function() {
  utils::read.csv(file.path(RAW_DIR, "wind_hourly.csv")) |>
    mutate(
      u = -speed_ms * sin(from_deg * pi / 180),
      v = -speed_ms * cos(from_deg * pi / 180)
    )
}

# The month at the cell nearest Duluth: share of hours by 16 directions (from), mean speed
wind_rose <- function(wind, places) {
  duluth <- st_transform(places[places$id == "duluth", ], 4326) |> st_coordinates()
  at <- wind |> distinct(lat, lon) |>
    mutate(d = (lat - duluth[2])^2 + ((lon - duluth[1]) * cos(duluth[2] * pi / 180))^2) |>
    slice_min(d, n = 1)
  hours <- wind |> semi_join(at, by = c("lat", "lon")) |> distinct(time, .keep_all = TRUE)
  bins <- hours |>
    mutate(sector = (round(from_deg / 22.5) %% 16) * 22.5) |>
    count(sector, name = "hours") |>
    right_join(tibble::tibble(sector = seq(0, 337.5, by = 22.5)), by = "sector") |>
    mutate(hours = coalesce(hours, 0L), share = hours / sum(hours)) |>
    left_join(hours |> mutate(sector = (round(from_deg / 22.5) %% 16) * 22.5) |>
                group_by(sector) |> summarise(mean_speed_ms = mean(speed_ms)), by = "sector") |>
    arrange(sector)
  list(bins = bins, cell = at, n_hours = nrow(hours))
}

summarise_numbers <- function(frame, elev, water, seas, doves, wind, rose, places) {
  bb <- st_bbox(frame)
  hib <- places[places$id == "hibbing", ]
  dry <- mask(elev$land, elev$lake_depth, inverse = TRUE)   # the tiles carry the lake surface too
  mean_all <- wind |>
    distinct(lat, lon, time, .keep_all = TRUE) |>   # two asked points can share one ERA5 cell
    summarise(u = mean(u), v = mean(v), speed = mean(speed_ms))
  tibble::tribble(
    ~item, ~value,
    "frame_width_km", (bb[["xmax"]] - bb[["xmin"]]) / 1000,
    "frame_height_km", (bb[["ymax"]] - bb[["ymin"]]) / 1000,
    "land_min_m", global(dry, "min", na.rm = TRUE)[[1]],
    "land_max_m", global(dry, "max", na.rm = TRUE)[[1]],
    "lake_max_depth_m", -global(elev$lake_depth, "min", na.rm = TRUE)[[1]],
    "water_km2", as.numeric(sum(st_area(water))) / 1e6,
    "triple_point_miss_m", seas$triple$miss_m,
    "triple_to_hibbing_km", as.numeric(st_distance(seas$triple, hib)) / 1000,
    "doves_april_records", nrow(doves),
    "doves_first_year", min(doves$year, na.rm = TRUE),
    "doves_last_year", max(doves$year, na.rm = TRUE),
    "wind_cells", nrow(distinct(wind, lat, lon)),
    "wind_hours", length(unique(wind$time)),
    "wind_mean_speed_ms", mean_all$speed,
    "wind_mean_vector_ms", sqrt(mean_all$u^2 + mean_all$v^2),
    "wind_mean_from_deg", (atan2(-mean_all$u, -mean_all$v) * 180 / pi) %% 360,
    "rose_cell_lat", rose$cell$lat,
    "rose_cell_lon", rose$cell$lon,
    "rose_hours", rose$n_hours
  )
}

main()
