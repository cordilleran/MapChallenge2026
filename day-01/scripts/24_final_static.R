#!/usr/bin/env Rscript
# Day 1 step 24: final static map, Letter portrait, with title, glyph key, length scale, data credits and AI disclosure.
# One run per variant: MC26_VARIANT=strahler (arm length 0.78*sqrt(order) mm) or shreve (0.8*magnitude^k mm, k = ln4/ln(max)).
# In: network3dhp<TAG>.gpkg (confluences), arms3dhp<TAG>_mag.csv (TAG from config.R, default _a1).  Out: out/day01_final_<variant>.png (300 dpi) and .pdf (vector).
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(ggplot2); library(dplyr); library(sf)})
DATA <- DATA_DIR; OUT <- OUT_DIR
VAR <- Sys.getenv("MC26_VARIANT", "strahler"); stopifnot(VAR %in% c("strahler", "shreve"))
arms <- read.csv(file.path(DATA, paste0("arms3dhp", TAG, "_mag.csv"))); cf <- st_read(file.path(DATA, paste0("network3dhp", TAG, ".gpkg")), "confluences", quiet = TRUE)
cf$conf <- seq_len(nrow(cf)); arms <- arms[arms$conf %in% cf$conf[!cf$braid], ]            # braid re-joins are channels meeting themselves, not junctions: same set as the Leaflet map
W <- 215.9; H <- 279.4; MG <- 12                                                   # Letter, mm
xr <- range(arms$nx); yr <- range(arms$ny)
m_per_mm <- max(diff(xr) / (W - 2 * MG), diff(yr) / (H - 2 * MG - 52))             # leaves 52 mm for header and footer
MMAX <- max(arms$mag, na.rm = TRUE); K <- log(4) / log(MMAX)
Lmm <- function(o, m) if (VAR == "strahler") 0.78 * sqrt(o) else 0.8 * m^K
arms$len_m <- Lmm(arms$order, arms$mag) * m_per_mm
arms$x2 <- arms$nx + arms$len_m * sin(arms$bearing * pi / 180); arms$y2 <- arms$ny + arms$len_m * cos(arms$bearing * pi / 180)
nodes <- cf |> st_drop_geometry() |> mutate(x = st_coordinates(cf)[, 1], y = st_coordinates(cf)[, 2]) |> filter(order_changes, !braid)
# page frame in map units: x from the left edge, y from the top edge, both in mm
x0 <- mean(xr) - W / 2 * m_per_mm
y_top_page <- max(yr) + (MG + 30) * m_per_mm                                       # 30 mm of header above the northernmost junction
PX <- function(mm) x0 + mm * m_per_mm; PY <- function(mm) y_top_page - mm * m_per_mm
bg <- "#0c1822"; ink <- "#e9f1f5"; blue <- "#7fb7d6"; amber <- "#ffb454"; mute <- "#8aa0ae"; pt <- 1 / .pt
tx <- function(x, y, label, size, col = ink, fam = "serif", face = "plain", hjust = 0, ...) annotate("text", x = PX(x), y = PY(y), label = label, size = size * pt, colour = col, family = fam, fontface = face, hjust = hjust, vjust = 1, lineheight = 1.15, ...)
title <- "Every junction on the Kettle River"
desc <- if (VAR == "strahler") {
  "Each point is a stream junction, from the headwaters in British Columbia\nto the Columbia River in Washington. An arm runs up each joining stream\nand one down the outflow. Arm length grows with Strahler order, which\nrises by one only where two streams of equal order meet."
} else {
  "Each point is a stream junction, from the headwaters in British Columbia\nto the Columbia River in Washington. An arm runs up each joining stream\nand one down the outflow. Arm length grows with Shreve magnitude, the\nnumber of headwater streams upstream (1 to %s)."
}
if (VAR == "shreve") desc <- sprintf(desc, format(round(MMAX), big.mark = ","))
# glyph key, lower left: an enlarged example junction (two order-3 inflows make an order 4) and the arm-length scale at actual size
kx <- 14; ky <- H - 76; ZOOM <- 4                                                 # key block top-left (page mm); example drawn 4 times larger
Lk <- Lmm(3, 11) * ZOOM; Lo <- Lmm(4, 22) * ZOOM;     # example: two inflows of magnitude 11 give an outflow of magnitude 22
 j <- c(kx + 13, ky + 14); ang <- 32 * pi / 180
