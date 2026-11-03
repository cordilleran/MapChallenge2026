#!/usr/bin/env Rscript
# Day 2 step 02: the finished static map, Letter portrait, drawn in UTM 11N (DISPLAY_CRS).
# Every channel in the basin, line width by Strahler order, colour by sinuosity over about
# 2 km (step 01). Lake connectors and side channels thin and grey. An inset plots
# sinuosity against gradient for windows of 1 km or more. North arrow (true north) and
# scale bar sit in the left column. Measuring stayed in BC Albers (step 01); only the
# drawing is reprojected, so every figure from the attributes is unchanged.
# In : $MC26_DAY02_DATA/windows.gpkg   Out: out/day02_final.png (300 dpi, local) and .pdf
#
# Layout: main() holds the pipeline and comes first; the helpers follow; main() is called
# on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
source(file.path(ROOT, "shared", "R", "map_furniture.R"))
suppressMessages({
  library(ggplot2)
  library(dplyr)
  library(purrr)
  library(sf)
})

# Sinuosity classes, from straight (dim river blue) to sinuous (the accent). The names of
# CLASS_RAMP are the class labels.
CLASS_BREAKS <- c(1, 1.03, 1.08, 1.15, 1.3, Inf)
CLASS_RAMP <- c(
  "under 1.03" = "#3b5b6e", "1.03 to 1.08" = "#5f8fab", "1.08 to 1.15" = "#a9c2c6",
  "1.15 to 1.3" = "#f3cc8a", "1.3 and over" = PALETTE[["amber"]]
)
# Letter page in mm. `left_mm` and `bottom_mm` are kept free of basin for header, key and
# inset (left) and credit (bottom).
PAGE <- list(w_mm = 215.9, h_mm = 279.4, margin_mm = 12, left_mm = 70, bottom_mm = 40)
# Furniture in page mm (x from left, y from top), left column below the inset:
# the compass by its centre, the scale bar by the left end of its line
COMPASS_MM <- c(PAGE$margin_mm + 9, PAGE$h_mm - 46)
SCALE_MM <- c(PAGE$margin_mm + 20, PAGE$h_mm - 42)

main <- function() {
  gpkg <- file.path(DATA_DIR, "windows.gpkg")
  windows <- read_layer(gpkg, "windows", DISPLAY_CRS) |>
    arrange(order) |>                            # big rivers drawn last, on top
    classify_sinuosity(CLASS_BREAKS, names(CLASS_RAMP)) |>
    mutate(line_width = 0.07 + 0.075 * order)    # ggplot linewidth units, by Strahler order
  other <- read_layer(gpkg, "other_lines", DISPLAY_CRS)
  mouth <- st_coordinates(read_layer(gpkg, "mouth", DISPLAY_CRS))

  page <- page_geometry(st_bbox(windows), PAGE)
  north_deg <- true_north_deg(bbox_centre(st_bbox(windows)), DISPLAY_CRS)
  inset <- inset_grob(windows, CLASS_RAMP)

  map <- ggplot() +
    draw_channels(windows, other, CLASS_RAMP) +
    draw_places(mouth, place_labels(windows, page), page) +
    draw_header(page) +
    draw_key(page, CLASS_RAMP, top_mm = PAGE$margin_mm + 104) +
    draw_inset(inset, page, top_mm = PAGE$margin_mm + 104 + 26) +
    draw_furniture(page, north_deg, COMPASS_MM, SCALE_MM) +
    draw_credit(page) +
    page_frame(page)

  save_map(map, file.path(OUT_DIR, "day02_final"), PAGE)
  report_numbers(page, north_deg, windows)
}

# ---- read and prepare ------------------------------------------------------------------

# One layer of the step 01 GeoPackage, drawn in `crs`.
read_layer <- function(path, layer, crs) {
  st_read(path, layer, quiet = TRUE) |>
    st_transform(crs)
}

