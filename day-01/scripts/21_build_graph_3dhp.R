#!/usr/bin/env Rscript
# Day 1 step 21: one directed stream network for the whole Kettle River, BC and US, ending where the Kettle meets the Columbia.
#
# BC lines come from the BC Freshwater Atlas (FWA), US lines from USGS 3DHP flowlines. Two faults in the FWA extract are
# corrected first: its lines are digitized upstream (21,582 of 27,409 start lower than they end), so they are reversed, and
# its CRS tag says WGS84 while the coordinates are BC Albers, so the CRS is set (not reprojected) to EPSG:3005.
#
# Order: FWA keeps its source Strahler order and never drops below the order flowing in. 3DHP has no order here, so US order
# is computed (Strahler). A braid re-join (a channel that split and meets itself again) does not raise the order.
#
# In : MC26_FWA (FWA streams, KETL), us_3dhp.gpkg (step 20), dem.tif and acc_area.tif (step 04)
# Out: $MC26_DATA/network3dhp<TAG>.gpkg (layers segments, confluences), arms3dhp<TAG>.csv, mouth3dhp<TAG>.csv, border_joins3dhp<TAG>.csv
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr); library(igraph); library(terra)})
sf_use_s2(FALSE)

out <- file.path(DATA_DIR, paste0("network3dhp", TAG, ".gpkg"))
if (file.exists(out)) stop("exists, not overwriting: ", out)
JOIN_TOL <- 1000   # m: largest gap bridged between a BC line end and a US line start at the border
HOPS     <- 12     # segments searched upstream when testing whether two inflows share a split (braid test)
D_BEAR   <- 150    # m along each line used to set an arm's bearing

# ---- helpers ------------------------------------------------------------------------------------------------------
node_key <- function(x, y) sprintf("%.2f_%.2f", x, y)                 # a node is its coordinates to the centimetre
key_xy   <- function(k) as.numeric(strsplit(k, "_")[[1]])
reverse_lines <- function(g) st_sfc(lapply(g, function(l) { m <- unclass(l); st_linestring(m[nrow(m):1, , drop = FALSE]) }), crs = st_crs(g))
line_ends <- function(x) {                                           # one row per line: x0, y0 (start), x1, y1 (end)
  t(vapply(st_geometry(x), function(g) { m <- unclass(g); n <- nrow(m); c(m[1, 1], m[1, 2], m[n, 1], m[n, 2]) }, numeric(4)))
}
point_along <- function(m, d, from_end) {                            # the point d metres along a line, from its start or its end
  if (from_end) m <- m[nrow(m):1, , drop = FALSE]
  step <- sqrt(rowSums(diff(m)^2)); cum <- c(0, cumsum(step)); d <- min(d, max(cum))
  i <- max(which(cum <= d)); if (i >= nrow(m)) return(m[nrow(m), ])
  m[i, ] + (d - cum[i]) / step[i] * (m[i + 1, ] - m[i, ])
}

# ---- BC lines (FWA) -------------------------------------------------------------------------------------------------
fwa <- st_read(input("MC26_FWA", "FWA stream network, Kettle watershed group (GeoJSON, BC Data Catalogue)"), quiet = TRUE)
st_crs(fwa) <- 3005                                                  # tag says WGS84; coordinates are BC Albers
fwa <- fwa[!is.na(fwa$STREAM_ORDER) & fwa$STREAM_ORDER > 0, ]
fwa <- st_sf(src = "FWA", seg_id = paste0("F", fwa$LINEAR_FEATURE_ID), name = fwa$GNIS_NAME,
             order_src = as.integer(fwa$STREAM_ORDER), geometry = reverse_lines(st_geometry(fwa)))

# ---- US lines (3DHP) ------------------------------------------------------------------------------------------------
us <- st_read(file.path(DATA_DIR, "us_3dhp.gpkg"), "flowline_kettle", quiet = TRUE)
us <- us[!(us$featuretypelabel %in% "Canal"), ]
us <- us[!(us$gnisidlabel %in% "Columbia River"), ]                 # the network ends at the Columbia; its own lines are not part of it
us <- st_cast(us, "LINESTRING", warn = FALSE)
us <- st_sf(src = "3DHP", seg_id = paste0("T", seq_len(nrow(us)), "_", us$permanentidentifier), name = us$gnisidlabel,
            order_src = NA_integer_, connector = us$featuretypelabel %in% "Waterbody Connector", geometry = st_geometry(us))

