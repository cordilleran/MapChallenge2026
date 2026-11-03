#!/usr/bin/env Rscript
# Day 2 step 01: cut every channel in the basin into windows of about WINDOW_M metres
# and measure each one.
#   sinuosity = channel length / straight distance between the window's ends (1.0 = straight)
#   gradient  = drop between the ends / channel length, from the DEM
# FWA segments are short (median about 420 m in the Granby) and barely bend on their own,
# so each blue line (one stream, BLUE_LINE_KEY) is merged in route-measure order and cut
# into windows along its length. Segments run upstream in route-measure order, each
# starting where the last ended (join_runs() stops if a gap exceeds 1 m).
# A run of channel breaks where a lake connector or side channel interrupts it. Each run
# is cut into round(length / window_m) equal pieces (at least one): pieces run from about
# 0.67 to 1.5 windows (1.3 to 3 km at 2 km), with no stub at the top, and a run under 1.5
# windows stays whole.
# Elevation at a window end is the lowest DEM cell within SEARCH_M, so a line drawn a cell
# off the valley floor still reads the channel. Gradient over short windows is noisy on a
# 30 m DEM; it is shown as a broad pattern.
# In : MC26_FWA, MC26_DEM_TIF   Out: $MC26_DAY02_DATA/windows.gpkg
#      (layers windows, other_lines, mouth), all in BC Albers (EPSG:3005)
#
# Layout: main() holds the pipeline and comes first, so the script reads as a table of
# contents; the helpers it calls follow, and main() is called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({
  library(sf)
  library(dplyr)
  library(purrr)
  library(terra)
})

main <- function() {
  # raw inputs are checked here, not in config.R, so steps 02 and 03 run without them
  fwa_path <- read_input("MC26_FWA", "BC Freshwater Atlas stream network, Kettle group (KETL)")
  dem_path <- read_input("MC26_DEM_TIF", "a 30 m DEM GeoTIFF in BC Albers covering the basin")
  basin <- read_fwa(fwa_path, crs = MEASURE_CRS) |>
    filter_basin(code = BASIN_CODE)
  segments <- basin |>
    keep_channel(edge_types = CHANNEL_TYPES) |>
    join_runs()                                  # one row per segment, tagged with its run
  windows <- segments |>
    cut_runs(window_m = WINDOW_M) |>             # one row per piece, with its Strahler order
    measure_sinuosity() |>
    add_gradient(read_dem(dem_path, crs = MEASURE_CRS), search_m = SEARCH_M)
  other <- drop_channel(basin, edge_types = CHANNEL_TYPES)
  mouth <- find_mouth(segments)

  write_layers(list(windows = windows, other_lines = other, mouth = mouth),
               file.path(DATA_DIR, "windows.gpkg"))
  report_numbers(basin, segments, windows, code = BASIN_CODE, main_stem = MAIN_STEM)
}

# ---- read and select ------------------------------------------------------------------

# FWA stream network as sf. The KETL extract carries a WGS84 tag on BC Albers
# coordinates (Day 1), so the CRS is set, not transformed.
read_fwa <- function(path, crs) {
  st_read(path, quiet = TRUE) |>
    st_set_crs(crs) |>
    suppressWarnings()
}

# Segments whose watershed code starts with `code`.
filter_basin <- function(fwa, code) {
  basin <- fwa[startsWith(fwa$FWA_WATERSHED_CODE, code), ]
  if (nrow(basin) == 0) stop("no FWA segments have a watershed code starting ", code, call. = FALSE)
  basin
}

# Segments that are channel (`edge_types`), as sf in the same CRS.
keep_channel <- function(basin, edge_types) {
  basin[basin$EDGE_TYPE %in% edge_types, ]
}

# Segments that are not channel (lake connectors, side channels), two columns kept.
drop_channel <- function(basin, edge_types) {
  basin[!basin$EDGE_TYPE %in% edge_types, c("EDGE_TYPE", "GNIS_NAME")]
}

# 30 m DEM as a SpatRaster; elevations in m. The file's tag is set, not reprojected.
read_dem <- function(path, crs) {
  dem <- rast(path)
  crs(dem) <- paste0("EPSG:", crs)
  dem
}

# ---- runs of channel: consecutive channel segments of one blue line --------------------

# Segments sorted along each blue line, with `run` numbering unbroken stretches: a new
# run starts at a new blue line or where a segment does not start (route measure, m)
# where the last one ended.
join_runs <- function(segments) {
  runs <- segments |>
    arrange(BLUE_LINE_KEY, DOWNSTREAM_ROUTE_MEASURE) |>
    mutate(
      new_run = BLUE_LINE_KEY != lag(BLUE_LINE_KEY) |
        abs(DOWNSTREAM_ROUTE_MEASURE - lag(DOWNSTREAM_ROUTE_MEASURE + LENGTH_METRE)) > 1,
      run = cumsum(coalesce(new_run, TRUE))
    ) |>
    select(-new_run)
  # rule 11: the method merges a run's lines end to start
  stopifnot(
    "segments in a run must chain end to start within 1 m" = max(chain_gaps_m(runs)) <= 1,
    "every channel segment needs a Strahler order" = !anyNA(runs$STREAM_ORDER)
  )
  runs
}

