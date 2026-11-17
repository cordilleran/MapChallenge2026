#!/usr/bin/env Rscript
# Day 7 step 07: an estimate of the waves on the lake in the week of 10 to 16 April 1962
# (the week of the first Gerde's performance), for the ripple strokes (D320).
# No wave record exists for that week: ERA5's wave model has no Lake Superior cells, and the
# buoys came later. So the waves are computed from the ERA5 10 m wind and the fetch:
#   - fetch: distance upwind over open water to the shore, along 16 directions, measured on
#     the whole lake (the NCEI grid, coarsened to 1 km), not only the part inside the frame;
#   - height and period: the JONSWAP fetch-limited relations (as in the Shore Protection
#     Manual, deep water), capped at a fully developed sea; duration limits are ignored, so
#     the estimate is an upper bound for short blows. Ice is not known and is ignored.
# For each lake point the week gives a mean significant height and a mean direction toward
# which the waves travel, weighted by wave energy (height squared).
# In : $MC26_DAY07_DATA/raw/wind_hourly.csv (step 01), the NCEI grid, derived/day07.gpkg
# Out: derived/waves_week.gpkg (points: hs_m, tp_s, to_deg, fetch_km at the mean direction)
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

WEEK <- c(from = "1962-04-10T00:00", to = "1962-04-16T23:00")
POINT_STEP_M <- 5000      # spacing of the lake points
SECTORS_DEG <- seq(0, 337.5, by = 22.5)
RAY_STEP_M <- 1000
RAY_MAX_M <- 600000       # longer than the lake
G <- 9.81
OUT <- file.path(DERIVED_DIR, "waves_week.gpkg")

main <- function() {
  if (file.exists(OUT)) stop("Delete ", OUT, " to rebuild it (rerun-safe).", call. = FALSE)
  lake <- lake_mask()
  pts <- lake_points(lake)
  fetch <- fetch_table(pts, lake)
  wind <- week_wind()
  waves <- hourly_waves(pts, fetch, wind) |> summarise_week()
  out <- pts |> mutate(pid = row_number()) |> inner_join(waves, by = "pid")
  st_write(out, OUT, quiet = TRUE)
  message("Step 07: ", nrow(out), " lake points; mean Hs ", round(mean(out$hs_m), 2),
          " m (", round(min(out$hs_m), 2), " to ", round(max(out$hs_m), 2), "); ", OUT)
}

# Water (1) and land (0) on a 1 km UTM grid over the whole lake, from NCEI (below lake level)
lake_mask <- function() {
  ncei <- rast(NCEI_TIF)
  utm <- project(ncei, paste0("EPSG:", DISPLAY_CRS), res = 1000, method = "average")
  ifel(!is.na(utm) & utm < 0, 1, 0)
}

# Points every POINT_STEP_M on open water inside the frame
lake_points <- function(lake) {
  frame <- st_read(file.path(DERIVED_DIR, "day07.gpkg"), "frame", quiet = TRUE)
  grid <- st_make_grid(frame, cellsize = POINT_STEP_M, what = "centers") |> st_sf(geometry = _)
  wet <- terra::extract(lake, vect(grid))[, 2]
  grid[!is.na(wet) & wet == 1, ]
}

# Fetch for each point and each direction the wind comes FROM: walk upwind until land
fetch_table <- function(pts, lake) {
  xy <- st_coordinates(pts)
  steps <- seq(RAY_STEP_M, RAY_MAX_M, by = RAY_STEP_M)
  map(SECTORS_DEG, \(from) {
    dx <- sin(from * pi / 180)
    dy <- cos(from * pi / 180)
    fetch_m <- map_dbl(seq_len(nrow(xy)), \(i) {
      wet <- terra::extract(lake, cbind(xy[i, 1] + steps * dx, xy[i, 2] + steps * dy))[, 1]
      first_dry <- which(is.na(wet) | wet == 0)[1]
      if (is.na(first_dry)) RAY_MAX_M else steps[first_dry] - RAY_STEP_M / 2
    })
    tibble::tibble(pid = seq_len(nrow(xy)), sector = from, fetch_m = fetch_m)
  }) |> bind_rows()
}

# Hourly 10 m wind for the week at the lake cells (ERA5 via Open-Meteo, step 01)
week_wind <- function() {
  utils::read.csv(file.path(RAW_DIR, "wind_hourly.csv")) |>
    filter(time >= WEEK[["from"]], time <= WEEK[["to"]]) |>
    distinct(lat, lon, time, .keep_all = TRUE) |>
    st_as_sf(coords = c("lon", "lat"), crs = 4326, remove = FALSE) |>
    st_transform(DISPLAY_CRS)
}

# For each point and hour: the nearest ERA5 cell's wind, the fetch along it, then JONSWAP
hourly_waves <- function(pts, fetch, wind) {
  cells <- wind |> distinct(lat, lon, .keep_all = TRUE)
  nearest <- st_nearest_feature(pts, cells)
  cell_of <- tibble::tibble(pid = seq_len(nrow(pts)), lat = cells$lat[nearest], lon = cells$lon[nearest])
  hours <- st_drop_geometry(wind) |> select(lat, lon, time, speed_ms, from_deg)
  cell_of |>
    inner_join(hours, by = c("lat", "lon"), relationship = "many-to-many") |>
    mutate(sector = (round(from_deg / 22.5) %% 16) * 22.5) |>
    left_join(fetch, by = c("pid", "sector")) |>
    mutate(jonswap(speed_ms, fetch_m), to_deg = (from_deg + 180) %% 360)
}

# JONSWAP fetch-limited deep-water growth, capped at a fully developed sea
jonswap <- function(u, fetch_m) {
  u <- pmax(u, 0.1)
  x <- G * fetch_m / u^2                       # dimensionless fetch
  hs <- pmin(1.6e-3 * sqrt(x), 0.243) * u^2 / G
  tp <- pmin(0.286 * x^(1 / 3), 8.13) * u / G
  tibble::tibble(hs_m = hs, tp_s = tp)
}

# The week at each point: mean height; direction weighted by wave energy (hs^2)
summarise_week <- function(h) {
  h |>
    group_by(pid) |>
    summarise(
      hours = n(),
      hs_mean_m = mean(hs_m),
      hs_max_m = max(hs_m),
      tp_s = mean(tp_s),
      ex = sum(hs_m^2 * sin(to_deg * pi / 180)),
      ey = sum(hs_m^2 * cos(to_deg * pi / 180)),
      e2 = sum(hs_m^2),
      .groups = "drop"
    ) |>
    mutate(to_deg = (atan2(ex, ey) * 180 / pi) %% 360,
           steadiness = sqrt(ex^2 + ey^2) / pmax(e2, 1e-9)) |>   # 1 = one direction all week
    transmute(pid, hours, hs_m = hs_mean_m, hs_max_m, tp_s, to_deg, steadiness)
}

main()