# 3DHP is digitized downstream; check that against the DEM on channel lines long and steep enough to tell.
# Waterbody connectors are skipped: on a lake or reservoir surface the DEM is flat and noisy (a 3 m rise on Lake Roosevelt
# once reversed a Kettle River connector and cut the network 20 km above the Columbia).
dem <- rast(file.path(DATA_DIR, "dem.tif")); crs(dem) <- "EPSG:3005"
e <- line_ends(us)
z_start <- terra::extract(dem, e[, 1:2])[, 1]
z_end   <- terra::extract(dem, e[, 3:4])[, 1]
testable <- !us$connector & as.numeric(st_length(us)) > 300 & !is.na(z_start) & !is.na(z_end) & abs(z_start - z_end) > 3
cat(sprintf("3DHP direction vs DEM (channel lines > 300 m with > 3 m drop, n = %d): start higher than end %.1f%%\n",
            sum(testable), 100 * mean(z_start[testable] > z_end[testable])))
flip <- testable & z_start < z_end
cat("lines reversed by the DEM test:", sum(flip), "\n")
if (any(flip)) st_geometry(us)[flip] <- reverse_lines(st_geometry(us)[flip])

# Thinning (MINAREA > 0): 3DHP starts channels at about half the upstream area FWA does, so the US side has twice the
# junctions per km2. A line is dropped only if neither it nor any line upstream of it reaches MINAREA km2 of DEM upstream
# area, so whole headwater branches go and the main chain is never cut. Lines with no flow cell are never dropped.
if (MINAREA > 0) {
  acc <- rast(file.path(DATA_DIR, "acc_area.tif")); crs(acc) <- "EPSG:3005"
  e <- line_ends(us); nb <- expand.grid(dx = c(-30, 0, 30), dy = c(-30, 0, 30))      # largest value in the 3 x 3 cells at the line end
  cells <- sapply(seq_len(nrow(nb)), function(j) terra::extract(acc, cbind(e[, 3] + nb$dx[j], e[, 4] + nb$dy[j]))[, 1])
  area_end <- apply(cells, 1, function(r) if (all(is.na(r))) Inf else max(r, na.rm = TRUE)) * 900 / 1e6
  from <- node_key(e[, 1], e[, 2]); to <- node_key(e[, 3], e[, 4])
  gu <- graph_from_data_frame(data.frame(from, to), directed = TRUE)
  into <- split(seq_along(to), to); leaving <- split(seq_along(from), from)
  up_max <- area_end                                                  # largest end area on the line or anywhere upstream of it
  for (v in names(topo_sort(gu, mode = "out"))) {
    if (is.null(leaving[[v]]) || is.null(into[[v]])) next
    up_max[leaving[[v]]] <- pmax(up_max[leaving[[v]]], max(up_max[into[[v]]]))
  }
  drop <- up_max < MINAREA
  km <- as.numeric(st_length(us)) / 1000
  cat(sprintf("3DHP lines dropped (whole branch below %.2f km2): %d of %d (%.0f of %.0f km)\n",
              MINAREA, sum(drop), nrow(us), sum(km[drop]), sum(km)))
  us <- us[!drop, ]
}

# ---- one table of segments with node keys ----------------------------------------------------------------------------
seg <- rbind(st_zm(fwa), st_zm(us[, names(fwa)]))
seg <- st_cast(seg, "LINESTRING", warn = FALSE)
e <- line_ends(seg)
seg$from_key <- node_key(e[, 1], e[, 2]); seg$to_key <- node_key(e[, 3], e[, 4])
seg$length_m <- as.numeric(st_length(seg))
self <- seg$from_key == seg$to_key
cat("closed-ring segments dropped (start = end):", sum(self), "\n")
seg <- seg[!self, ]