seg_in <- data.frame(x = PX(j[1]), y = PY(j[2]), xe = PX(j[1] + c(-1, 1) * Lk * sin(ang)), ye = PY(j[2] - Lk * cos(ang)))
seg_out <- data.frame(x = PX(j[1]), y = PY(j[2]), xe = PX(j[1]), ye = PY(j[2] + Lo))
scale_vals <- if (VAR == "strahler") c(1, 2, 4, 8) else c(1, 10, 100, 1000, 10000)
scale_len <- if (VAR == "strahler") Lmm(scale_vals, NA) else Lmm(NA, scale_vals)
scale_lab <- if (VAR == "strahler") paste("order", scale_vals) else paste(format(scale_vals, big.mark = ","), ifelse(scale_vals == 1, "source", "sources"))
p <- ggplot() +
  geom_segment(data = arms |> filter(arm == "in"), aes(nx, ny, xend = x2, yend = y2), colour = blue, linewidth = .2, lineend = "round", alpha = .85) +
  geom_segment(data = arms |> filter(arm == "out"), aes(nx, ny, xend = x2, yend = y2), colour = ink, linewidth = .2, lineend = "round") +
  geom_point(data = nodes, aes(x, y), colour = amber, size = .22) +
  tx(MG + 2, MG + 4, title, 17) + tx(MG + 2, MG + 14, "DAY 1  ·  POINTS  ·  #30DAYMAPCHALLENGE", 6, amber, "mono") + tx(MG + 2, MG + 21, desc, 6.2, mute) +
  geom_segment(data = seg_in, aes(x, y, xend = xe, yend = ye), colour = blue, linewidth = .5, lineend = "round") +
  geom_segment(data = seg_out, aes(x, y, xend = xe, yend = ye), colour = ink, linewidth = .5, lineend = "round") +
  annotate("point", x = PX(j[1]), y = PY(j[2]), colour = amber, size = 1.3) +
  tx(j[1] + 10, j[2] - Lk * cos(ang) - 1, "joining streams", 5, blue, "mono") +
  tx(j[1] + 4, j[2] - 2.2, "junction", 5, ink, "mono") + tx(j[1] + 4, j[2] + 2, "amber: Strahler order rises", 5, amber, "mono") +
  tx(j[1] + 3, j[2] + 7.2, "outflow", 5, ink, "mono") +
  tx(kx, ky + 27, "ARM LENGTH, ACTUAL SIZE (mm)", 4.6, mute, "mono") + tx(kx, ky + 31.2, "(example above drawn 4x larger)", 4.2, mute, "mono")
for (i in seq_along(scale_len)) { yy <- ky + 37 + 4.3 * (i - 1)
  p <- p + annotate("segment", x = PX(kx + 1), xend = PX(kx + 1 + scale_len[i]), y = PY(yy), yend = PY(yy), colour = ink, linewidth = .5, lineend = "round") +
    tx(kx + 8, yy - 1.8, sprintf("%s: %.1f", scale_lab[i], scale_len[i]), 4.8, mute, "mono") }
credit <- "Data: BC Freshwater Atlas, Province of British Columbia (contains information licensed under the Open Government Licence - British Columbia); USGS 3D Hydrography Program.\nUS channels under 1 km² of upstream area omitted. CC BY 4.0, Graham Watt. Made in R and GRASS by Claude Code (Anthropic) from Graham Watt's design;\ndirected, run and reviewed by Graham Watt. github.com/cordilleran/MapChallenge2026"
p <- p + tx(MG + 2, H - 14, credit, 4.6, mute, "sans") +
  coord_equal(xlim = c(PX(0), PX(W)), ylim = c(PY(H), PY(0)), expand = FALSE, clip = "off") + theme_void() +
  theme(plot.background = element_rect(fill = bg, colour = NA), plot.margin = margin(0, 0, 0, 0))
f <- file.path(OUT, paste0("day01_final_", VAR))
ggsave(paste0(f, ".png"), p, width = W / 25.4, height = H / 25.4, dpi = 300, bg = bg, device = ragg::agg_png)
ggsave(paste0(f, ".pdf"), p, width = W / 25.4, height = H / 25.4, bg = bg, device = cairo_pdf)
cat("wrote", f, ".png and .pdf; m per mm:", round(m_per_mm), " k:", round(K, 3), "\n")
