#!/usr/bin/env Rscript
# Day 1 (Points) step 1: US part of the Kettle River network, from USGS NLDI / NHDPlus V2.
# Kettle mouth = NHDPlus V2 comid 23040709 (order 5, 10,934 km2), last reach before the Columbia.
# Writes: $DATA/us_nhdplus_v2.gpkg  (EPSG:3005, all upstream flowlines with EROM mean annual flow)
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(nhdplusTools); library(sf)})
sf_use_s2(FALSE)
DATA <- DATA_DIR
dir.create(DATA, showWarnings = FALSE, recursive = TRUE)
out <- file.path(path.expand(DATA), "us_nhdplus_v2.gpkg")
if (file.exists(out)) stop("exists, not overwriting: ", out)

mouth <- 23040709L
ut <- navigate_nldi(list(featureSource = "comid", featureID = as.character(mouth)),
                    mode = "UT", data_source = "flowlines", distance_km = 999)$UT_flowlines
ids <- unique(as.integer(c(mouth, ut$nhdplus_comid)))
cat("upstream comids:", length(ids), "\n")
chunks <- split(ids, ceiling(seq_along(ids) / 100))
fl <- do.call(rbind, lapply(chunks, function(ch)
  get_nhdplus(comid = ch, realization = "flowline", t_srs = 3005)))
keep <- c("comid", "gnis_name", "streamorde", "streamleve", "hydroseq", "levelpathi", "dnhydroseq",
          "fromnode", "tonode", "divergence", "areasqkm", "totdasqkm", "lengthkm",
          "qa_ma", "maxelevsmo", "minelevsmo", "lakefract")
fl <- fl[, intersect(keep, names(fl))]
st_write(fl, out, "us_flowlines", quiet = TRUE)
cat("wrote", nrow(fl), "flowlines to", out, "\n")