# ---- border bridges: join a line that ends on one side to the nearest line that starts on the other ------------------
# A pair is joined only if each is the other's nearest candidate (mutual nearest) and the gap is at most JOIN_TOL.
sinks <- setdiff(seg$to_key, seg$from_key)                           # line ends with nothing leaving them
heads <- setdiff(seg$from_key, seg$to_key)                           # line starts with nothing arriving
src_of <- function(k, col) seg$src[match(k, seg[[col]])]
mutual_nearest <- function(a_k, b_k, label) {
  if (!length(a_k) || !length(b_k)) return(NULL)
  a <- t(sapply(a_k, key_xy)); b <- t(sapply(b_k, key_xy))
  d <- as.matrix(dist(rbind(a, b)))[seq_len(nrow(a)), nrow(a) + seq_len(nrow(b)), drop = FALSE]
  best_b <- apply(d, 1, which.min); best_a <- apply(d, 2, which.min)
  ok <- which(best_a[best_b] == seq_along(best_b) & d[cbind(seq_along(best_b), best_b)] <= JOIN_TOL)
  data.frame(dir = rep(label, length(ok)), sink = a_k[ok], src = b_k[best_b[ok]], gap_m = d[cbind(ok, best_b[ok])])
}
joins <- rbind(mutual_nearest(sinks[src_of(sinks, "to_key") == "FWA"],  heads[src_of(heads, "from_key") == "3DHP"], "FWA->3DHP"),
               mutual_nearest(sinks[src_of(sinks, "to_key") == "3DHP"], heads[src_of(heads, "from_key") == "FWA"],  "3DHP->FWA"))
joins$sink_seg  <- seg$seg_id[match(joins$sink, seg$to_key)]
joins$src_seg   <- seg$seg_id[match(joins$src, seg$from_key)]
joins$order_src <- seg$order_src[match(joins$sink, seg$to_key)]
joins <- joins[order(-joins$order_src, joins$gap_m), ]
joins$used <- TRUE
cat("border bridge candidates:", nrow(joins), "\n")

# A bridge moves the start of the joined line onto the end of the other. Bridges that close a cycle or make a line start
# and end on the same node are dropped one at a time (the longest gap in the cycle first) until the graph is acyclic.
from_raw <- seg$from_key
apply_joins <- function(from_key, joins) {
  for (r in which(joins$used)) from_key[from_key == joins$src[r]] <- joins$sink[r]
  from_key
}
repeat {
  seg$from_key <- apply_joins(from_raw, joins)
  g <- graph_from_data_frame(data.frame(from = seg$from_key, to = seg$to_key), directed = TRUE)
  if (is_dag(g)) break
  loops <- which(seg$from_key == seg$to_key)
  if (length(loops)) {
    for (l in loops) {
      jj <- which(joins$used & joins$src == from_raw[l]); stopifnot(length(jj) > 0)
      joins$used[jj] <- FALSE
      cat("bridge dropped (self-loop):", joins$sink_seg[jj], "->", joins$src_seg[jj], round(joins$gap_m[jj]), "m\n")
    }
    next
  }
  sc <- components(g, "strong"); in_cycle <- names(sc$membership)[sc$membership %in% which(sc$csize > 1)]
  cand <- which(joins$used & (joins$sink %in% in_cycle | joins$src %in% in_cycle)); stopifnot(length(cand) > 0)
  worst <- cand[which.max(joins$gap_m[cand])]; joins$used[worst] <- FALSE
  cat("bridge dropped (cycle):", joins$sink_seg[worst], "->", joins$src_seg[worst], round(joins$gap_m[worst]), "m\n")
}
cat("bridges used:", sum(joins$used), "of", nrow(joins), "\n")

