#!/usr/bin/env Rscript
# Day 7 step 08: the road notes of the collar, in the custom of the 1958 USGS sheets
# ("HIBBING 33 MI."): where a numbered road leaves the frame, the distance along that same
# road to the first town beyond the edge (D325).
#   - roads: OSM ways with a US, MN or WI route number (interstates and county roads left
#     out; the interstates were not built here in 1958), in a box 1 degree round the frame;
#   - towns: OSM place = city, town or village, outside the frame, within TOWN_NEAR_M of that road;
#   - distance: shortest path along that route's own ways, outside the frame, from the
#     crossing to the town. Today's roads, so a 1958 alignment may differ by a mile or two.
# In : $MC26_DAY07_DATA/raw/osm_roads_beyond.gpkg, osm_towns_beyond.gpkg (step 01),
#      derived/day07.gpkg (frame)
# Out: derived/roads_out.csv (one row per note: route, edge, x, y, town, km, miles)
#
# Layout: main() first, the helpers follow; main() is called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({
  library(dplyr)
  library(purrr)
  library(sf)
})

ROUTE_PATTERN <- "^(US|MN|WI) [0-9]+$"
TOWN_NEAR_M <- 1500       # a town is on the road if its point is this close to it
SAME_CROSSING_M <- 3000   # the two carriageways of one road leave the frame as one crossing
TOWN_REACH_M <- 80000     # a city or town this close along the road is named before any village
MAX_MILES <- 50           # longer notes are left out
METRES_PER_MILE <- 1609.344
OUT <- file.path(DERIVED_DIR, "roads_out.csv")

main <- function() {
  frame <- st_read(file.path(DERIVED_DIR, "day07.gpkg"), "frame", quiet = TRUE) |> st_geometry()
  roads <- read_routes()
  towns <- st_read(file.path(RAW_DIR, "osm_towns_beyond.gpkg"), quiet = TRUE) |>
    st_transform(DISPLAY_CRS)
  towns <- towns[lengths(st_intersects(towns, frame)) == 0, ]
  notes <- unique(roads$route) |>
    map(\(route) route_notes(filter(roads, route == !!route), towns, frame)) |>
    bind_rows() |>
    dedupe_notes()
  utils::write.csv(notes, OUT, row.names = FALSE)
  message("Step 08: ", nrow(notes), " road notes; ", OUT)
}

# One row per way and route number ("US 169;MN 73" is two routes), in UTM
read_routes <- function() {
  st_read(file.path(RAW_DIR, "osm_roads_beyond.gpkg"), quiet = TRUE) |>
    st_transform(DISPLAY_CRS) |>
    mutate(route = sub('.*"ref"=>"([^"]*)".*', "\\1", other_tags)) |>
    mutate(route = strsplit(route, ";\\s*")) |>
    tidyr::unnest(route) |>
    filter(grepl(ROUTE_PATTERN, route)) |>
    st_as_sf() |>
    select(osm_id, route)
}

# Where one route leaves the frame, and the first town along it beyond each crossing
route_notes <- function(ways, towns, frame) {
  edge <- st_cast(frame, "MULTILINESTRING")
  crossings <- st_intersection(st_union(ways), edge) |> st_cast("POINT") |> merge_close(SAME_CROSSING_M)
  outside <- st_difference(st_union(ways), frame)
  if (length(crossings) == 0 || st_is_empty(outside)) return(NULL)
  on_road <- towns[st_is_within_distance(towns, outside, TOWN_NEAR_M, sparse = FALSE)[, 1], ]
  if (nrow(on_road) == 0) return(NULL)
  g <- road_graph(outside)
  from <- nearest_node(g$xy, st_coordinates(crossings))
  to <- nearest_node(g$xy, st_coordinates(on_road))
  targets <- unique(to)   # two towns can snap to one node; igraph wants each target once
  d <- igraph::distances(g$graph, v = unique(from), to = targets,
                         weights = igraph::E(g$graph)$len)[match(from, unique(from)), match(to, targets), drop = FALSE]
  map(seq_along(from), \(i) {
    # the custom names towns of note: the nearest city or town within reach, else the nearest village
    rank <- ifelse(on_road$place %in% c("city", "town") & d[i, ] <= TOWN_REACH_M, d[i, ], d[i, ] + 1e7)
    j <- which.min(rank)
    if (length(j) == 0 || !is.finite(d[i, j])) return(NULL)
    xy <- st_coordinates(crossings[i])
    tibble::tibble(route = ways$route[1], edge = which_edge(xy, st_bbox(frame)),
                   x = xy[1], y = xy[2], town = sub(";", " \u00b7 ", on_road$name[j]),
                   km = round(d[i, j] / 1000, 1), miles = round(d[i, j] / METRES_PER_MILE))
  }) |> bind_rows()
}

# Points closer than `dist` become one point (their mean)
merge_close <- function(pts, dist) {
  if (length(pts) < 2) return(pts)
  groups <- igraph::components(igraph::graph_from_adjacency_matrix(
    st_is_within_distance(pts, pts, dist, sparse = FALSE), mode = "undirected"))$membership
  xy <- st_coordinates(pts)
  st_sfc(map(sort(unique(groups)), \(k) st_point(colMeans(xy[groups == k, , drop = FALSE]))),
         crs = st_crs(pts))
}

# A graph of the road: every vertex a node (OSM ways share nodes where they join), every
# segment an edge weighted by its length
road_graph <- function(lines) {
  parts <- st_cast(st_cast(lines, "MULTILINESTRING"), "LINESTRING")
  seg <- map(seq_along(parts), \(i) {
    xy <- round(st_coordinates(parts[i])[, 1:2], 1)
    if (nrow(xy) < 2) return(NULL)
    cbind(xy[-nrow(xy), , drop = FALSE], xy[-1, , drop = FALSE])
  }) |> reduce(rbind)
  key <- \(x, y) paste(x, y)
  nodes <- unique(rbind(seg[, 1:2], seg[, 3:4]))
  id <- setNames(seq_len(nrow(nodes)), key(nodes[, 1], nodes[, 2]))
  edges <- cbind(id[key(seg[, 1], seg[, 2])], id[key(seg[, 3], seg[, 4])])
  graph <- igraph::graph_from_edgelist(edges, directed = FALSE)
  igraph::E(graph)$len <- sqrt((seg[, 1] - seg[, 3])^2 + (seg[, 2] - seg[, 4])^2)
  list(graph = graph, xy = nodes)
}

nearest_node <- function(nodes, xy) {
  apply(xy[, 1:2, drop = FALSE], 1, \(p) which.min((nodes[, 1] - p[1])^2 + (nodes[, 2] - p[2])^2))
}

which_edge <- function(xy, bb) {
  d <- c(left = xy[1] - bb[["xmin"]], right = bb[["xmax"]] - xy[1],
         bottom = xy[2] - bb[["ymin"]], top = bb[["ymax"]] - xy[2])
  names(which.min(abs(d)))
}

# One note per route and town (a road that crosses the edge twice keeps its shorter note)
dedupe_notes <- function(notes) {
  notes |>
    filter(miles <= MAX_MILES) |>
    arrange(km) |>
    distinct(route, town, .keep_all = TRUE)
}

main()
