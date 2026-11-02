# Shared helpers for the area-chain construction of local units, used by 12_make_units_a16.R and the exploration scripts 11 and 11b.
# load_net reads a reach table and its unit raster; unit_A builds units (larger branch continues, smaller branch starts a unit
# only if it drains at least A km2); unit_S is the Strahler-stream variant; score compares units with the official BC 1:50k units.
suppressMessages({library(terra); library(sf); library(dplyr); library(igraph)})
D <- DATA_DIR
OFF <- st_read(input("MC26_BC50K", "BC Watershed Atlas 1:50k watersheds, Kettle region (GeoPackage, BC Data Catalogue)"), quiet=TRUE)
OFF <- OFF[grepl("^320-", OFF$NEW_WATERSHED_CODE), ]; OFF <- st_transform(OFF, 3005)
oid <- vect(OFF); oid$id <- seq_len(nrow(OFF))

load_net <- function(NET) {
  rc <- read.csv(file.path(D, sprintf("reaches_t%d.csv", NET)))
  ras <- rast(file.path(D, sprintf("units_t%dkm2.tif", NET)))
  fr <- as.data.frame(freq(ras)); loc <- setNames(fr$count*900/1e6, fr$value)
  rc$a_loc <- as.numeric(loc[as.character(rc$stream)]); rc$a_loc[is.na(rc$a_loc)] <- 0
  rc$next_stream[!(rc$next_stream %in% rc$stream)] <- NA
  e <- rc[!is.na(rc$next_stream), c("stream","next_stream")]
  g <- graph_from_data_frame(e, directed=TRUE, vertices=data.frame(name=rc$stream))
  topo <- as.numeric(names(topo_sort(g, mode="out")))      # upstream first
  idx <- setNames(seq_len(nrow(rc)), rc$stream)
  cum <- setNames(rc$a_loc, rc$stream)
  for (s in topo) { n <- rc$next_stream[idx[as.character(s)]]; if (!is.na(n)) cum[as.character(n)] <- cum[as.character(n)] + cum[as.character(s)] }
  rc$cumA <- as.numeric(cum[as.character(rc$stream)])
  list(rc=rc, ras=ras, topo=topo, idx=idx)
}
unit_S <- function(nt, N) {
  rc <- nt$rc; u <- setNames(rep(NA_real_, nrow(rc)), rc$stream)
  for (s in rev(nt$topo)) { i <- nt$idx[as.character(s)]; n <- rc$next_stream[i]
    u[as.character(s)] <- if (is.na(n)) s else if (rc$strahler[i] >= N && rc$strahler[i] != rc$strahler[nt$idx[as.character(n)]]) s else u[as.character(n)] }
  u }
unit_A <- function(nt, A) {
  rc <- nt$rc; kids <- split(rc$stream, rc$next_stream)
  u <- setNames(rep(NA_real_, nrow(rc)), rc$stream)
  for (s in rev(nt$topo)) { i <- nt$idx[as.character(s)]; n <- rc$next_stream[i]
    if (is.na(n)) { u[as.character(s)] <- s; next }
    ks <- kids[[as.character(n)]]; main <- ks[which.max(rc$cumA[nt$idx[as.character(ks)]])]
    u[as.character(s)] <- if (s == main || rc$cumA[i] < A) u[as.character(n)] else s }
  u }
.rid_cache <- new.env()                                  # official units rasterized once per raster geometry, not once per score
score <- function(ras, u) {
  r2 <- classify(ras, cbind(as.numeric(names(u)), as.numeric(u)), others=NA)
  key <- paste(c(as.vector(ext(ras)), ncell(ras)), collapse = "_")
  if (is.null(.rid_cache[[key]])) .rid_cache[[key]] <- rasterize(oid, ras, field="id")
  rid <- .rid_cache[[key]]
  df <- data.frame(unit=as.vector(values(r2)), off=as.vector(values(rid))); df <- df[!is.na(df$unit), ]
  ut_all <- as.data.frame(freq(r2)); names(ut_all) <- c("layer","unit","utot"); ut_all <- ut_all[,c("unit","utot")]
  d <- df[!is.na(df$off), ]
  best <- d |> count(off, unit, name="n") |> group_by(off) |> slice_max(n, n=1, with_ties=FALSE) |> ungroup()
  otot <- d |> count(off, name="otot")
  allu <- d |> count(unit, name="in_off") |> left_join(ut_all, by="unit")
  best |> left_join(ut_all, by="unit") |> left_join(otot, by="off") |>
    mutate(iou=n/(utot+otot-n), a_off=OFF$WATERSHED_AREA[off]/1e6, a_der=utot*900/1e6, n_der_in=sum(allu$in_off/allu$utot > 0.5))
}