# Distance (m) from the end of each segment to the start of the next one in its run.
chain_gaps_m <- function(runs) {
  ends <- end_points(runs)
  same_run <- runs$run[-1] == runs$run[-nrow(runs)]
  gap <- sqrt((ends$x_start[-1] - ends$x_end[-nrow(ends)])^2 +
                (ends$y_start[-1] - ends$y_end[-nrow(ends)])^2)
  c(0, gap[same_run])
}

# ---- cut each run into windows ---------------------------------------------------------

# One row per piece (sf lines, CRS kept): blue_line, name, order, piece, geometry.
cut_runs <- function(segments, window_m = 2000) {
  segments |>
    split(segments$run) |>
    map(cut_one_run, window_m = window_m) |>
    bind_rows() |>
    st_as_sf()
}

# Pieces of one run as sf, each with the highest Strahler order among the segments it
# overlaps, so a river widens downstream (a run-wide maximum would draw the main stem at
# full width from its source).
cut_one_run <- function(run, window_m) {
  cut <- cut_polyline(run_coords(st_geometry(run)), window_m)
  share_end <- cumsum(run$LENGTH_METRE) / sum(run$LENGTH_METRE)   # share of the run
  share_start <- c(0, share_end[-length(share_end)])
  order <- map_int(seq_along(cut$pieces), \(k) {
    overlaps <- share_start < cut$breaks[k + 1] & share_end > cut$breaks[k]
    max(run$STREAM_ORDER[overlaps])
  })
  # rule 11: a piece that overlapped no segment would give -Inf, not an order
  stopifnot("every piece needs a Strahler order" = all(is.finite(order)))
  st_sf(
    blue_line = run$BLUE_LINE_KEY[1],
    name = run$GNIS_NAME[!is.na(run$GNIS_NAME)][1],
    order = order,
    piece = seq_along(cut$pieces),
    geometry = st_sfc(map(cut$pieces, st_linestring), crs = st_crs(run))
  )
}

# One coordinate matrix (x, y in map units) for a list of lines, without repeated
# vertices (no zero-length steps).
run_coords <- function(geoms) {
  m <- do.call(rbind, map(geoms, \(g) st_coordinates(g)[, 1:2, drop = FALSE]))
  m[c(TRUE, rowSums(abs(diff(m))) > 0), , drop = FALSE]
}

# rule 6 broken: sf has no line-substring by distance, so the matrix is cut directly.
# Splits a polyline matrix (map units) into equal pieces of about `window_m` metres.
# Returns pieces (a list of matrices) and breaks (the cut points as shares of the run).
cut_polyline <- function(m, window_m) {
  d <- c(0, cumsum(sqrt(rowSums(diff(m)^2))))     # distance along the line, m
  total <- d[length(d)]
  n <- max(1, round(total / window_m))            # equal pieces, so no stub at the top
  breaks <- seq(0, total, length.out = n + 1)
  point_at <- function(s) {
    i <- pmin(findInterval(s, d, rightmost.closed = TRUE), nrow(m) - 1)
    f <- (s - d[i]) / (d[i + 1] - d[i])
    m[i, ] + f * (m[i + 1, ] - m[i, ])
  }
  pieces <- map(seq_len(n), \(k) {
    inside <- d > breaks[k] & d < breaks[k + 1]
    rbind(point_at(breaks[k]), m[inside, , drop = FALSE], point_at(breaks[k + 1]))
  })
  list(pieces = pieces, breaks = breaks / total)
}

# ---- measure ---------------------------------------------------------------------------

# Coordinates (map units) of the first and last vertex of each line, one row per line.
end_points <- function(lines) {
  ends <- map(st_geometry(lines), \(g) {
    m <- st_coordinates(g)
    m[c(1, nrow(m)), 1:2, drop = FALSE]
  })
  tibble::tibble(
    x_start = map_dbl(ends, \(m) m[1, 1]),
    y_start = map_dbl(ends, \(m) m[1, 2]),
    x_end = map_dbl(ends, \(m) m[2, 1]),
    y_end = map_dbl(ends, \(m) m[2, 2])
  )
}

# Adds length_m, chord_m (straight distance between the ends, m) and sinuosity
# (length over chord, at least 1 m of chord).
measure_sinuosity <- function(windows) {
  ends <- end_points(windows)
  windows |>
    mutate(
      length_m = as.numeric(st_length(windows)),
      chord_m = sqrt((ends$x_end - ends$x_start)^2 + (ends$y_end - ends$y_start)^2),
      sinuosity = length_m / pmax(chord_m, 1)
    )
}

# ---- gradient from the DEM -------------------------------------------------------------