# ---- the mouth: the node where the Kettle meets the Columbia; keep everything that drains to it ------------------------
m_ll <- as.numeric(strsplit(MOUTH_LONLAT, ",")[[1]])
m_xy <- st_coordinates(st_transform(st_sfc(st_point(m_ll), crs = 4326), 3005))
end_nodes <- names(which(degree(g, mode = "out") == 0))
d_mouth <- sapply(end_nodes, function(k) sqrt(sum((key_xy(k) - m_xy)^2)))
mouth_node <- end_nodes[which.min(d_mouth)]
if (min(d_mouth) > 100) stop(sprintf("no network end within 100 m of the mouth (%s); nearest %.0f m", MOUTH_LONLAT, min(d_mouth)))
keep <- names(subcomponent(g, mouth_node, mode = "in"))
seg <- seg[seg$to_key %in% keep & seg$from_key %in% keep, ]
cat(sprintf("mouth node %s (%.0f m from %s); segments kept %d (FWA %d, 3DHP %d)\n", mouth_node, min(d_mouth), MOUTH_LONLAT,
            nrow(seg), sum(seg$src == "FWA"), sum(seg$src == "3DHP")))
g <- graph_from_data_frame(data.frame(from = seg$from_key, to = seg$to_key), directed = TRUE)

# ---- order (Strahler), braid-aware -----------------------------------------------------------------------------------
into    <- split(seq_len(nrow(seg)), seg$to_key)                     # segments arriving at each node
leaving <- split(seq_len(nrow(seg)), seg$from_key)                   # segments leaving each node
splits  <- names(leaving)[lengths(leaving) >= 2]
# Limit: only the first two inflows of a node are tested, so a braid among a third or later inflow can be missed.
is_braid <- function(v) {
  ups <- lapply(into[[v]][1:2], function(k) names(ego(g, order = HOPS, nodes = seg$from_key[k], mode = "in")[[1]]))
  any(Reduce(intersect, ups) %in% splits)
}
ord <- rep(NA_integer_, nrow(seg)); braid <- list()
for (v in names(topo_sort(g, mode = "out"))) {
  o <- leaving[[v]]; if (is.null(o)) next
  i <- into[[v]]
  if (is.null(i)) { ord[o] <- ifelse(is.na(seg$order_src[o]), 1L, seg$order_src[o]); next }   # a headwater
  top <- max(ord[i])
  if (length(i) >= 2) braid[[v]] <- is_braid(v)
  strahler <- if (sum(ord[i] == top) >= 2 && !isTRUE(braid[[v]])) top + 1L else top
  ord[o] <- ifelse(is.na(seg$order_src[o]), strahler, pmax(seg$order_src[o], top))
}
seg$order <- ifelse(is.na(ord), seg$order_src, ord)
cat("max order FWA:", max(seg$order[seg$src == "FWA"]), " 3DHP:", max(seg$order[seg$src == "3DHP"]), "\n")
print(table(order = seg$order, src = seg$src))

# ---- junctions and arms ------------------------------------------------------------------------------------------------
rows <- lapply(names(into), function(v) {
  i <- into[[v]]; o <- leaving[[v]]
  if (length(i) < 2 || length(o) < 1) return(NULL)
  data.frame(key = v, n_in = length(i), n_out = length(o), in_ids = paste(seg$seg_id[i], collapse = ";"), out_id = seg$seg_id[o[1]],
             out_order = seg$order[o[1]], max_in = max(seg$order[i]), braid = isTRUE(braid[[v]]))
})
cf <- do.call(rbind, rows); cf$order_changes <- cf$out_order > cf$max_in
xy <- t(sapply(cf$key, key_xy))
cf <- st_sf(cf, geometry = st_sfc(lapply(seq_len(nrow(xy)), function(r) st_point(xy[r, ])), crs = 3005))
cat("junctions:", nrow(cf), " order-raising:", sum(cf$order_changes & !cf$braid), " braid re-joins:", sum(cf$braid), "\n")

