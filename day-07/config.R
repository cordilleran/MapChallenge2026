# Shared configuration for the Day 7 R scripts (sourced first by every script).
# Inputs and constants only (rule 2). Folders come from environment variables;
# nothing machine-specific lives in the repo.
if (!exists(".here") || is.na(.here)) {
  stop("Run the scripts with Rscript, not by source() in a session.", call. = FALSE)
}
ROOT <- normalizePath(file.path(.here, "..", ".."), mustWork = FALSE)
DAY_DIR <- file.path(ROOT, "day-07")
OUT_DIR <- file.path(DAY_DIR, "out")      # full-resolution maps, kept local; the site shows the PDF as tiles
FONT_DIR <- file.path(DAY_DIR, "fonts")   # Special Elite (Apache 2.0); Caveat, EB Garamond, Jost (OFL)

# Stop with a message rather than install anything into the reader's library (D308).
needed <- c("sf", "terra", "elevatr", "httr2", "jsonlite", "dplyr", "purrr",
            "tidyr", "ggplot2", "showtext", "sysfonts", "systemfonts", "magick", "igraph",
            "units", "tibble")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing) > 0) {
  stop("Install these R packages first: ", paste(missing, collapse = ", "), call. = FALSE)
}

read_input <- function(var, what) {
  v <- Sys.getenv(var, "")
  if (!nzchar(v)) stop("Set ", var, ": ", what, call. = FALSE)
  path.expand(v)
}
DATA_DIR <- read_input("MC26_DAY07_DATA", "working folder for Day 7 data, outside the repo")
RAW_DIR <- file.path(DATA_DIR, "raw")       # fetched as-is, never edited
DERIVED_DIR <- file.path(DATA_DIR, "derived")
walk_dirs <- c(RAW_DIR, DERIVED_DIR, OUT_DIR)
invisible(lapply(walk_dirs, dir.create, showWarnings = FALSE, recursive = TRUE))

# Optional: a local copy of the NOAA NCEI Lake Superior grid (superior_lld.tif).
# If unset, step 01 downloads the archive (about 165 MB unpacked) into RAW_DIR.
NCEI_TIF <- Sys.getenv("MC26_NCEI_SUPERIOR", "")
if (!nzchar(NCEI_TIF)) NCEI_TIF <- file.path(RAW_DIR, "superior_lld", "superior_lld.tif")
NCEI_URL <- "https://www.ngdc.noaa.gov/mgg/greatlakes/superior/data/geotiff/superior_lld.geotiff.tar.gz"

# The frame: Duluth to Hibbing, Argon's box widened so Hibbing and Two Harbors sit inside (D321).
FRAME_LL <- c(xmin = -93.30, ymin = 46.40, xmax = -91.30, ymax = 47.72)
FETCH_PAD_DEG <- 0.08    # fetch a little wider so the projected frame has no empty corners
DISPLAY_CRS <- 26915     # NAD83 / UTM 15N, the zone this place lies in (D296)

DEM_ZOOM <- 10           # AWS Terrain Tiles zoom: about 100 m cells here (D298)
LAKE_LEVEL_M <- 183.2    # Lake Superior, IGLD 1985; NCEI values are relative to it

WIND_MONTH <- c(start = "1962-04-01", end = "1962-04-30")   # the month of the song (D301)
WIND_STEP_DEG <- 0.25    # ERA5 grid spacing
DOVE_TAXON <- "Zenaida macroura"                 # Mourning Dove (D300)
DOVE_LICENCES <- c("CC0_1_0", "CC_BY_4_0")
DOVE_MONTH <- 4L                                 # April, any year: the song's month (D315)
DOVE_MAX_UNCERTAINTY_M <- 1000

# Named places, looked up in OSM by exact name (step 01), never typed in as coordinates.
# The Hill of Three Waters is not looked up: step 02 computes it where the three
# drainages meet.
OSM_PLACES <- c(
  duluth          = "Duluth",
  hibbing         = "Hibbing",
  minnesota_point = "Minnesota Point",
  memorial        = "Clayton-Jackson-McGhie Memorial"   # drawn only in variant B (D303)
)

# The 1963 palette (D305)
INK <- c(
  paper   = "#EFECE6",   # aged sleeve stock
  charcoal = "#22201E",  # darkroom ink, never pure black
  graphite = "#5A554C",  # wind, state lines in the location diagram
  suede   = "#6E5340",   # the jacket: the 1958 brown plate (contours)
  rust    = "#8B4513",   # the pits, the accent
  dove    = "#FAF8F5",   # dove points, label halos
  # Watercolour washes in the 1958 sheets' own hues, muted (D326, GW 11-16)
  woods   = "#93A86E",   # the sheets' woodland green
  water   = "#8FB0BC",   # the sheets' water blue, Lake Superior included
  stream  = "#3F6577"    # the sheets' blue line ink: streams, shorelines, marsh tufts
)

# Magnetic declination printed on the four 1958 sheets, for 1955, at the centre of each
# sheet's west and east edge, with the mean annual change (read from the scans, D325).
# 03_map.R interpolates it to April 1962 at the centre of the frame's west and east edges.
DECLINATION_1955 <- data.frame(
  sheet      = c("Duluth", "Hibbing", "Ashland", "Two Harbors"),
  lat        = c(46.5, 47.5, 46.5, 47.5),
  lon_west   = c(-94, -94, -92, -92),
  west_deg   = c(6 + 0 / 60, 5 + 45 / 60, 4 + 0 / 60, 3 + 45 / 60),
  east_deg   = c(4 + 0 / 60, 3 + 45 / 60, 2 + 15 / 60, 1 + 45 / 60),
  change_min = c(-2, -3, -2, -3)     # minutes a year; negative = westerly
)
DECLINATION_EPOCH <- 1955
DECLINATION_AT <- 1962 + 3.5 / 12    # mid-April 1962