# Adds z_low and z_high (m, lowest DEM cell within `search_m` of each end) and gradient
# (rise over length, m per m). Windows run upstream: the first end is the lower one.
add_gradient <- function(windows, dem, search_m = 30) {
  ends <- end_points(windows)
  windows |>
    mutate(
      z_low = low_near(dem, ends$x_start, ends$y_start, search_m),
      z_high = low_near(dem, ends$x_end, ends$y_end, search_m),
      gradient = pmax(z_high - z_low, 0) / length_m
    )
}

# Lowest DEM value (m) in the 3 x 3 block spaced `search_m` around each point.
low_near <- function(dem, x, y, search_m) {
  offsets <- expand.grid(dx = c(-1, 0, 1) * search_m, dy = c(-1, 0, 1) * search_m)
  z <- map2(offsets$dx, offsets$dy, \(dx, dy) terra::extract(dem, cbind(x + dx, y + dy))[, 1])
  z <- do.call(cbind, z)
  do.call(pmin, c(asplit(z, 2), na.rm = TRUE))   # NA only where all nine cells are NA
}

# ---- outputs ---------------------------------------------------------------------------

# The mouth: the start of the highest-order segment with the lowest route measure.
# Returns a one-point sf named "mouth".
find_mouth <- function(segments) {
  mouth_row <- segments |>
    filter(STREAM_ORDER == max(STREAM_ORDER)) |>
    slice_min(DOWNSTREAM_ROUTE_MEASURE, n = 1, with_ties = FALSE)
  st_sf(
    name = "mouth",
    geometry = st_sfc(st_point(st_coordinates(mouth_row)[1, 1:2]), crs = st_crs(segments))
  )
}

# Writes each sf in the named list as a layer of one GeoPackage (replaced every run).
write_layers <- function(layers, path) {
  if (file.exists(path)) invisible(file.remove(path))   # derived from the FWA on every run
  iwalk(layers, \(layer, name) st_write(layer, path, name, quiet = TRUE))
}

# ---- the numbers quoted on the page and in the README ----------------------------------

# Prints every figure the page quotes, one labelled line each.
report_numbers <- function(basin, segments, windows, code, main_stem) {
  pc <- \(x) sprintf("%.0f %%", 100 * x)
  cat(sprintf(
    "basin %s: %d segments, %.0f km; channel %.0f km\n", code, nrow(basin),
    sum(basin$LENGTH_METRE) / 1000, sum(segments$LENGTH_METRE) / 1000
  ))
  cat(sprintf(
    "%d lengths on %d runs; median %.0f m; under 1.3 km: %s (creeks under 3 km stay whole)\n",
    nrow(windows), n_distinct(segments$run), median(windows$length_m),
    pc(mean(windows$length_m < 1300))
  ))
  cat(
    "sinuosity quantiles (5, 25, 50, 75, 95, 99 %):",
    round(quantile(windows$sinuosity, c(.05, .25, .5, .75, .95, .99)), 2), "\n"
  )
  cat(
    "share of channel length with sinuosity 1.15 or more:",
    pc(sum(windows$length_m[windows$sinuosity >= 1.15]) / sum(windows$length_m)), "\n"
  )
  cat(
    "gradient % quantiles (5, 25, 50, 75, 95 %):",
    round(100 * quantile(windows$gradient, c(.05, .25, .5, .75, .95), na.rm = TRUE), 1), "\n"
  )
  report_inset(st_drop_geometry(windows))
  report_main_stem(st_drop_geometry(windows), name = main_stem)
}

# Prints the inset's figures: lengths of 1 km or more with a drop over 0.1 %.
report_inset <- function(windows) {
  long <- filter(windows, length_m >= 1000, gradient > 0.001)
  tenths <- long |>
    mutate(tenth = ntile(gradient, 10)) |>
    group_by(tenth) |>
    summarise(gradient = median(gradient), sinuosity = median(sinuosity))
  cat(sprintf(
    paste0("inset: %d lengths; median sinuosity %.2f in the flattest tenth (%.1f %% slope), ",
           "%.2f in the steepest (%.0f %%); Spearman %.2f\n"),
    nrow(long), tenths$sinuosity[1], 100 * tenths$gradient[1],
    tenths$sinuosity[10], 100 * tenths$gradient[10],
    cor(long$sinuosity, long$gradient, method = "spearman")
  ))
}

# Prints the main stem's figures: whole river, then the lowest 30 km by elevation.
report_main_stem <- function(windows, name) {
  granby <- windows |>
    filter(.data$name %in% .env$name) |>
    arrange(z_low) |>
    mutate(from_mouth_m = cumsum(length_m))
  if (nrow(granby) == 0) {
    message("no lengths named ", name, "; set MC26_MAIN_STEM for this basin")
    return(invisible(NULL))
  }
  lowest <- filter(granby, from_mouth_m - length_m < 30000)
  cat(sprintf(
    paste0(name, ": %.0f km, median sinuosity %.2f, orders %s; ",
           "lowest 30 km: median sinuosity %.2f, gradient %.2f %%\n"),
    sum(granby$length_m) / 1000, median(granby$sinuosity),
    paste(range(granby$order), collapse = " to "),
    median(lowest$sinuosity), 100 * median(lowest$gradient)
  ))
}

main()