# Adds `cls`, the sinuosity class as a factor (labels in order of `breaks`).
classify_sinuosity <- function(windows, breaks, labels) {
  mutate(windows, cls = cut(sinuosity, breaks, labels, right = FALSE))
}

# Centre of a bounding box as c(x, y), map units.
bbox_centre <- function(bbox) {
  c((bbox[["xmin"]] + bbox[["xmax"]]) / 2, (bbox[["ymin"]] + bbox[["ymax"]]) / 2)
}

# ---- page geometry: Letter in mm, map units in metres ----------------------------------

# Returns a list: m_per_mm (map metres per page mm), x0 and y_top (map coordinates of the
# page's left edge and top edge), plus the page sizes in mm.
page_geometry <- function(bbox, page) {
  width <- bbox[["xmax"]] - bbox[["xmin"]]
  height <- bbox[["ymax"]] - bbox[["ymin"]]
  m_per_mm <- max(
    width / (page$w_mm - 2 * page$margin_mm - page$left_mm),
    height / (page$h_mm - 2 * page$margin_mm - page$bottom_mm)
  )
  list(
    m_per_mm = m_per_mm, w_mm = page$w_mm, h_mm = page$h_mm, margin_mm = page$margin_mm,
    # basin against the right margin, and a little below the top
    x0 = bbox[["xmax"]] + (page$margin_mm + 4) * m_per_mm - page$w_mm * m_per_mm,
    y_top = bbox[["ymax"]] + (page$margin_mm + 8) * m_per_mm
  )
}

# Page mm to map x and y (m); x_mm from the left, y_mm from the top.
page_x <- function(page, x_mm) page$x0 + x_mm * page$m_per_mm
page_y <- function(page, y_mm) page$y_top - y_mm * page$m_per_mm

# Text layer at page mm; `size_pt` in points, `family` one of the names in FONT.
text_at <- function(page, x_mm, y_mm, label, size_pt, colour = PALETTE[["ink"]],
                    family = "serif", hjust = 0) {
  annotate(
    "text", x = page_x(page, x_mm), y = page_y(page, y_mm), label = label,
    size = size_pt * PT, colour = colour, family = FONT[[family]],
    hjust = hjust, vjust = 1, lineheight = 1.15
  )
}

# ---- layers ----------------------------------------------------------------------------

# Side channels (thin grey) under the windows (colour by class, width by order).
draw_channels <- function(windows, other, ramp) {
  list(
    geom_sf(data = other, colour = PALETTE[["mute"]], linewidth = .12, alpha = .55),
    geom_sf(data = windows, aes(colour = cls, linewidth = line_width), lineend = "round"),
    scale_colour_manual(values = ramp, guide = "none"),
    scale_linewidth_identity()
  )
}

# The mouth marker and its name, then the river labels (a tibble from place_labels()).
draw_places <- function(mouth, labels, page) {
  list(
    annotate("point", x = mouth[1], y = mouth[2], colour = PALETTE[["ink"]],
             size = 1.1, shape = 1, stroke = .3),
    annotate("text", x = mouth[1] + 2 * page$m_per_mm, y = mouth[2] - 1 * page$m_per_mm,
             label = "Grand Forks", size = 5 * PT, colour = PALETTE[["mute"]],
             family = FONT[["mono"]], hjust = 0, vjust = 1),
    geom_label(data = labels, aes(x, y, label = label), size = 5 * PT,
               colour = PALETTE[["mute"]], fill = PALETTE[["ground"]],
               family = FONT[["mono"]], hjust = 0, linewidth = 0,
               label.padding = unit(.6, "mm"), alpha = .85)
  )
}

# Where the river names go: a tibble of x, y (map units, just right of the line) and
# label. For each name, the window at the share `at` of the way up (by y) among the
# windows of that name.
place_labels <- function(windows, page, at = c("Granby River" = .55, "Burrell Creek" = .5)) {
  named <- windows |>
    filter(name %in% names(at))
  centres <- st_coordinates(st_centroid(st_geometry(named)))
  named <- named |>
    st_drop_geometry() |>
    mutate(x = centres[, 1], y = centres[, 2])
  imap(at, \(share, river) {
    along <- named |>
      filter(name == river) |>
      arrange(y)
    along[ceiling(share * nrow(along)), ] |>
      transmute(x = x + 2.2 * page$m_per_mm, y = y, label = river)
  }) |>
    bind_rows()
}

