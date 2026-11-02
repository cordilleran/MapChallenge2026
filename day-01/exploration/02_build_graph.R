#!/usr/bin/env Rscript
# Day 1 step 2: merge BC Freshwater Atlas (Kettle watershed group) and US NHDPlus V2 into ONE directed
# network, recompute Strahler order on the merged graph, list every confluence.
#
# Facts found on the way (kept here so the method can be audited):
#  * FWA lines in this extract are digitized UPSTREAM (first vertex = downstream end): checked with the
#    Z values (21,582 of 27,409 lines start lower than they end). They are reversed here.
#  * the extract's file CRS tag says WGS84 but the coordinates are BC Albers (EPSG:3005).
#  * NHDPlus V2 lines are digitized downstream and share exact node coordinates.
# In : fwa_stream_networks_ketl.geojson, us_nhdplus_v2.gpkg
# Out: $DATA/network.gpkg  layers: segments, confluences ;  $DATA/border_joins.csv
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr); library(igraph)})
sf_use_s2(FALSE)
DATA <- DATA_DIR
out  <- file.path(DATA, "network.gpkg")
if (file.exists(out)) stop("exists, not overwriting: ", out)
JOIN_TOL <- as.numeric(Sys.getenv("JOIN_TOL_M", "1000"))   # max gap bridged across the border, metres
KEY <- function(x, y) sprintf("%.2f_%.2f", x, y)
rev_geom <- function(g) st_sfc(lapply(g, function(l) { m <- unclass(l); st_linestring(m[nrow(m):1, , drop = FALSE]) }), crs = st_crs(g))

fwa <- st_read(input("MC26_FWA", "FWA stream network, Kettle watershed group (GeoJSON, BC Data Catalogue)"), quiet = TRUE)
st_crs(fwa) <- 3005
fwa <- fwa[!is.na(fwa$STREAM_ORDER) & fwa$STREAM_ORDER > 0, ]
fwa <- st_sf(src = "FWA", seg_id = paste0("F", fwa$LINEAR_FEATURE_ID), name = fwa$GNIS_NAME,
             edge_type = fwa$EDGE_TYPE, order_src = as.integer(fwa$STREAM_ORDER),
             geometry = rev_geom(st_geometry(fwa)))
us <- st_read(file.path(DATA, "us_nhdplus_v2.gpkg"), quiet = TRUE)
us <- st_sf(src = "NHD", seg_id = paste0("U", us$comid), name = us$gnis_name, edge_type = NA_integer_,
            order_src = as.integer(us$streamorde), geometry = st_geometry(us))
ends3 <- function(x) do.call(rbind, lapply(st_geometry(x), function(g) { m <- unclass(g); n <- nrow(m)
  c(m[1, 1], m[1, 2], if (ncol(m) >= 3) m[1, 3] else NA, m[n, 1], m[n, 2], if (ncol(m) >= 3) m[n, 3] else NA) }))
xy <- rbind(ends3(fwa), ends3(us))
seg <- rbind(st_zm(fwa), st_zm(us)) |> st_cast("LINESTRING", warn = FALSE)
seg$z_up <- xy[, 3]; seg$z_dn <- xy[, 6]
seg$from_key <- KEY(xy[, 1], xy[, 2]); seg$to_key <- KEY(xy[, 4], xy[, 5])
seg$length_m <- as.numeric(st_length(seg))

# ---- bridge across the international border (mutual nearest, within JOIN_TOL) ---------------------------
mouth <- "U23040709"
in_k <- unique(seg$to_key); out_k <- unique(seg$from_key)
sinks <- setdiff(in_k, out_k); srcs <- setdiff(out_k, in_k)
coord <- function(k) as.numeric(strsplit(k, "_")[[1]])
bridge <- function(from_sinks, to_srcs, label) {
  if (!length(from_sinks) || !length(to_srcs)) return(NULL)
  a <- t(sapply(from_sinks, coord)); b <- t(sapply(to_srcs, coord))
  d <- as.matrix(dist(rbind(a, b)))[seq_len(nrow(a)), nrow(a) + seq_len(nrow(b)), drop = FALSE]
  ia <- apply(d, 1, which.min); ib <- apply(d, 2, which.min)
  r <- NULL
  for (i in seq_along(ia)) { j <- ia[i]
    if (ib[j] == i && d[i, j] <= JOIN_TOL) r <- rbind(r, data.frame(dir = label, sink = from_sinks[i], src = to_srcs[j], gap_m = d[i, j])) }
  r }
