#!/usr/bin/env Rscript
# Day 2 step 01: cut every channel in the basin into windows of about WINDOW metres and measure each one.
#   sinuosity = channel length / straight distance between the window's ends (1.0 = straight)
#   gradient  = drop between the ends / channel length, from the DEM
# FWA segments are short (median about 420 m in the Granby) and barely bend on their own, so each blue line
# (one stream, BLUE_LINE_KEY) is merged in route-measure order and cut into windows along its length.
# Segments run upstream in route-measure order, each starting where the last ended (checked: 100 % within 1 m).
# A run of channel breaks where a lake connector or side channel interrupts it. Each run is cut into
# round(length / WINDOW) equal pieces (at least one): pieces run from about 0.67 to 1.5 windows (1.3 to 3 km at
# 2 km), with no stub at the top, and a run under 1.5 windows stays whole.
# Elevation at a window end is the lowest DEM cell within 30 m, so a line drawn a cell off the valley floor
# still reads the channel. Gradient over short windows is noisy on a 30 m DEM; it is shown as a broad pattern.
# In : MC26_FWA, MC26_DEM_TIF   Out: $MC26_DAY02_DATA/windows.gpkg (layers windows, other_lines, mouth)
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr); library(terra)})

fwa <- st_read(FWA, quiet = TRUE)
fwa <- suppressWarnings(st_set_crs(fwa, 3005))                                    # the KETL extract carries a WGS84 tag on BC Albers coordinates (Day 1)
basin <- fwa[startsWith(fwa$FWA_WATERSHED_CODE, BASIN_CODE), ]
is_channel <- basin$EDGE_TYPE %in% CHANNEL
cat(sprintf("basin %s: %d segments, %.0f km; channel %.0f km\n", BASIN_CODE, nrow(basin),
            sum(basin$LENGTH_METRE) / 1000, sum(basin$LENGTH_METRE[is_channel]) / 1000))

# ---- runs of channel: consecutive channel segments of one blue line ------------------------------------------------
seg <- basin[is_channel, ] |> arrange(BLUE_LINE_KEY, DOWNSTREAM_ROUTE_MEASURE)
seg$run <- with(seg, cumsum(c(TRUE, BLUE_LINE_KEY[-1] != BLUE_LINE_KEY[-length(BLUE_LINE_KEY)] |
  abs(DOWNSTREAM_ROUTE_MEASURE[-1] - (DOWNSTREAM_ROUTE_MEASURE + LENGTH_METRE)[-length(BLUE_LINE_KEY)]) > 1)))

run_coords <- function(geoms) {                         # one coordinate matrix, without repeated vertices (no zero-length steps)
  m <- do.call(rbind, lapply(geoms, function(g) st_coordinates(g)[, 1:2, drop = FALSE]))
  m[c(TRUE, rowSums(abs(diff(m))) > 0), , drop = FALSE]
}

cut_windows <- function(m, window) {                    # split a polyline into pieces of about `window` metres
  d <- c(0, cumsum(sqrt(rowSums(diff(m)^2)))); total <- d[length(d)]
  n <- max(1, round(total / window))                    # equal pieces, so no stub at the top
  breaks <- seq(0, total, length.out = n + 1)
  at <- function(s) { i <- findInterval(s, d, rightmost.closed = TRUE); i <- pmin(i, nrow(m) - 1)
    f <- (s - d[i]) / (d[i + 1] - d[i]); m[i, ] + f * (m[i + 1, ] - m[i, ]) }
  pieces <- lapply(seq_len(n), function(k) {
    inside <- d > breaks[k] & d < breaks[k + 1]
    rbind(at(breaks[k]), m[inside, , drop = FALSE], at(breaks[k + 1]))
  })
  list(pieces = pieces, breaks = breaks / total)          # breaks as shares of the run, to match segments to pieces
}

runs <- split(seg, seg$run)
rows <- lapply(runs, function(r) {
  cw <- cut_windows(run_coords(st_geometry(r)), WINDOW)
  # Each piece takes the highest Strahler order among the segments it overlaps, so a river widens downstream
  # (a run-wide maximum would draw the main stem at full width from its source).
  share <- cumsum(r$LENGTH_METRE) / sum(r$LENGTH_METRE); start <- c(0, share[-length(share)])
  order <- vapply(seq_along(cw$pieces), function(k)
    max(r$STREAM_ORDER[start < cw$breaks[k + 1] & share > cw$breaks[k]]), integer(1))
  st_sf(blue_line = r$BLUE_LINE_KEY[1], name = r$GNIS_NAME[!is.na(r$GNIS_NAME)][1],
        order = order, piece = seq_along(cw$pieces),
        geometry = st_sfc(lapply(cw$pieces, st_linestring), crs = 3005))
})
win <- do.call(rbind, rows)
win$length_m <- as.numeric(st_length(win))
ends <- t(vapply(st_geometry(win), function(g) { m <- st_coordinates(g); c(m[1, 1:2], m[nrow(m), 1:2]) }, numeric(4)))
win$chord_m <- sqrt((ends[, 3] - ends[, 1])^2 + (ends[, 4] - ends[, 2])^2)
win$sinuosity <- win$length_m / pmax(win$chord_m, 1)

