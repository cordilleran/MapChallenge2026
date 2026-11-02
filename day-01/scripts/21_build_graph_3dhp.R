#!/usr/bin/env Rscript
# Day 1 step 21: same merged network as 02_build_graph.R, but the US reach comes from USGS 3DHP (1:24k class)
# instead of NHDPlus V2 (1:100k). 3DHP carries no stream order here, so US order is computed (Strahler) from the
# 3DHP headwaters; FWA segments keep their source order and never drop below the order flowing in.
# Braid rule: a confluence whose inflows share a divergence within BRAID_HOPS upstream is a channel re-joining
# itself and does not raise the order. Canals dropped. Only segments that drain to the Kettle mouth are kept.
# In : fwa_stream_networks_ketl.geojson, us_3dhp.gpkg (step 20), dem.tif (direction check only)
# Out: $DATA/network3dhp.gpkg (segments, confluences), arms3dhp.csv, border_joins3dhp.csv. network.gpkg is untouched.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr); library(igraph); library(terra)})
sf_use_s2(FALSE)
DATA <- DATA_DIR
# TAG and MINAREA come from config.R (thinned network by default; MC26_TAG="" MC26_MINAREA=0 gives the unthinned one)
out <- file.path(DATA, paste0("network3dhp", TAG, ".gpkg")); if (file.exists(out)) stop("exists, not overwriting: ", out)
JOIN_TOL <- as.numeric(Sys.getenv("JOIN_TOL_M", "1000")); HOPS <- as.integer(Sys.getenv("BRAID_HOPS", "12"))
KEY <- function(x, y) sprintf("%.2f_%.2f", x, y)
rev_geom <- function(g) st_sfc(lapply(g, function(l) { m <- unclass(l); st_linestring(m[nrow(m):1, , drop = FALSE]) }), crs = st_crs(g))
fwa <- st_read(input("MC26_FWA", "FWA stream network, Kettle watershed group (GeoJSON, BC Data Catalogue)"), quiet = TRUE); st_crs(fwa) <- 3005
fwa <- fwa[!is.na(fwa$STREAM_ORDER) & fwa$STREAM_ORDER > 0, ]
fwa <- st_sf(src = "FWA", seg_id = paste0("F", fwa$LINEAR_FEATURE_ID), name = fwa$GNIS_NAME, order_src = as.integer(fwa$STREAM_ORDER),
             geometry = rev_geom(st_geometry(fwa)))
