# Upstream area helpers shared by step 25 (the map's readout) and the 25a check.
# Sourced after config.R; needs terra and igraph loaded.

# Largest DEM flow accumulation within 60 m of each point, in km2. The DEM channel and the mapped line are not always in
# the same 30 m cell, so a 5 x 5 window around the point picks up the channel.
area_near <- function(acc, x, y, reach = 60, cell = 30, cell_m2 = 900) {   # cell_m2: nominal 30 m cell, as in the other steps
  nb <- expand.grid(dx = seq(-reach, reach, cell), dy = seq(-reach, reach, cell))
  cells <- sapply(seq_len(nrow(nb)), function(k) terra::extract(acc, cbind(x + nb$dx[k], y + nb$dy[k]))[, 1])
  apply(cells, 1, function(v) if (all(is.na(v))) NA else max(v, na.rm = TRUE)) * cell_m2 / 1e6
}

# Row in `cf` of the next junction downstream of each junction (NA at the mouth), found by walking down the outflow segments.
next_junction <- function(cf, seg) {
  seg_to <- setNames(seg$to_key, seg$seg_id); seg_from <- split(seg$seg_id, seg$from_key)
  vapply(seq_len(nrow(cf)), function(r) {
    k <- seg_to[[cf$out_id[r]]]
    repeat {
      j <- match(k, cf$key); if (!is.na(j)) return(j)
      out <- seg_from[[k]]; if (is.null(out)) return(NA_integer_)
      k <- seg_to[[out[1]]]
    }
  }, integer(1))
}

# Raise each junction's area to at least the largest area upstream (area cannot shrink downstream). Returns the new areas
# and how many junctions were raised (each counted once, however many of its inflows raised it).
raise_downstream <- function(area, nxt) {
  jg <- igraph::graph_from_data_frame(data.frame(from = which(!is.na(nxt)), to = na.omit(nxt)), directed = TRUE,
                                      vertices = data.frame(name = seq_along(area)))
  area0 <- area
  for (v in as.integer(names(igraph::topo_sort(jg, mode = "out")))) {
    d <- nxt[v]
    if (!is.na(d) && !is.na(area[v]) && (is.na(area[d]) || area[d] < area[v])) area[d] <- area[v]
  }
  list(area = area, raised = sum(!is.na(area) & (is.na(area0) | area > area0)))
}
