#!/usr/bin/env Rscript
# Day 1 step 26: a shaded-relief image for the Leaflet map, made from the same DEM as the network work (step 04).
# Two looks (MC26_RELIEF):
#   superior (default): the land style of the author's Superior Ice Year hillshade (sonify-viz, palette B): cool stone
#                       greys by elevation, 60 % saturation and a 20 % lift toward a winter white, key light from 315
#                       degrees at 45, shadows keeping 62 % of the base colour.
#   dark              : a dark studio relief (sun 315/38) whose shadows sink into the page ground.
# Vertical exaggeration 1.3 on a DEM smoothed over about 120 m, with the shading range narrowed and 25 % blended toward the
# surround grey, so the relief stays behind the glyphs (GW 11-02). Superior used 12 on a flat lake floor. The DEM's rectangular
# edge fades over FEATHER metres into a flat surround (stone grey, or the page ground for the dark look).
# In : $MC26_DATA/dem.tif (EPSG:3005)   Out: site/img/day01_relief.jpg and site/data/day01_relief.js (image bounds)
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(terra); library(sf)})

LOOK     <- Sys.getenv("MC26_RELIEF", "superior"); stopifnot(LOOK %in% c("superior", "dark"))
RES_3857 <- 75                                   # m per pixel in Web Mercator (about 50 m on the ground at 49 N)
VE       <- 1.3                                  # vertical exaggeration (GW 11-02: less, so the relief does not dominate)
SMOOTH   <- 120                                  # m: Gaussian smoothing of the DEM before shading (softens 30 m texture)
SHADE_LO <- 0.74; SHADE_HI <- 1.06               # shadow and light multipliers (Superior used 0.62 and 1.15; muted here)
MUTE     <- 0.25                                 # share blended toward the flat surround grey
FEATHER  <- 15000                                # m (Web Mercator) over which the DEM edge fades into the ground
GROUND   <- c(12, 24, 34) / 255                  # page ground, #0c1822
EDGE_SUP <- c(138, 144, 148) / 255               # flat stone grey around the superior relief (the map page uses the same colour)
hex <- function(h) sapply(c(2, 4, 6), function(i) strtoi(substr(h, i, i + 1), 16L) / 255)

# ---- relief on the DEM grid, then into Web Mercator -------------------------------------------------------------------
dem <- rast(file.path(DATA_DIR, "dem.tif")); crs(dem) <- "EPSG:3005"
dem <- aggregate(dem, 2, mean, na.rm = TRUE)     # 60 m is plenty for a backdrop
dem <- focal(dem, focalMat(dem, SMOOTH / 2, "Gauss"), fun = sum, na.rm = TRUE, na.policy = "omit")
alt <- if (LOOK == "superior") 45 else 38
hs <- shade(terrain(dem * VE, "slope", unit = "radians"), terrain(dem, "aspect", unit = "radians"), angle = alt, direction = 315)
q  <- global(hs, quantile, probs = c(0.02, 0.995), na.rm = TRUE)
hs <- clamp((hs - q[[1]]) / (q[[2]] - q[[1]]), 0, 1)
zq <- global(dem, quantile, probs = c(0.01, 0.99), na.rm = TRUE)
el <- clamp((dem - zq[[1]]) / (zq[[2]] - zq[[1]]), 0, 1)          # 0 = valley floor, 1 = high ground

tmpl <- project(rast(ext(hs), crs = "EPSG:3005", resolution = 60), "EPSG:3857", res = RES_3857)
hs <- project(hs, tmpl, method = "bilinear"); el <- project(el, tmpl, method = "bilinear")
fade <- clamp(distance(ifel(is.na(hs), 1, NA)) / FEATHER, 0, 1)
h <- as.matrix(hs, wide = TRUE); e <- as.matrix(el, wide = TRUE); w <- as.matrix(fade, wide = TRUE)^1.5

# ---- colour -----------------------------------------------------------------------------------------------------------
ramp <- function(v, stops) {                     # v in 0..1 -> one matrix per channel, stops evenly spaced
  cols <- sapply(stops, hex); xs <- seq(0, 1, length.out = length(stops))
  lapply(1:3, function(k) matrix(approx(xs, cols[k, ], xout = pmin(pmax(v, 0), 1))$y, nrow(v)))
}
if (LOOK == "superior") {
  base <- ramp(e, c("#5d6468", "#7f868a", "#a3a9ab", "#d6dadb"))    # LAND_STONE, superior_palette.py
  lum <- 0.2126 * base[[1]] + 0.7152 * base[[2]] + 0.0722 * base[[3]]
  white <- hex("#eef3f6")
  rgb <- lapply(1:3, function(k) {
    v <- lum + 0.6 * (base[[k]] - lum)            # saturation 60 %
    v <- v + 0.2 * (white[k] - v)                 # lift 20 % toward winter white
    v <- v * (SHADE_LO + (SHADE_HI - SHADE_LO) * h)   # shade_mix as palette B, with a narrower range
    v + MUTE * (EDGE_SUP[k] - v)                  # mute toward the surround
  })
} else {
  lit <- c(92, 106, 114) / 255
  rgb <- lapply(1:3, function(k) GROUND[k] + (lit[k] - GROUND[k]) * h^1.1 + 16 / 255 * e)
}
edge_col <- if (LOOK == "superior") EDGE_SUP else GROUND
img <- array(0, c(nrow(h), ncol(h), 3))
for (k in 1:3) {
  v <- edge_col[k] + (rgb[[k]] - edge_col[k]) * w  # fade the DEM edge into a flat surround
  v[is.na(v)] <- edge_col[k]
  img[, , k] <- pmin(pmax(v, 0), 1)
}
f_img <- file.path(ROOT, "site", "img", "day01_relief.jpg")
jpeg::writeJPEG(img, f_img, quality = 0.8)

bb <- as.vector(ext(hs))                         # xmin, xmax, ymin, ymax in EPSG:3857
ll <- st_coordinates(st_transform(st_sfc(st_point(bb[c(1, 3)]), st_point(bb[c(2, 4)]), crs = 3857), 4326))
writeLines(c(sprintf("// Shaded relief behind the Day 1 glyphs (26_relief.R, look '%s'). Made from a 30 m DEM; see THIRD_PARTY.md for its sources.", LOOK),
             sprintf("window.DAY01_RELIEF={url:'img/day01_relief.jpg',look:'%s',edge:'%s',bounds:[[%.5f,%.5f],[%.5f,%.5f]]};", LOOK, rgb(edge_col[1], edge_col[2], edge_col[3]), ll[1, 2], ll[1, 1], ll[2, 2], ll[2, 1])),
           file.path(SITE_DATA, "day01_relief.js"))
cat(sprintf("relief (%s) %d x %d px, %.1f MB\n", LOOK, ncol(h), nrow(h), file.size(f_img) / 1e6))