us <- st_read(file.path(DATA, "us_3dhp.gpkg"), "flowline_kettle", quiet = TRUE)
us <- us[!(us$featuretypelabel %in% "Canal"), ]; us <- st_cast(us, "LINESTRING", warn = FALSE)
us <- st_sf(src = "3DHP", seg_id = paste0("T", seq_len(nrow(us)), "_", us$permanentidentifier), name = us$gnisidlabel, order_src = NA_integer_, geometry = st_geometry(us))
ends2 <- function(x) do.call(rbind, lapply(st_geometry(x), function(g) { m <- unclass(g); n <- nrow(m); c(m[1, 1], m[1, 2], m[n, 1], m[n, 2]) }))
# direction check for 3DHP against the DEM: the attribute says digitized downstream; confirm
dem <- rast(file.path(DATA, "dem.tif")); crs(dem) <- "EPSG:3005"
e <- ends2(us); zs <- terra::extract(dem, e[, 1:2])[, 1]; ze <- terra::extract(dem, e[, 3:4])[, 1]
len <- as.numeric(st_length(us)); big <- len > 300 & !is.na(zs) & !is.na(ze) & abs(zs - ze) > 3
cat(sprintf("3DHP direction vs DEM (lines > 300 m with > 3 m drop, n = %d): start higher than end %.1f%%\n", sum(big), 100 * mean(zs[big] > ze[big])))
flip <- big & zs < ze; cat("lines reversed by the DEM test:", sum(flip), "\n")
if (any(flip)) st_geometry(us)[flip] <- rev_geom(st_geometry(us)[flip])
if (MINAREA > 0) {                                      # harmonise channel-start size with the BC side (step 23: BC and US junction density)
  accA <- rast(file.path(DATA, "acc_area.tif")); crs(accA) <- "EPSG:3005"; e2 <- ends2(us)
  vv <- sapply(seq_len(9), function(j) terra::extract(accA, cbind(e2[, 3] + c(-30, 0, 30)[(j - 1) %% 3 + 1], e2[, 4] + c(-30, 0, 30)[(j - 1) %/% 3 + 1]))[, 1])
  a_end <- apply(vv, 1, function(r) if (all(is.na(r))) NA else max(r, na.rm = TRUE)) * 900 / 1e6
  a_end[is.na(a_end)] <- Inf                                                    # lake connectors and cells without flow are never pruned
  fk <- KEY(e2[, 1], e2[, 2]); tk <- KEY(e2[, 3], e2[, 4])                     # a line is pruned only if no line upstream of it (or itself) reaches MINAREA
  gu <- graph_from_data_frame(data.frame(from = fk, to = tk), directed = TRUE); tpo <- names(topo_sort(gu, mode = "out"))
  inn <- split(seq_along(tk), tk); outn <- split(seq_along(fk), fk); upmax <- a_end
  for (v in tpo) { o2 <- outn[[v]]; if (is.null(o2)) next; i <- inn[[v]]; if (!is.null(i)) upmax[o2] <- pmax(upmax[o2], max(upmax[i])) }
  drop <- upmax < MINAREA; cat(sprintf("3DHP channels dropped (whole branch below %.2f km2 upstream area): %d of %d (%.0f km of %.0f km)\n", MINAREA, sum(drop), nrow(us), sum(as.numeric(st_length(us))[drop]) / 1000, sum(as.numeric(st_length(us))) / 1000))
  us <- us[!drop, ] }
seg <- rbind(st_zm(fwa), st_zm(us)); seg <- st_cast(seg, "LINESTRING", warn = FALSE)
xy <- rbind(ends2(fwa), ends2(us)); seg$from_key <- KEY(xy[, 1], xy[, 2]); seg$to_key <- KEY(xy[, 3], xy[, 4]); seg$length_m <- as.numeric(st_length(seg))
self <- seg$from_key == seg$to_key; cat("self-loop segments dropped (start = end):", sum(self), "(", paste(seg$seg_id[self], collapse = ", "), ")\n"); seg <- seg[!self, ]
# ---- border bridges (mutual nearest sink -> source, any gap up to JOIN_TOL, FWA<->3DHP only) ----------------
in_k <- unique(seg$to_key); out_k <- unique(seg$from_key); sinks <- setdiff(in_k, out_k); srcs <- setdiff(out_k, in_k)
coord <- function(k) as.numeric(strsplit(k, "_")[[1]]); sk <- function(k, col) seg$src[match(k, seg[[col]])]
bridge <- function(a_k, b_k, label) { if (!length(a_k) || !length(b_k)) return(NULL)
  a <- t(sapply(a_k, coord)); b <- t(sapply(b_k, coord)); d <- as.matrix(dist(rbind(a, b)))[seq_len(nrow(a)), nrow(a) + seq_len(nrow(b)), drop = FALSE]
  ia <- apply(d, 1, which.min); ib <- apply(d, 2, which.min); r <- NULL
  for (i in seq_along(ia)) { j <- ia[i]; if (ib[j] == i && d[i, j] <= JOIN_TOL) r <- rbind(r, data.frame(dir = label, sink = a_k[i], src = b_k[j], gap_m = d[i, j])) }; r }
joins <- rbind(bridge(sinks[sk(sinks, "to_key") == "FWA"], srcs[sk(srcs, "from_key") == "3DHP"], "FWA->3DHP"),
               bridge(sinks[sk(sinks, "to_key") == "3DHP"], srcs[sk(srcs, "from_key") == "FWA"], "3DHP->FWA"))
