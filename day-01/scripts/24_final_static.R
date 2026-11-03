#!/usr/bin/env Rscript
# Day 1 step 24: the finished static map, Letter portrait: title, glyph key, arm-length scale, credits.
# One run per variant: MC26_VARIANT=strahler (arm 0.78 * sqrt(order) mm) or shreve (arm 0.8 * magnitude^K mm, K = ln 4 / ln max).
# In : network3dhp<TAG>.gpkg (confluences), arms3dhp<TAG>_mag.csv, mouth3dhp<TAG>_mag.csv
# Out: out/day01_final_<variant>.png (300 dpi) and .pdf (vector)
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(ggplot2); library(dplyr); library(sf)})
VAR <- Sys.getenv("MC26_VARIANT", "strahler"); stopifnot(VAR %in% c("strahler", "shreve"))

# ---- data ----------------------------------------------------------------------------------------------------------
cf <- st_read(file.path(DATA_DIR, paste0("network3dhp", TAG, ".gpkg")), "confluences", quiet = TRUE); cf$conf <- seq_len(nrow(cf))
arms  <- read.csv(file.path(DATA_DIR, paste0("arms3dhp", TAG, "_mag.csv")))
mouth <- read.csv(file.path(DATA_DIR, paste0("mouth3dhp", TAG, "_mag.csv")))
arms <- arms[arms$conf %in% cf$conf[!cf$braid], ]       # braid re-joins are channels meeting themselves, not junctions (same set as the Leaflet map)
rises <- cf |> filter(order_changes, !braid)

# ---- page geometry: Letter in mm, map units in metres ----------------------------------------------------------------
W <- 215.9; H <- 279.4; MG <- 12
xr <- range(c(arms$nx, mouth$nx)); yr <- range(c(arms$ny, mouth$ny))
m_per_mm <- max(diff(xr) / (W - 2 * MG), diff(yr) / (H - 2 * MG - 52))   # 52 mm kept for header and footer
x0 <- mean(xr) - W / 2 * m_per_mm
y_top <- max(yr) + (MG + 30) * m_per_mm                                  # 30 mm of header above the northernmost junction
PX <- function(mm) x0 + mm * m_per_mm                                    # page mm (from the left) to map x
PY <- function(mm) y_top - mm * m_per_mm                                 # page mm (from the top) to map y

# ---- arm length rule ------------------------------------------------------------------------------------------------
MMAX <- max(arms$mag, na.rm = TRUE); K <- log(4) / log(MMAX)
arm_mm <- function(order, mag) if (VAR == "strahler") 0.78 * sqrt(order) else 0.8 * mag^K
arm_end <- function(d) {                                                 # adds x2, y2: the arm tip in map units
  len <- arm_mm(d$order, d$mag) * m_per_mm
  transform(d, x2 = nx + len * sin(bearing * pi / 180), y2 = ny + len * cos(bearing * pi / 180))
}
arms <- arm_end(arms)

# The last junction: the Kettle arm by the same rule; the Columbia, which is far larger than anything on the page and not
# part of this network, as a dashed pale line 1.6 times the longest arm.
col_len <- 1.6 * arm_mm(8, MMAX) * m_per_mm
is_col <- grepl("^columbia", mouth$arm)
m_kettle <- arm_end(mouth[!is_col, ])                                # the Kettle and any other line arriving at the mouth
m_col <- transform(mouth[is_col, ], x2 = nx + col_len * sin(bearing * pi / 180), y2 = ny + col_len * cos(bearing * pi / 180))

# ---- style ----------------------------------------------------------------------------------------------------------
bg <- "#0c1822"; ink <- "#e9f1f5"; blue <- "#7fb7d6"; amber <- "#ffb454"; mute <- "#8aa0ae"; pt <- 1 / .pt
# Named faces, so the PNG (ragg) and the PDF (cairo) set the same type; cairo_pdf maps the generic "serif" to Times.
FONT <- c(serif = "Noto Serif", sans = "Noto Sans", mono = "DejaVu Sans Mono")
text_at <- function(x, y, label, size, col = ink, fam = "serif", hjust = 0)
  annotate("text", x = PX(x), y = PY(y), label = label, size = size * pt, colour = col, family = FONT[[fam]], hjust = hjust, vjust = 1, lineheight = 1.15)

title <- "Every junction on the Kettle River"
measure <- if (VAR == "strahler") "Strahler order, which\nrises by one only where two streams of equal order meet." else
  sprintf("Shreve magnitude, the\nnumber of headwater streams upstream (1 to %s).", format(round(MMAX), big.mark = ","))
desc <- paste0("Each point is a stream junction, from the headwaters in British Columbia\n",
               "to the Columbia River in Washington. An arm runs up each joining stream\n",
               "and one down the outflow. Arm length grows with ", measure)
credit <- paste0("Data: BC Freshwater Atlas, Province of British Columbia (contains information licensed under the Open Government Licence - British Columbia); ",
                 "USGS 3D Hydrography Program.\n", if (MINAREA > 0) sprintf("US channels under %s km² of upstream area omitted. ", format(MINAREA)) else "", "Map: Graham Watt, CC BY 4.0. ",
                 "Built in R and GRASS GIS with Claude Code (Anthropic). github.com/cordilleran/MapChallenge2026")