lines_xy <- lapply(st_geometry(seg), function(l) unclass(l)[, 1:2, drop = FALSE]); names(lines_xy) <- seg$seg_id
arm_row <- function(conf, arm, id, node, from_end) {
  p <- point_along(lines_xy[[id]], D_BEAR, from_end)
  data.frame(conf = conf, arm = arm, seg_id = id, nx = node[1], ny = node[2], bx = p[1], by = p[2])
}
arms <- do.call(rbind, lapply(seq_len(nrow(cf)), function(r) {
  ins <- strsplit(cf$in_ids[r], ";")[[1]]
  rbind(do.call(rbind, lapply(ins, function(id) arm_row(r, "in", id, xy[r, ], TRUE))),   # inflows point back up their line
        arm_row(r, "out", cf$out_id[r], xy[r, ], FALSE))
}))
arms$bearing <- (atan2(arms$bx - arms$nx, arms$by - arms$ny) * 180 / pi) %% 360
arms$order <- seg$order[match(arms$seg_id, seg$seg_id)]
arms$src   <- seg$src[match(arms$seg_id, seg$seg_id)]

# ---- the last junction: the Kettle and the Columbia --------------------------------------------------------------------
# The Columbia is not part of this network, so its two arms (upstream and downstream) take their bearing from the 3DHP
# Columbia lines that touch the mouth and carry no order. Stored separately so the maps can draw it on its own terms.
mxy <- key_xy(mouth_node)
f3 <- input("MC26_3DHP", "USGS 3DHP flowlines for the region (GeoPackage with a flowline layer)")
crs3 <- st_crs(st_read(f3, query = "select * from flowline limit 1", quiet = TRUE))
near_mouth <- st_transform(st_buffer(st_sfc(st_point(mxy), crs = 3005), 2000), crs3)
col <- st_read(f3, "flowline", wkt_filter = st_as_text(near_mouth), quiet = TRUE)
col <- st_transform(st_cast(st_zm(col[col$gnisidlabel %in% "Columbia River", ]), "LINESTRING", warn = FALSE), 3005)
col_xy <- lapply(st_geometry(col), function(l) unclass(l)[, 1:2, drop = FALSE])
ce <- line_ends(col)
at_mouth <- function(x, y) sqrt((x - mxy[1])^2 + (y - mxy[2])^2) < 1
bearing_to <- function(p) (atan2(p[1] - mxy[1], p[2] - mxy[2]) * 180 / pi) %% 360
col_in  <- which(at_mouth(ce[, 3], ce[, 4]))                         # Columbia lines ending at the mouth (upstream arm)
col_out <- which(at_mouth(ce[, 1], ce[, 2]))                         # Columbia lines starting at the mouth (downstream arm)
inflow  <- into[[mouth_node]]                                        # the Kettle, plus anything else arriving at the same node
mouth <- data.frame(
  arm = c(ifelse(seg$name[inflow] %in% "Kettle River", "kettle", "inflow"), rep("columbia_in", length(col_in)), rep("columbia_out", length(col_out))),
  seg_id = c(seg$seg_id[inflow], rep(NA, length(col_in) + length(col_out))),
  bearing = c(vapply(seg$seg_id[inflow], function(id) bearing_to(point_along(lines_xy[[id]], D_BEAR, TRUE)), numeric(1), USE.NAMES = FALSE),
              vapply(col_in,  function(k) bearing_to(point_along(col_xy[[k]], D_BEAR, TRUE)),  numeric(1)),
              vapply(col_out, function(k) bearing_to(point_along(col_xy[[k]], D_BEAR, FALSE)), numeric(1))),
  order = c(seg$order[inflow], rep(NA, length(col_in) + length(col_out))),
  nx = mxy[1], ny = mxy[2])
cat("mouth arms:\n"); print(mouth, row.names = FALSE)
stopifnot(length(col_in) >= 1, length(col_out) >= 1, any(mouth$arm == "kettle"))

write.csv(arms, file.path(DATA_DIR, paste0("arms3dhp", TAG, ".csv")), row.names = FALSE)
write.csv(joins, file.path(DATA_DIR, paste0("border_joins3dhp", TAG, ".csv")), row.names = FALSE)
write.csv(mouth, file.path(DATA_DIR, paste0("mouth3dhp", TAG, ".csv")), row.names = FALSE)
st_write(seg, out, "segments", quiet = TRUE)
st_write(cf, out, "confluences", quiet = TRUE)
cat("wrote", out, "and arms3dhp", TAG, ".csv:", nrow(arms), "arms\n", sep = "")
