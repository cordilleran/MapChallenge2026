#!/usr/bin/env Rscript
# Day 1 static map: glyph-only, no basemap. Arm LENGTH = Strahler order, arm WIDTH = relative specific yield.
# Letter portrait, 300 dpi PNG + vector PDF. Arm lengths are defined on the PAGE (mm), converted to ground metres.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(ggplot2); library(dplyr); library(sf)})
DATA <- DATA_DIR
OUT <- OUT_DIR; dir.create(OUT, showWarnings = FALSE)
arms <- read.csv(file.path(DATA, Sys.getenv("MC26_ARMS", "arms.csv")))
if ("q_rel_v2" %in% names(arms)) arms$q_rel <- arms$q_rel_v2          # yield axis v2 (BEC weight, step 19)
cf   <- st_read(file.path(DATA, Sys.getenv("MC26_NET", "network.gpkg")), "confluences", quiet = TRUE)
W_MM <- 8.5 * 25.4; H_MM <- 11 * 25.4; MARGIN <- 12
xr <- range(c(arms$nx)); yr <- range(c(arms$ny))
m_per_mm <- max(diff(xr) / (W_MM - 2 * MARGIN), diff(yr) / (H_MM - 2 * MARGIN - 18))
LEN <- Sys.getenv("MC26_LEN", "linear"); WID <- Sys.getenv("MC26_WIDTH", "yield")       # length rule: linear | sqrt | cap; width: yield | uniform
MMAX <- if ("mag" %in% names(arms)) max(arms$mag, na.rm = TRUE) else NA                  # largest Shreve magnitude on the page
L_MM <- function(o, m) switch(LEN, linear = 0.45 * o, sqrt = 0.78 * sqrt(o), cap = pmin(0.45 * o, 1.8),
  mag_log2 = 0.8 + 2.4 * log2(m) / log2(MMAX), mag_pow = 0.8 * m^(log(4) / log(MMAX)), mag_p25 = pmin(0.8 * m^0.25, 4))   # arm length on paper, mm
arms$len_m <- L_MM(arms$order, arms$mag) * m_per_mm
arms$x2 <- arms$nx + arms$len_m * sin(arms$bearing * pi / 180)
arms$y2 <- arms$ny + arms$len_m * cos(arms$bearing * pi / 180)
arms$lw <- ifelse(arms$qc_ok & !is.na(arms$q_rel), pmin(pmax(arms$q_rel, 0.3), 2.7), 0.3)   # arms that fail QC are drawn at the minimum width
if (WID == "uniform") arms$lw <- 1
arms$kind <- ifelse(arms$arm == "out", "outflow", "inflow")
xyc <- st_coordinates(cf); cf$x <- xyc[, 1]; cf$y <- xyc[, 2]
nodes <- cf |> st_drop_geometry() |> filter(order_changes, !braid)
bg <- "#0c1822"; ink <- "#e9f1f5"; acc <- "#ffb454"
p <- ggplot() +
  geom_segment(data = arms |> filter(arm == "in"), aes(nx, ny, xend = x2, yend = y2, linewidth = lw), colour = "#7fb7d6", lineend = "round", alpha = .85) +
  geom_segment(data = arms |> filter(arm == "out"), aes(nx, ny, xend = x2, yend = y2, linewidth = lw), colour = ink, lineend = "round") +
  geom_point(data = nodes, aes(x, y), colour = acc, size = .22) +
  scale_linewidth(range = if (WID == "uniform") c(.2, .2) else c(.06, .55), guide = "none") +
  coord_equal(xlim = xr + c(-1, 1) * 2000, ylim = yr + c(-1, 1) * 2000, expand = FALSE) + theme_void() +
  theme(plot.background = element_rect(fill = bg, colour = NA), plot.margin = margin(MARGIN, MARGIN, MARGIN + 18, MARGIN, "mm"))
ggsave(file.path(OUT, Sys.getenv("MC26_OUTNAME", "day01_draft.png")), p, width = 8.5, height = 11, dpi = 300, bg = bg)
cat("m per mm:", round(m_per_mm), " arms:", nrow(arms), " order-changing nodes:", nrow(nodes), "\n")