sink_src <- function(k, col) seg$src[match(k, seg[[col]])]
fs <- sinks[sink_src(sinks, "to_key") == "FWA"]; ns <- srcs[sink_src(srcs, "from_key") == "NHD"]
ns_sink <- sinks[sink_src(sinks, "to_key") == "NHD" & seg$seg_id[match(sinks, seg$to_key)] != mouth]
fs_src <- srcs[sink_src(srcs, "from_key") == "FWA"]
joins <- rbind(bridge(fs, ns, "FWA->NHD"), bridge(ns_sink, fs_src, "NHD->FWA"))
joins$sink_seg <- seg$seg_id[match(joins$sink, seg$to_key)]; joins$src_seg <- seg$seg_id[match(joins$src, seg$from_key)]
joins$name <- seg$name[match(joins$sink, seg$to_key)]; joins$order_src <- seg$order_src[match(joins$sink, seg$to_key)]
joins <- joins[order(-joins$order_src, joins$gap_m), ]
cat("border bridges:", nrow(joins), "(", sum(joins$gap_m < 1), "touching )\n")
print(head(joins[, c("dir", "sink_seg", "src_seg", "name", "order_src", "gap_m")], 15), row.names = FALSE)
for (r in seq_len(nrow(joins))) seg$from_key[seg$from_key == joins$src[r]] <- joins$sink[r]

# ---- Order on the merged graph --------------------------------------------------------------------------
# Re-deriving Strahler on the merged graph inflates orders in braided reaches (parallel channels tie and
# bump the order: up to 74 on a river that is order 8 in FWA). So each segment keeps its source order
# (FWA's braid-aware STREAM_ORDER; NHDPlus V2 STREAMORDE) and an order never drops below the largest
# order flowing into it. That carries the BC order 8 Kettle across the border into the US reach.
g <- graph_from_data_frame(data.frame(from = seg$from_key, to = seg$to_key), directed = TRUE)
cat("graph is DAG:", is_dag(g), " weak components:", components(g, "weak")$no, "\n")
stopifnot(is_dag(g))
topo <- names(topo_sort(g, mode = "out"))
inc <- split(seq_len(nrow(seg)), seg$to_key); outg <- split(seq_len(nrow(seg)), seg$from_key)
ord <- rep(NA_integer_, nrow(seg))
for (v in topo) {
  i <- inc[[v]]; o2 <- outg[[v]]; if (is.null(o2)) next
  inflow <- if (is.null(i)) 0L else max(ord[i])
  ord[o2] <- pmax(seg$order_src[o2], inflow)
}
# segments that only end (never start) a node keep their source order
ord[is.na(ord)] <- seg$order_src[is.na(ord)]
seg$order <- ord
cat("segments without order:", sum(is.na(seg$order)), "\n")
cat("merged order vs source order, FWA:\n"); print(table(src = seg$order_src[seg$src == "FWA"], merged = seg$order[seg$src == "FWA"]))
cat("merged order vs source order, NHD:\n"); print(table(src = seg$order_src[seg$src == "NHD"], merged = seg$order[seg$src == "NHD"]))

# ---- confluences ------------------------------------------------------------------------------------------
rows <- list()
for (v in names(inc)) { i <- inc[[v]]; o2 <- outg[[v]]
  if (length(i) >= 2 && length(o2) >= 1) rows[[length(rows) + 1]] <- data.frame(
    key = v, n_in = length(i), n_out = length(o2), in_ids = paste(seg$seg_id[i], collapse = ";"),
    in_orders = paste(seg$order[i], collapse = ";"), out_id = seg$seg_id[o2[1]], out_order = seg$order[o2[1]],
    max_in = max(seg$order[i])) }
cf <- do.call(rbind, rows); cf$order_changes <- cf$out_order > cf$max_in
# braid re-join: the inflows share a divergence node a few reaches upstream, so this is a channel
# re-joining itself, not a tributary. Flagged, not deleted.
div_nodes <- names(outg)[lengths(outg) >= 2]
HOPS <- as.integer(Sys.getenv("BRAID_HOPS", "12"))
cf$braid <- vapply(seq_len(nrow(cf)), function(r) {
  ins <- strsplit(cf$in_ids[r], ";")[[1]]; if (length(ins) < 2) return(FALSE)
  ups <- lapply(ins, function(id) { n0 <- seg$from_key[match(id, seg$seg_id)]
    names(ego(g, order = HOPS, nodes = n0, mode = "in")[[1]]) })
  any(Reduce(intersect, ups[1:2]) %in% div_nodes) }, logical(1))
cat("braid re-joins flagged:", sum(cf$braid), "\n")
xyc <- t(sapply(cf$key, coord))
cf <- st_sf(cf, geometry = st_sfc(lapply(seq_len(nrow(xyc)), function(i) st_point(xyc[i, ])), crs = 3005))
cat("confluences:", nrow(cf), " order-changing:", sum(cf$order_changes), " >2 inflows:", sum(cf$n_in > 2), "\n")
print(table(out_order = cf$out_order, changes = cf$order_changes))
st_write(seg, out, "segments", quiet = TRUE); st_write(cf, out, "confluences", quiet = TRUE)
write.csv(joins, file.path(DATA, "border_joins.csv"), row.names = FALSE)
cat("wrote", out, "\n")