# Title, tag line and description, top left.
draw_header <- function(page) {
  m <- page$margin_mm
  description <- paste0(
    "Every channel in the Granby River basin: long streams cut into\n",
    "equal lengths of about 2 km, creeks under 3 km whole. Colour is\n",
    "sinuosity: channel length over the straight line between its ends. ",
    "Width grows\nwith stream order. ",
    "Thin grey lines are lake connectors and side channels."
  )
  list(
    text_at(page, m + 2, m + 4, "How the Granby bends", 17),
    text_at(page, m + 2, m + 14, "DAY 2  ·  LINES  ·  #30DAYMAPCHALLENGE", 6,
            PALETTE[["amber"]], "mono"),
    text_at(page, m + 2, m + 21, description, 6.2, PALETTE[["mute"]])
  )
}

# The colour key: heading, then one swatch and label per class, from `top_mm`.
draw_key <- function(page, ramp, top_mm) {
  x_mm <- page$margin_mm + 2
  row_y <- top_mm + 4.3 * (seq_along(ramp) - 1)
  list(
    text_at(page, x_mm, top_mm - 6, "SINUOSITY OVER ABOUT 2 KM", 4.6,
            PALETTE[["mute"]], "mono"),
    annotate("segment", x = page_x(page, x_mm + 1), xend = page_x(page, x_mm + 9),
             y = page_y(page, row_y), yend = page_y(page, row_y), colour = unname(ramp),
             linewidth = .9, lineend = "round"),
    text_at(page, x_mm + 12, row_y - 1.6, names(ramp), 4.8, PALETTE[["mute"]], "mono")
  )
}

# The inset's captions and the plot itself, from `top_mm`.
draw_inset <- function(inset, page, top_mm) {
  x_mm <- page$margin_mm + 2
  list(
    text_at(page, x_mm, top_mm, "SINUOSITY AGAINST GRADIENT", 4.6, PALETTE[["mute"]], "mono"),
    text_at(page, x_mm, top_mm + 4,
            "lengths of 1 km or more falling over 0.1 %; white: median per tenth", 4.2,
            PALETTE[["mute"]], "mono"),
    annotation_custom(inset, xmin = page_x(page, x_mm - 2), xmax = page_x(page, x_mm + 62),
                      ymin = page_y(page, top_mm + 66), ymax = page_y(page, top_mm + 8))
  )
}

# North arrow (pointing to true north) and scale bar, each centred or started at page mm.
draw_furniture <- function(page, north_deg, compass_mm, scale_mm) {
  c(
    compass_rose(c(page_x(page, compass_mm[1]), page_y(page, compass_mm[2])),
                 north_deg, page$m_per_mm),
    scale_ticked(c(page_x(page, scale_mm[1]), page_y(page, scale_mm[2])), page$m_per_mm)
  )
}

# Data credit and licences, bottom left.
draw_credit <- function(page) {
  credit <- paste0(
    "Data: BC Freshwater Atlas, Province of British Columbia (contains information ",
    "licensed under the Open Government Licence - British Columbia); ",
    "gradient from a 30 m DEM (Canadian Digital Elevation Model,\n",
    "contains information licensed under the Open Government Licence - Canada). ",
    "Map: Graham Watt, CC BY 4.0. Built in R with Claude Code (Anthropic). ",
    "github.com/cordilleran/MapChallenge2026"
  )
  text_at(page, page$margin_mm + 2, page$h_mm - 15, credit, 4.4, PALETTE[["mute"]], "sans")
}

