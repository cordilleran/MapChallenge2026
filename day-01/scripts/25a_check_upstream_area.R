#!/usr/bin/env Rscript
# Day 1 step 25a (a check; writes nothing): why the map shows upstream area per junction and not per arm.
#   1. Junction areas before the downstream raise: share of junction pairs where the next junction down drains at least
#      as much. Below 100 % means the 60 m sampling sometimes misses the channel, so step 25 raises those junctions.
#   2. Arm areas: sample each arm 150 m from the junction (the bearing point from step 21) and test whether the inflows
#      add up to the outflow within 20 %. They often do not: near a junction the DEM channel and the mapped lines part,
#      so one window can catch the main stem for two arms or miss a small tributary. Per-arm areas would need one
#      catchment traced per line, which is a separate processing step.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(terra); library(igraph)})
source(file.path(.here, "lib_area.R"))

net <- file.path(DATA_DIR, paste0("network3dhp", TAG, ".gpkg"))
cf <- st_read(net, "confluences", quiet = TRUE); cf$conf <- seq_len(nrow(cf))
seg <- st_read(net, "segments", quiet = TRUE) |> st_drop_geometry()
arms <- read.csv(file.path(DATA_DIR, paste0("arms3dhp", TAG, "_mag.csv")))
acc <- rast(file.path(DATA_DIR, "acc_area.tif")); crs(acc) <- "EPSG:3005"

cxy <- st_coordinates(cf)
area <- area_near(acc, cxy[, 1], cxy[, 2]); nxt <- next_junction(cf, seg)
ok <- !is.na(nxt) & !is.na(area) & !is.na(area[nxt])
cat(sprintf("1. junction pairs where the next junction down drains at least as much: %.0f %% of %d (before the raise)\n",
            100 * mean(area[nxt[ok]] >= area[ok]), sum(ok)))

arms <- arms[arms$conf %in% cf$conf[!cf$braid], ]            # braid re-joins excluded, as on the maps
arms$area <- area_near(acc, arms$bx, arms$by)
by_conf <- split(arms, arms$conf)
ratio <- vapply(by_conf, function(a) {
  inflow <- a$area[a$arm == "in"]; outflow <- a$area[a$arm == "out"]
  if (length(outflow) != 1 || anyNA(inflow) || is.na(outflow) || outflow == 0) NA_real_ else sum(inflow) / outflow
}, numeric(1))
ratio <- ratio[!is.na(ratio)]
cat(sprintf("2. junctions where the inflow arms add up to the outflow within 20 %%: %.0f %% of %d\n",
            100 * mean(abs(ratio - 1) <= 0.2), length(ratio)))
cat("   inflow sum / outflow, quantiles:\n"); print(round(quantile(ratio, c(.05, .25, .5, .75, .95)), 2))