# ---- gradient from the DEM -----------------------------------------------------------------------------------------
dem <- rast(DEM); crs(dem) <- "EPSG:3005"
low_near <- function(x, y) {                            # lowest cell in the 3 x 3 block around each point
  off <- expand.grid(dx = c(-30, 0, 30), dy = c(-30, 0, 30))
  z <- sapply(seq_len(nrow(off)), function(k) terra::extract(dem, cbind(x + off$dx[k], y + off$dy[k]))[, 1])
  apply(z, 1, function(v) if (all(is.na(v))) NA else min(v, na.rm = TRUE))
}
win$z_low  <- low_near(ends[, 1], ends[, 2])            # windows run upstream: the first end is the lower one
win$z_high <- low_near(ends[, 3], ends[, 4])
win$gradient <- pmax(win$z_high - win$z_low, 0) / win$length_m

other <- basin[!is_channel, c("EDGE_TYPE", "GNIS_NAME")]
mouth_row <- seg[seg$STREAM_ORDER == max(seg$STREAM_ORDER), ] |> slice_min(DOWNSTREAM_ROUTE_MEASURE, n = 1, with_ties = FALSE)
mouth <- st_sf(name = "mouth", geometry = st_sfc(st_point(st_coordinates(mouth_row)[1, 1:2]), crs = 3005))

out <- file.path(DATA_DIR, "windows.gpkg")
if (file.exists(out)) invisible(file.remove(out))       # derived from the FWA file on every run
st_write(win, out, "windows", quiet = TRUE); st_write(other, out, "other_lines", quiet = TRUE); st_write(mouth, out, "mouth", quiet = TRUE)
# ---- the numbers quoted on the page and in the README -----------------------------------------------------------------
pc <- function(x) sprintf("%.0f %%", 100 * x)
cat(sprintf("%d lengths on %d runs; median %.0f m; under 1.3 km: %s (creeks under 3 km stay whole)\n",
            nrow(win), length(runs), median(win$length_m), pc(mean(win$length_m < 1300))))
cat("sinuosity quantiles (5, 25, 50, 75, 95, 99 %):", round(quantile(win$sinuosity, c(.05, .25, .5, .75, .95, .99)), 2), "\n")
cat("share of channel length with sinuosity 1.15 or more:", pc(sum(win$length_m[win$sinuosity >= 1.15]) / sum(win$length_m)), "\n")
cat("gradient % quantiles (5, 25, 50, 75, 95 %):", round(100 * quantile(win$gradient, c(.05, .25, .5, .75, .95), na.rm = TRUE), 1), "\n")
long <- st_drop_geometry(win)[win$length_m >= 1000 & win$gradient > 0.001, ]   # the inset's set: 1 km or more, a drop over 0.1 %
tenth <- long |> mutate(t = ntile(gradient, 10)) |> group_by(t) |> summarise(gradient = median(gradient), sinuosity = median(sinuosity))
cat(sprintf("inset: %d lengths; median sinuosity %.2f in the flattest tenth (%.1f %% slope), %.2f in the steepest (%.0f %%); Spearman %.2f\n",
            nrow(long), tenth$sinuosity[1], 100 * tenth$gradient[1], tenth$sinuosity[10], 100 * tenth$gradient[10],
            cor(long$sinuosity, long$gradient, method = "spearman")))
main <- st_drop_geometry(win)[win$name %in% "Granby River", ] |> arrange(z_low) |> mutate(from_mouth = cumsum(length_m))
low30 <- main[main$from_mouth - main$length_m < 30000, ]
cat(sprintf("Granby River: %.0f km, median sinuosity %.2f, orders %s; lowest 30 km: median sinuosity %.2f, gradient %.2f %%\n",
            sum(main$length_m) / 1000, median(main$sinuosity), paste(range(main$order), collapse = " to "),
            median(low30$sinuosity), 100 * median(low30$gradient)))
