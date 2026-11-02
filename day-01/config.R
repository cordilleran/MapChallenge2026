# Shared configuration for the Day 1 R scripts (sourced first by every script).
# Nothing machine-specific lives in the repo: folders and external inputs come from environment variables.
# Each script sets `.here` (its own folder) before sourcing this file, so scripts can be run from any directory.
if (!exists(".here") || is.na(.here)) stop("Run the scripts with Rscript (they find config.R from their own location), not by source() in a session.", call. = FALSE)
ROOT      <- normalizePath(file.path(.here, "..", ".."), mustWork = FALSE)   # repo root
OUT_DIR   <- file.path(ROOT, "day-01", "out")                                 # finished maps (PNG, PDF)
SITE_DATA <- file.path(ROOT, "site", "data")                                  # data file read by the Leaflet map
input <- function(var, what) {                                               # a required folder, file or setting from an environment variable
  v <- Sys.getenv(var, "")
  if (!nzchar(v)) stop("Set ", var, ": ", what, call. = FALSE)
  path.expand(v)
}
DATA_DIR <- input("MC26_DATA", "working folder for intermediate and derived Day 1 files, outside the repo")
dir.create(DATA_DIR, FALSE, TRUE)
TAG     <- Sys.getenv("MC26_TAG", "_a1")                    # file-name suffix of the thinned network; set MC26_TAG="" for the unthinned one
MINAREA <- as.numeric(Sys.getenv("MC26_MINAREA", "1"))      # km2 of upstream area under which a 3DHP headwater branch is dropped (0 = off)
