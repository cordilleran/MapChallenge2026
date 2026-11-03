# Shared configuration for the Day 2 R scripts (sourced first by every script).
# Inputs and constants only (rule 2). Folders and inputs come from environment
# variables; nothing machine-specific lives in the repo.
if (!exists(".here") || is.na(.here)) {
  stop("Run the scripts with Rscript, not by source() in a session.", call. = FALSE)
}
ROOT <- normalizePath(file.path(.here, "..", ".."), mustWork = FALSE)
OUT_DIR <- file.path(ROOT, "day-02", "out")   # full-resolution maps (PNG local, PDF published)

# The month's shared look: PALETTE, FONT, DISPLAY_CRS (UTM 11N), PT (rule 12)
source(file.path(ROOT, "shared", "R", "look.R"))

# Path of a required input, read from the environment variable `var`.
read_input <- function(var, what) {
  v <- Sys.getenv(var, "")
  if (!nzchar(v)) stop("Set ", var, ": ", what, call. = FALSE)
  path.expand(v)
}
DATA_DIR <- read_input("MC26_DAY02_DATA", "working folder for Day 2 derived files, outside repo")
dir.create(DATA_DIR, FALSE, TRUE)
dir.create(OUT_DIR, FALSE, TRUE)

# FWA watershed code of the Granby River; every line in the basin starts with it
BASIN_CODE <- Sys.getenv("MC26_BASIN_CODE", "300-571168-245886")
MAIN_STEM  <- Sys.getenv("MC26_MAIN_STEM", "Granby River")   # GNIS name of the reported river
WINDOW_M <- as.numeric(Sys.getenv("MC26_WINDOW", "2000"))   # m of channel per sinuosity window
# FWA edge types kept as channel: single-line main flow, and the centreline of
# double-line rivers (the lower Granby)
CHANNEL_TYPES <- c(1000L, 1250L)
SEARCH_M <- 30   # elevation at a window end: lowest DEM cell within this distance (one cell)
MEASURE_CRS <- 3005   # BC Albers: all measuring (lengths, chords) happens here
