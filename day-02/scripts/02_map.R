#!/usr/bin/env Rscript
# Day 2 step 02: the finished static map, Letter portrait. Every channel in the basin, line width by Strahler order,
# colour by sinuosity over about 2 km (step 01). Lake connectors and side channels thin and grey. An inset plots
# sinuosity against gradient for windows of 1 km or more.
# In : $MC26_DAY02_DATA/windows.gpkg   Out: out/day02_final.png (300 dpi, kept local) and .pdf (vector)
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(ggplot2); library(dplyr); library(sf)})

f_in <- file.path(DATA_DIR, "windows.gpkg")
win   <- st_read(f_in, "windows", quiet = TRUE) |> arrange(order)          # big rivers drawn last, on top
other <- st_read(f_in, "other_lines", quiet = TRUE)
mouth <- st_coordinates(st_read(f_in, "mouth", quiet = TRUE))

# ---- sinuosity classes: from straight (dim river blue) to sinuous (Day 1 amber) ---------------------------------------
BREAKS <- c(1, 1.03, 1.08, 1.15, 1.3, Inf)
LABELS <- c("under 1.03", "1.03 to 1.08", "1.08 to 1.15", "1.15 to 1.3", "1.3 and over")
RAMP   <- c("#3b5b6e", "#5f8fab", "#a9c2c6", "#f3cc8a", AMBER)
win$cls <- cut(win$sinuosity, BREAKS, LABELS, right = FALSE)
win$lw <- 0.07 + 0.075 * win$order                                        # line width (ggplot units) by Strahler order

# ---- page geometry: Letter in mm, map units in metres -----------------------------------------------------------------
W <- 215.9; H <- 279.4; MG <- 12; pt <- 1 / .pt
bb <- st_bbox(win); xr <- bb[c("xmin", "xmax")]; yr <- bb[c("ymin", "ymax")]
m_per_mm <- max(diff(xr) / (W - 2 * MG - 70), diff(yr) / (H - 2 * MG - 40))   # 70 mm on the left for header, key and inset
x0 <- xr[[2]] + (MG + 4) * m_per_mm - W * m_per_mm                             # basin against the right margin
y_top <- yr[[2]] + (MG + 8) * m_per_mm
PX <- function(mm) x0 + mm * m_per_mm
PY <- function(mm) y_top - mm * m_per_mm
text_at <- function(x, y, label, size, col = INK, fam = "serif", hjust = 0)
  annotate("text", x = PX(x), y = PY(y), label = label, size = size * pt, colour = col, family = FONT[[fam]], hjust = hjust, vjust = 1, lineheight = 1.15)

# ---- inset: sinuosity against gradient ------------------------------------------------------------------------------
long <- st_drop_geometry(win) |> filter(length_m >= 1000, gradient > 0.001)
bins <- long |> mutate(g = cut(gradient, quantile(gradient, seq(0, 1, .1)), include.lowest = TRUE)) |>
  group_by(g) |> summarise(gradient = median(gradient), sinuosity = median(sinuosity))
inset <- ggplot(long, aes(100 * gradient, sinuosity)) +
  geom_point(aes(colour = cls), size = .35, alpha = .7, stroke = 0) +
  geom_line(data = bins, colour = INK, linewidth = .35) + geom_point(data = bins, colour = INK, size = .7) +
  scale_colour_manual(values = setNames(RAMP, LABELS), guide = "none") +
  scale_x_log10(breaks = c(.3, 1, 3, 10, 30, 100), labels = c("0.3", "1", "3", "10", "30", "100 %")) +
  scale_y_log10(breaks = c(1, 1.1, 1.25, 1.5, 2)) + coord_cartesian(ylim = c(1, 2)) +
  labs(x = "gradient (log scale)", y = "sinuosity") +
  theme_void(base_family = FONT[["mono"]], base_size = 5.2) +
  theme(axis.text = element_text(colour = MUTE, size = 4.4), axis.title = element_text(colour = MUTE, size = 4.6),
        axis.title.y = element_text(angle = 90, margin = margin(r = 5)), axis.title.x = element_text(margin = margin(t = 3)),
        axis.text.y = element_text(hjust = 1, margin = margin(r = 2)), axis.text.x = element_text(margin = margin(t = 2)),
        panel.grid.major = element_line(colour = "#1d3141", linewidth = .2), plot.background = element_rect(fill = GROUND, colour = NA))

pdf(NULL)                                               # build the grob on a null device (no stray Rplots.pdf); its text is measured
inset_grob <- suppressWarnings(ggplotGrob(inset))       # without the named font, which the real devices then render
invisible(dev.off())