joins$sink_seg <- seg$seg_id[match(joins$sink, seg$to_key)]; joins$src_seg <- seg$seg_id[match(joins$src, seg$from_key)]
joins$order_src <- seg$order_src[match(joins$sink, seg$to_key)]; joins <- joins[order(-joins$order_src, joins$gap_m), ]
cat("border bridges:", nrow(joins), "\n"); print(head(joins[, c("dir", "sink_seg", "src_seg", "order_src", "gap_m")], 12), row.names = FALSE)
from0 <- seg$from_key; joins$used <- TRUE
apply_joins <- function(from_key, joins) { for (r in which(joins$used)) from_key[from_key == joins$src[r]] <- joins$sink[r]; from_key }
repeat { seg$from_key <- apply_joins(from0, joins); g <- graph_from_data_frame(data.frame(from = seg$from_key, to = seg$to_key), directed = TRUE)
  if (is_dag(g)) break
  lp <- which(seg$from_key == seg$to_key)
  if (length(lp)) { for (l in lp) { jj <- which(joins$used & joins$src == from0[l]); stopifnot(length(jj) > 0); joins$used[jj] <- FALSE; cat("bridge dropped (it made a self-loop):", joins$sink_seg[jj], "->", joins$src_seg[jj], " gap", round(joins$gap_m[jj]), "m\n") }; next }
  sc <- components(g, "strong"); bad <- names(sc$membership)[sc$membership %in% which(sc$csize > 1)]
  cand <- which(joins$used & (joins$sink %in% bad | joins$src %in% bad)); stopifnot(length(cand) > 0)
  drop <- cand[which.max(joins$gap_m[cand])]; joins$used[drop] <- FALSE
  cat("bridge dropped (it closed a cycle):", joins$sink_seg[drop], "->", joins$src_seg[drop], " gap", round(joins$gap_m[drop]), "m\n") }
cat("bridges used:", sum(joins$used), "of", nrow(joins), "\n")
cat("DAG:", is_dag(g), " weak components:", components(g, "weak")$no, "\n")
# ---- keep what drains to the Kettle mouth (the sink with the largest upstream set) -----------------------------
stopifnot(is_dag(g))
sk_nodes <- names(which(degree(g, mode = "out") == 0))
up_n <- vapply(sk_nodes, function(n) length(subcomponent(g, n, mode = "in")), numeric(1)); mouth_node <- sk_nodes[which.max(up_n)]
keep_nodes <- names(subcomponent(g, mouth_node, mode = "in")); seg <- seg[seg$to_key %in% keep_nodes & seg$from_key %in% keep_nodes, ]
cat("mouth node:", mouth_node, " segments kept:", nrow(seg), " (FWA", sum(seg$src == "FWA"), ", 3DHP", sum(seg$src == "3DHP"), ")\n")
g <- graph_from_data_frame(data.frame(from = seg$from_key, to = seg$to_key), directed = TRUE)
# ---- braid-aware confluence flag, then order ---------------------------------------------------------------------
inc <- split(seq_len(nrow(seg)), seg$to_key); outg <- split(seq_len(nrow(seg)), seg$from_key)
div_nodes <- names(outg)[lengths(outg) >= 2]
# Limit: only the first two inflows of a node are tested (31 of 13,095 junctions have three or more), so a braid among later inflows can be missed.
is_braid <- function(v) { i <- inc[[v]]; if (length(i) < 2) return(FALSE)
  ups <- lapply(i[1:2], function(k) names(ego(g, order = HOPS, nodes = seg$from_key[k], mode = "in")[[1]]))
  any(Reduce(intersect, ups) %in% div_nodes) }
topo <- names(topo_sort(g, mode = "out")); ord <- rep(NA_integer_, nrow(seg)); braid_at <- list()
for (v in topo) { o2 <- outg[[v]]; if (is.null(o2)) next; i <- inc[[v]]
  if (is.null(i)) { ord[o2] <- ifelse(is.na(seg$order_src[o2]), 1L, seg$order_src[o2]); next }
  oi <- ord[i]; mx <- max(oi); n_mx <- sum(oi == mx)
  if (length(i) >= 2) braid_at[[v]] <- is_braid(v)
  strahler <- if (n_mx >= 2 && !isTRUE(braid_at[[v]])) mx + 1L else mx
  ord[o2] <- ifelse(is.na(seg$order_src[o2]), strahler, pmax(seg$order_src[o2], mx)) }
