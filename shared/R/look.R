# The month's shared look: colours, fonts and the display projection (rule 12).
# Sourced by each day's config.R; site/styles.css uses the same colours.

PALETTE <- c(
  ground = "#0c1822",   # page ground, deep river night
  ink    = "#e9f1f5",   # main text and strong lines
  mute   = "#8aa0ae",   # secondary text and quiet lines
  blue   = "#7fb7d6",   # water
  amber  = "#ffb454"    # the accent (may change; every function takes it as an argument)
)

# Named faces, so the PNG (ragg) and the PDF (cairo) set the same type;
# cairo_pdf maps the generic "serif" to Times.
FONT <- c(serif = "Noto Serif", sans = "Noto Sans", mono = "DejaVu Sans Mono")

# Maps are drawn in NAD83 / UTM zone 11N: the basins so far sit between 117 and 120 deg W,
# where true north is within about 2 deg of grid north.
# Data stay in their source CRS for measuring; only drawing is reprojected.
DISPLAY_CRS <- 26911

PT <- 1 / ggplot2::.pt   # multiply a size in points by PT to get ggplot text size (mm)