# ---- labels ---------------------------------------------------------------------------------------------------------
nm <- win[win$name %in% c("Granby River", "Burrell Creek"), ]
xy <- st_coordinates(st_centroid(st_geometry(nm)))
named <- st_drop_geometry(nm) |> mutate(x = xy[, 1], y = xy[, 2])
lab_at <- function(n, q) { d <- named[named$name %in% n, ]; d <- d[order(d$y), ]; d[ceiling(q * nrow(d)), c("x", "y")] }
labs_df <- rbind(cbind(lab_at("Granby River", .55), label = "Granby River"), cbind(lab_at("Burrell Creek", .5), label = "Burrell Creek"))

# ---- plot -----------------------------------------------------------------------------------------------------------
kx <- MG + 2; ky <- MG + 104                                                 # key and inset in the lower left, level with the basin
title <- "How the Granby bends"
desc <- paste0("Every channel in the Granby River basin: long streams cut into\nequal lengths of about 2 km, creeks under 3 km whole. Colour is\nsinuosity: channel length over the straight line between its ends. ",
               "Width grows\nwith stream order. Thin grey lines are lake connectors and side channels.")
credit <- paste0("Data: BC Freshwater Atlas, Province of British Columbia (contains information licensed under the Open Government Licence - British Columbia); ",
                 "gradient from a 30 m DEM (Canadian Digital Elevation Model,\ncontains information licensed under the Open Government Licence - Canada). ",
                 "Map: Graham Watt, CC BY 4.0. Built in R with Claude Code (Anthropic). github.com/cordilleran/MapChallenge2026")

p <- ggplot() +
  geom_sf(data = other, colour = MUTE, linewidth = .12, alpha = .55) +
  geom_sf(data = win, aes(colour = cls, linewidth = lw), lineend = "round") +
  scale_colour_manual(values = setNames(RAMP, LABELS), guide = "none") + scale_linewidth_identity() +
  annotate("point", x = mouth[1], y = mouth[2], colour = INK, size = 1.1, shape = 1, stroke = .3) +
  annotate("text", x = mouth[1] + 2 * m_per_mm, y = mouth[2] - 1 * m_per_mm, label = "Grand Forks", size = 5 * pt,
           colour = MUTE, family = FONT[["mono"]], hjust = 0, vjust = 1) +
  geom_label(data = labs_df, aes(x + 2.2 * m_per_mm, y, label = label), size = 5 * pt, colour = MUTE, fill = GROUND, family = FONT[["mono"]],
             hjust = 0, linewidth = 0, label.padding = unit(.6, "mm"), alpha = .85) +
  text_at(MG + 2, MG + 4, title, 17) +
  text_at(MG + 2, MG + 14, "DAY 2  ·  LINES  ·  #30DAYMAPCHALLENGE", 6, AMBER, "mono") +
  text_at(MG + 2, MG + 21, desc, 6.2, MUTE) +
  text_at(kx, ky - 6, "SINUOSITY OVER ABOUT 2 KM", 4.6, MUTE, "mono")
for (i in seq_along(LABELS)) {
  yy <- ky + 4.3 * (i - 1)
  p <- p + annotate("segment", x = PX(kx + 1), xend = PX(kx + 9), y = PY(yy), yend = PY(yy), colour = RAMP[i], linewidth = .9, lineend = "round") +
    text_at(kx + 12, yy - 1.6, LABELS[i], 4.8, MUTE, "mono")
}
p <- p + text_at(kx, ky + 26, "SINUOSITY AGAINST GRADIENT", 4.6, MUTE, "mono") +
  text_at(kx, ky + 30, "lengths of 1 km or more falling over 0.1 %; white: median per tenth", 4.2, MUTE, "mono") +
  annotation_custom(inset_grob, xmin = PX(kx - 2), xmax = PX(kx + 62), ymin = PY(ky + 92), ymax = PY(ky + 34)) +
  text_at(MG + 2, H - 15, credit, 4.4, MUTE, "sans") +
  coord_sf(xlim = c(PX(0), PX(W)), ylim = c(PY(H), PY(0)), expand = FALSE, clip = "off", datum = NA) + theme_void() +
  theme(plot.background = element_rect(fill = GROUND, colour = NA), plot.margin = margin(0, 0, 0, 0))

f <- file.path(OUT_DIR, "day02_final")
ggsave(paste0(f, ".png"), p, width = W / 25.4, height = H / 25.4, dpi = 300, bg = GROUND, device = ragg::agg_png)
ggsave(paste0(f, ".pdf"), p, width = W / 25.4, height = H / 25.4, bg = GROUND, device = cairo_pdf)
cat("wrote", f, ".png and .pdf; m per mm:", round(m_per_mm), "\n")
print(table(win$cls))