ord[is.na(ord)] <- seg$order_src[is.na(ord)]; seg$order <- ord
cat("max order FWA:", max(seg$order[seg$src == "FWA"]), " 3DHP:", max(seg$order[seg$src == "3DHP"]), " NA:", sum(is.na(seg$order)), "\n")
print(table(order = seg$order, src = seg$src))
# ---- confluences and arms -------------------------------------------------------------------------------------------
rows <- list(); for (v in names(inc)) { i <- inc[[v]]; o2 <- outg[[v]]
  if (length(i) >= 2 && length(o2) >= 1) rows[[length(rows) + 1]] <- data.frame(key = v, n_in = length(i), n_out = length(o2), in_ids = paste(seg$seg_id[i], collapse = ";"),
    out_id = seg$seg_id[o2[1]], out_order = seg$order[o2[1]], max_in = max(seg$order[i]), braid = isTRUE(braid_at[[v]])) }
cf <- do.call(rbind, rows); cf$order_changes <- cf$out_order > cf$max_in
xyc <- t(sapply(cf$key, coord)); cf <- st_sf(cf, geometry = st_sfc(lapply(seq_len(nrow(xyc)), function(i) st_point(xyc[i, ])), crs = 3005))
cat("confluences:", nrow(cf), " order-changing:", sum(cf$order_changes & !cf$braid), " braid:", sum(cf$braid), "\n")
mats <- lapply(st_geometry(seg), function(l) unclass(l)[, 1:2, drop = FALSE]); names(mats) <- seg$seg_id
pt_along <- function(m, d, from_end) { if (from_end) m <- m[nrow(m):1, , drop = FALSE]
  sl <- sqrt(rowSums(diff(m)^2)); cum <- c(0, cumsum(sl)); d <- min(d, max(cum)); i <- max(which(cum <= d)); if (i >= nrow(m)) return(m[nrow(m), ])
  f <- (d - cum[i]) / sl[i]; m[i, ] + f * (m[i + 1, ] - m[i, ]) }
D_BEAR <- 150; arms <- list()
cfxy <- st_coordinates(cf)                                  # node coordinates once, not row by row inside the loop
for (r in seq_len(nrow(cf))) { node <- cfxy[r, 1:2]
  for (id in strsplit(cf$in_ids[r], ";")[[1]]) { p <- pt_along(mats[[id]], D_BEAR, TRUE)
    arms[[length(arms) + 1]] <- data.frame(conf = r, arm = "in", seg_id = id, nx = node[1], ny = node[2], bx = p[1], by = p[2]) }
  id <- cf$out_id[r]; p <- pt_along(mats[[id]], D_BEAR, FALSE)
  arms[[length(arms) + 1]] <- data.frame(conf = r, arm = "out", seg_id = id, nx = node[1], ny = node[2], bx = p[1], by = p[2]) }
arms <- do.call(rbind, arms); arms$bearing <- (atan2(arms$bx - arms$nx, arms$by - arms$ny) * 180 / pi) %% 360
arms$order <- seg$order[match(arms$seg_id, seg$seg_id)]; arms$src <- seg$src[match(arms$seg_id, seg$seg_id)]; arms$qc_ok <- TRUE; arms$q_rel <- 1
write.csv(arms, file.path(DATA, paste0("arms3dhp", TAG, ".csv")), row.names = FALSE); write.csv(joins, file.path(DATA, paste0("border_joins3dhp", TAG, ".csv")), row.names = FALSE)
st_write(seg, out, "segments", quiet = TRUE); st_write(cf, out, "confluences", quiet = TRUE); cat("wrote", out, "and", paste0("arms3dhp", TAG, ".csv:"), nrow(arms), "arms\n")
