# Day 1 step 23: how dense is each side, and what minimum upstream area makes 3DHP match FWA?
# Upstream area at each segment's downstream end comes from the DEM accumulation (same grid both sides).
# Output: printout only plus day01/seg_area_end.csv (segment id, area at the end, side).
# The threshold table near the end is an approximation (it filters single segments and counts every node with two or more inflows);
# the density after the real branch pruning is the one printed by step 21 and in the README.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(terra); library(dplyr)})
sf_use_s2(FALSE)
D <- DATA_DIR
seg <- st_read(file.path(D, "network3dhp.gpkg"), "segments", quiet = TRUE)
cf  <- st_read(file.path(D, "network3dhp.gpkg"), "confluences", quiet = TRUE) |> filter(!braid)
acc <- rast(file.path(D, "acc_area.tif")); crs(acc) <- "EPSG:3005"
en <- do.call(rbind, lapply(st_geometry(seg), function(g) { m <- unclass(g); m[nrow(m), 1:2] }))
off <- expand.grid(dx = c(-1, 0, 1) * 30, dy = c(-1, 0, 1) * 30)
v <- sapply(seq_len(nrow(off)), function(j) terra::extract(acc, cbind(en[, 1] + off$dx[j], en[, 2] + off$dy[j]))[, 1])
seg$A_end <- apply(v, 1, function(r) if (all(is.na(r))) NA else max(r, na.rm = TRUE)) * 900 / 1e6
seg$is_head <- !(seg$from_key %in% seg$to_key)
ll <- st_coordinates(st_transform(st_centroid(st_geometry(seg)), 4326)); seg$side <- ifelse(ll[, 2] < 49, "US", "BC")
cfll <- st_coordinates(st_transform(cf, 4326)); cf$side <- ifelse(cfll[, 2] < 49, "US", "BC")
# areas by side: Kettle footprint split at 49 N (segmentized so the parallel is not a chord)
fp <- st_union(st_make_valid(st_read(file.path(D, "units_a16.gpkg"), "units", quiet = TRUE)))
lon <- seq(-125, -110, by = 0.01); box <- st_sfc(st_polygon(list(rbind(cbind(lon, 49), c(-110, 40), c(-125, 40), c(-125, 49)))), crs = 4326) |> st_transform(3005)   # the 49th parallel as a curve, not a chord
a_us <- as.numeric(st_area(st_intersection(fp, box))) / 1e6; a_bc <- as.numeric(st_area(fp)) / 1e6 - a_us
cat(sprintf("footprint area: BC %.0f km2, US %.0f km2\n", a_bc, a_us))
cat(sprintf("junctions (braids excluded): BC %d (%.2f per 100 km2), US %d (%.2f per 100 km2)\n", sum(cf$side == "BC"), 100 * sum(cf$side == "BC") / a_bc, sum(cf$side == "US"), 100 * sum(cf$side == "US") / a_us))
cat(sprintf("stream length density: BC %.2f km/km2, US %.2f km/km2\n", sum(seg$length_m[seg$side == "BC"]) / 1000 / a_bc, sum(seg$length_m[seg$side == "US"]) / 1000 / a_us))
h <- seg[seg$is_head & !is.na(seg$A_end), ]
cat("headwater segments: upstream area at the end of the segment (km2), quantiles 10/25/50/75/90\n")
for (s in c("BC", "US")) cat(" ", s, "n =", sum(h$side == s), ":", round(quantile(h$A_end[h$side == s], c(.1, .25, .5, .75, .9)), 3), "\n")
# for each candidate A_min, how many US junctions survive (a junction survives if >= 2 inflows survive)
us <- seg[seg$side == "US", ]; jdens <- 100 * sum(cf$side == "BC") / a_bc
cat("US junction density after dropping 3DHP segments with end area < A_min (target BC =", round(jdens, 2), "per 100 km2):\n")
for (A in c(0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2)) { k <- us[!is.na(us$A_end) & us$A_end >= A, ]
  n <- sum(table(k$to_key) >= 2); cat(sprintf("  A_min %.2f km2: segments %d, junctions %d, %.2f per 100 km2, length %.0f km\n", A, nrow(k), n, 100 * n / a_us, sum(k$length_m) / 1000)) }
write.csv(st_drop_geometry(seg)[, c("seg_id", "src", "side", "A_end", "is_head", "order", "length_m")], file.path(D, "seg_area_end.csv"), row.names = FALSE)