# The page: limits in map units, dark ground, no margins or datum.
page_frame <- function(page) {
  list(
    coord_sf(xlim = c(page_x(page, 0), page_x(page, page$w_mm)),
             ylim = c(page_y(page, page$h_mm), page_y(page, 0)),
             expand = FALSE, clip = "off", datum = NA),
    theme_void(),
    theme(plot.background = element_rect(fill = PALETTE[["ground"]], colour = NA),
          plot.margin = margin(0, 0, 0, 0))
  )
}

# ---- inset: sinuosity against gradient -------------------------------------------------

# The inset as a grob. Built on a null device so no stray Rplots.pdf appears; its text is
# measured without the named font, which the real devices then render.
inset_grob <- function(windows, ramp) {
  pdf(NULL)
  on.exit(invisible(dev.off()))
  suppressWarnings(ggplotGrob(inset_plot(windows, ramp)))
}

# Sinuosity against gradient (%, log scales) for lengths of 1 km or more falling over
# 0.1 %, with the median per tenth of gradient.
inset_plot <- function(windows, ramp) {
  long <- windows |>
    st_drop_geometry() |>
    filter(length_m >= 1000, gradient > 0.001)
  tenths <- long |>
    mutate(tenth = ntile(gradient, 10)) |>   # as step 01 prints them
    group_by(tenth) |>
    summarise(gradient = median(gradient), sinuosity = median(sinuosity))
  mute <- PALETTE[["mute"]]
  ggplot(long, aes(100 * gradient, sinuosity)) +
    geom_point(aes(colour = cls), size = .35, alpha = .7, stroke = 0) +
    geom_line(data = tenths, colour = PALETTE[["ink"]], linewidth = .35) +
    geom_point(data = tenths, colour = PALETTE[["ink"]], size = .7) +
    scale_colour_manual(values = ramp, guide = "none") +
    scale_x_log10(breaks = c(.3, 1, 3, 10, 30, 100),
                  labels = c("0.3", "1", "3", "10", "30", "100 %")) +
    scale_y_log10(breaks = c(1, 1.1, 1.25, 1.5, 2)) +
    coord_cartesian(ylim = c(1, 2)) +
    labs(x = "gradient (log scale)", y = "sinuosity") +
    theme_void(base_family = FONT[["mono"]], base_size = 5.2) +
    theme(
      axis.text = element_text(colour = mute, size = 4.4),
      axis.title = element_text(colour = mute, size = 4.6),
      axis.title.y = element_text(angle = 90, margin = margin(r = 5)),
      axis.title.x = element_text(margin = margin(t = 3)),
      axis.text.y = element_text(hjust = 1, margin = margin(r = 2)),
      axis.text.x = element_text(margin = margin(t = 2)),
      panel.grid.major = element_line(colour = "#1d3141", linewidth = .2),
      plot.background = element_rect(fill = PALETTE[["ground"]], colour = NA)
    )
}

# ---- output ----------------------------------------------------------------------------

# Writes `stem`.png (300 dpi, ragg) and `stem`.pdf (cairo), both at the Letter page size.
save_map <- function(map, stem, page) {
  size_in <- c(page$w_mm, page$h_mm) / 25.4
  ggsave(paste0(stem, ".png"), map, width = size_in[1], height = size_in[2], dpi = 300,
         bg = PALETTE[["ground"]], device = ragg::agg_png)
  ggsave(paste0(stem, ".pdf"), map, width = size_in[1], height = size_in[2],
         bg = PALETTE[["ground"]], device = cairo_pdf)
}

# Prints the figures this step makes: page scale, true north, the class counts.
report_numbers <- function(page, north_deg, windows) {
  cat("wrote day02_final .png and .pdf; m per mm:", round(page$m_per_mm), "\n")
  cat(sprintf("true north at the basin centre: %+.2f deg from grid north (UTM 11N)\n",
              north_deg))
  cat(sprintf("scale bar: %g km; compass %.0f mm across\n",
              nice_km(page$m_per_mm), 13))
  print(table(windows$cls))
}

main()
