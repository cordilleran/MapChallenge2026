# Day 1 step 22: Shreve magnitude (number of headwater sources upstream) on the 3DHP-based network.
# Each headwater segment is 1; a segment below a junction carries the sum of its inflows. At a braid re-join
# (flagged in step 21) the inflows share upstream sources, so the larger inflow is taken instead of the sum.
# A divergence passes the full magnitude down each channel (approximation). In: network3dhp<TAG>.gpkg, arms3dhp<TAG>.csv, mouth3dhp<TAG>.csv.
# Out: arms3dhp<TAG>_mag.csv (arms with `mag`) and mouth3dhp<TAG>_mag.csv (the Kettle arm at the Columbia, with `mag`).
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr); library(igraph)})
D <- DATA_DIR; out <- file.path(D, paste0("arms3dhp", TAG, "_mag.csv")); stopifnot(!file.exists(out))
seg <- st_read(file.path(D, paste0("network3dhp", TAG, ".gpkg")), "segments", quiet = TRUE) |> st_drop_geometry()
cf  <- st_read(file.path(D, paste0("network3dhp", TAG, ".gpkg")), "confluences", quiet = TRUE) |> st_drop_geometry()
braid_keys <- cf$key[cf$braid]
g <- graph_from_data_frame(data.frame(from = seg$from_key, to = seg$to_key), directed = TRUE)
topo <- names(topo_sort(g, mode = "out")); inc <- split(seq_len(nrow(seg)), seg$to_key); outg <- split(seq_len(nrow(seg)), seg$from_key)
mag <- rep(NA_real_, nrow(seg))
for (v in topo) { o2 <- outg[[v]]; if (is.null(o2)) next; i <- inc[[v]]
  mag[o2] <- if (is.null(i)) 1 else if (v %in% braid_keys) max(mag[i]) else sum(mag[i]) }
mag[is.na(mag)] <- 1; seg$mag <- mag
cat("magnitude: median", median(mag), " p90", quantile(mag, .9), " p99", quantile(mag, .99), " max", max(mag), "\n")
cat("by Strahler order (median magnitude):\n"); print(round(tapply(seg$mag, seg$order, median)))
arms <- read.csv(file.path(D, paste0("arms3dhp", TAG, ".csv"))); arms$mag <- seg$mag[match(arms$seg_id, seg$seg_id)]
mouth_mag <- max(arms$mag[arms$arm == "out"], na.rm = TRUE); cat("largest outflow magnitude (mouth side):", mouth_mag, "\n")
write.csv(arms, out, row.names = FALSE)
mouth <- read.csv(file.path(D, paste0("mouth3dhp", TAG, ".csv"))); mouth$mag <- seg$mag[match(mouth$seg_id, seg$seg_id)]   # the Kettle at the Columbia
write.csv(mouth, file.path(D, paste0("mouth3dhp", TAG, "_mag.csv")), row.names = FALSE); cat("magnitude at the mouth:", paste(mouth$mag[mouth$arm == "kettle"], collapse = ", "), "\n")