# ---- glyph key, lower left: an example junction drawn 4 times larger (two order-3 inflows, magnitude 11 each, make an order 4) ----
kx <- 14; ky <- H - 76; ZOOM <- 4
j <- c(kx + 13, ky + 14); ang <- 32 * pi / 180
L_in <- arm_mm(3, 11) * ZOOM; L_out <- arm_mm(4, 22) * ZOOM
key_in  <- data.frame(x = PX(j[1]), y = PY(j[2]), xe = PX(j[1] + c(-1, 1) * L_in * sin(ang)), ye = PY(j[2] - L_in * cos(ang)))
key_out <- data.frame(x = PX(j[1]), y = PY(j[2]), xe = PX(j[1]), ye = PY(j[2] + L_out))
scale_vals <- if (VAR == "strahler") c(1, 2, 4, 8) else c(1, 10, 100, 1000, 10000)
scale_len  <- if (VAR == "strahler") arm_mm(scale_vals, NA) else arm_mm(NA, scale_vals)
scale_lab  <- if (VAR == "strahler") paste("order", scale_vals) else paste(format(scale_vals, big.mark = ","), ifelse(scale_vals == 1, "source", "sources"))

# ---- plot -----------------------------------------------------------------------------------------------------------
p <- ggplot() +
  geom_segment(data = filter(arms, arm == "in"), aes(nx, ny, xend = x2, yend = y2), colour = blue, linewidth = .2, lineend = "round", alpha = .85) +
  geom_segment(data = filter(arms, arm == "out"), aes(nx, ny, xend = x2, yend = y2), colour = ink, linewidth = .2, lineend = "round") +
  geom_point(data = st_drop_geometry(rises) |> mutate(x = st_coordinates(rises)[, 1], y = st_coordinates(rises)[, 2]),
             aes(x, y), colour = amber, size = .22) +
  # the mouth
  geom_segment(data = m_col, aes(nx, ny, xend = x2, yend = y2), colour = ink, linewidth = .3, linetype = "22", lineend = "butt") +
  geom_segment(data = m_kettle, aes(nx, ny, xend = x2, yend = y2), colour = blue, linewidth = .3, lineend = "round") +
  annotate("point", x = mouth$nx[1], y = mouth$ny[1], colour = amber, size = 1.4, shape = 1, stroke = .3) +
  annotate("text", x = mouth$nx[1] + 2.5 * m_per_mm, y = mouth$ny[1] - 2.2 * m_per_mm, label = "Columbia River", size = 4.6 * pt,
           colour = mute, family = FONT[["mono"]], hjust = 0, vjust = 1) +
  # header
  text_at(MG + 2, MG + 4, title, 17) +
  text_at(MG + 2, MG + 14, "DAY 1  ·  POINTS  ·  #30DAYMAPCHALLENGE", 6, amber, "mono") +
  text_at(MG + 2, MG + 21, desc, 6.2, mute) +
  # key
  geom_segment(data = key_in, aes(x, y, xend = xe, yend = ye), colour = blue, linewidth = .5, lineend = "round") +
  geom_segment(data = key_out, aes(x, y, xend = xe, yend = ye), colour = ink, linewidth = .5, lineend = "round") +
  annotate("point", x = PX(j[1]), y = PY(j[2]), colour = amber, size = 1.3) +
  text_at(j[1] + 10, j[2] - L_in * cos(ang) - 1, "joining streams", 5, blue, "mono") +
  text_at(j[1] + 4, j[2] - 2.2, "junction", 5, ink, "mono") +
  text_at(j[1] + 4, j[2] + 2, "amber: Strahler order rises", 5, amber, "mono") +
  text_at(j[1] + 3, j[2] + 7.2, "outflow", 5, ink, "mono") +
  text_at(kx, ky + 27, "ARM LENGTH, ACTUAL SIZE (mm)", 4.6, mute, "mono") +
  text_at(kx, ky + 31.2, "(example above drawn 4x larger)", 4.2, mute, "mono")
for (i in seq_along(scale_len)) {
  yy <- ky + 37 + 4.3 * (i - 1)
  p <- p + annotate("segment", x = PX(kx + 1), xend = PX(kx + 1 + scale_len[i]), y = PY(yy), yend = PY(yy), colour = ink, linewidth = .5, lineend = "round") +
    text_at(kx + 8, yy - 1.8, sprintf("%s: %.1f", scale_lab[i], scale_len[i]), 4.8, mute, "mono")
}
p <- p + text_at(MG + 2, H - 14, credit, 4.6, mute, "sans") +
  coord_equal(xlim = c(PX(0), PX(W)), ylim = c(PY(H), PY(0)), expand = FALSE, clip = "off") + theme_void() +
  theme(plot.background = element_rect(fill = bg, colour = NA), plot.margin = margin(0, 0, 0, 0))

suffix <- if (TAG == "") "_unthinned" else if (TAG == "_a15") "" else TAG  # the unthinned run feeds only the page's comparison crop
f <- file.path(OUT_DIR, paste0("day01_final_", VAR, suffix))
ggsave(paste0(f, ".png"), p, width = W / 25.4, height = H / 25.4, dpi = 300, bg = bg, device = ragg::agg_png)
ggsave(paste0(f, ".pdf"), p, width = W / 25.4, height = H / 25.4, bg = bg, device = cairo_pdf)
cat("wrote", f, ".png and .pdf; m per mm:", round(m_per_mm), " K:", round(K, 3), "\n")
