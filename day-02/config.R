# Shared configuration for the Day 2 R scripts (sourced first by every script).
# Folders and inputs come from environment variables; nothing machine-specific lives in the repo.
if (!exists(".here") || is.na(.here)) stop("Run the scripts with Rscript, not by source() in a session.", call. = FALSE)
ROOT    <- normalizePath(file.path(.here, "..", ".."), mustWork = FALSE)    # repo root
OUT_DIR <- file.path(ROOT, "day-02", "out")                                  # full-resolution maps (PNG kept local, PDF published)
input <- function(var, what) {
  v <- Sys.getenv(var, "")
  if (!nzchar(v)) stop("Set ", var, ": ", what, call. = FALSE)
  path.expand(v)
}
DATA_DIR <- input("MC26_DAY02_DATA", "working folder for Day 2 derived files, outside the repo")
FWA      <- input("MC26_FWA", "BC Freshwater Atlas stream network for the Kettle watershed group (KETL)")
DEM      <- input("MC26_DEM_TIF", "a 30 m DEM GeoTIFF in BC Albers (EPSG:3005) covering the basin")
dir.create(DATA_DIR, FALSE, TRUE); dir.create(OUT_DIR, FALSE, TRUE)

BASIN_CODE <- Sys.getenv("MC26_BASIN_CODE", "300-571168-245886")   # FWA watershed code of the Granby River; every line in the basin starts with it
WINDOW     <- as.numeric(Sys.getenv("MC26_WINDOW", "2000"))         # m of channel per sinuosity window
CHANNEL    <- c(1000L, 1250L)   # FWA edge types kept as channel: single-line main flow, and the centreline of double-line rivers (the lower Granby)

# Day 1's look, so the month reads as one set (site/styles.css uses the same values)
GROUND <- "#0c1822"; INK <- "#e9f1f5"; MUTE <- "#8aa0ae"; BLUE <- "#7fb7d6"; AMBER <- "#ffb454"
FONT   <- c(serif = "Noto Serif", sans = "Noto Sans", mono = "DejaVu Sans Mono")
