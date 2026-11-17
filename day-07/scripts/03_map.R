#!/usr/bin/env Rscript
# Day 7 step 03: the print map, Tabloid (11 x 17 in) portrait, drawn in UTM 15N (D328).
# "Ten Minutes in April, 1962: a geography of Blowin' in the Wind". Duluth to Hibbing as the
# 1958 USGS 1:250,000 sheets drew it, redrawn from their own inks, with what the song asks of
# it: the roads out, the three seas, the mountain dug out, the doves, the wind of April 1962.
#
# The page follows the 1958 sheets: the map in a neatline, a collar outside it (latitude and
# longitude every 15 minutes, township and range, the miles to the next town where a road
# leaves the map), and under the map the sheet's own legend, scales, notes, a location
# diagram and the sectionized township.
#
# Raster layers (relief, water, the 1958 ink plates) are multiplied onto the paper colour in
# one image at print resolution; woods and water are laid as watercolour washes. Vector
# layers go on top.
#
# In : $MC26_DAY07_DATA/derived (steps 02, 05, 07, 08; htmc/ from steps 10-14), raw/ (PLSS,
#      states, step 01)
# Out: out/day07_<variant>.png (300 dpi, with grain, local) and .pdf (no grain), and
#      out/day07_<variant>_layout.json (pixel positions for step 04)
# Usage: Rscript 03_map.R [A|B]   B (the default since GW's pick, D303) marks the memorial.
#
# Layout: main() first, the helpers follow; main() is called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
source(file.path(ROOT, "shared", "R", "map_furniture.R"))
suppressMessages({
  library(dplyr)
  library(purrr)
  library(sf)
  library(terra)
  library(ggplot2)
})

PAGE <- list(w_mm = 279.4, h_mm = 431.8, map_w_mm = 240, map_top_mm = 57)
COLLAR_MM <- 14.5        # neatline to the outer border, all round
DPI <- 300
BASE_DPI <- 762   # the map raster: 21.2 m a pixel at 1:641,000, the scans' own resolution, so the 1958 lettering stays crisp in the PDF
K <- 1.3                 # type and mark sizes, against the first (Letter) design
ROSE_AT <- c(-91.58, 46.91)   # lon, lat: open water east of Duluth, where the rose is drawn
GPKG <- file.path(DERIVED_DIR, "day07.gpkg")
HTMC_DIR <- file.path(DERIVED_DIR, "htmc")

FONT_FILES <- c(
  elite = "SpecialElite-Regular.ttf", caveat = "Caveat-Variable.ttf",
  garamond = "EBGaramond-Variable.ttf", jost = "Jost-Variable.ttf", jostit = "Jost-Italic-Variable.ttf"
)

# How each raster layer darkens the paper: colour, strongest opacity, and whether it is laid
# as a watercolour wash (D311, D326)
BLEND <- list(
  relief = list(col = INK[["charcoal"]], max = 0.20, wash = FALSE),
  wetland = list(col = INK[["water"]], max = 0.20, wash = TRUE),  # NWI, under the sheets' own tufts (D327 draft)
  water  = list(col = INK[["water"]], max = 0.55, wash = TRUE),
  green  = list(col = INK[["woods"]], max = 0.28, wash = TRUE),     # 1958 woodland tint
  urban  = list(col = INK[["charcoal"]], max = 0.16, wash = FALSE), # 1958 built-up fill
  brown  = list(col = INK[["suede"]], max = 0.70, wash = FALSE),
  blue   = list(col = INK[["stream"]], max = 0.75, wash = FALSE),
  black  = list(col = INK[["charcoal"]], max = 0.95, wash = FALSE),
  red    = list(col = INK[["charcoal"]], max = 0.80, wash = FALSE)
)

main <- function() {
  variant <- commandArgs(TRUE)[1] %||% "B"
  stopifnot(variant %in% c("A", "B"))
  register_fonts()

  layers <- read_layers()
  page <- page_geometry(layers$frame)
  base <- compose_base(layers, page)

  p <- ggplot() +
    annotation_raster(base, page$frame_bb[["xmin"]], page$frame_bb[["xmax"]],
                      page$frame_bb[["ymin"]], page$frame_bb[["ymax"]]) +
    draw_seas(layers) +
    draw_pits(layers, page) +
    draw_ripples(layers, page) +
    draw_doves(layers) +
    draw_places(layers, variant) +
    draw_rose(layers, page) +
    draw_frame(page) +
    draw_notes(page, layers, variant) +
    draw_collar(page, layers) +
    draw_title(page) +
    draw_lower_collar(page, layers, variant) +
    coord_sf(crs = DISPLAY_CRS, datum = NA, expand = FALSE,
             xlim = page$xlim, ylim = page$ylim) +
    scale_alpha_identity() +
    theme_void() +
    theme(plot.margin = margin(0, 0, 0, 0),
          plot.background = element_rect(fill = INK[["paper"]], colour = NA))

  stem <- file.path(OUT_DIR, paste0("day07_", variant))
  write_layout(page, layers, paste0(stem, "_layout.json"))
  save_pdf(p, paste0(stem, ".pdf"))
  save_png(p + grain_layer(page), paste0(stem, ".png"))
  message("Wrote ", stem, ".pdf and .png; scale 1:", format(page$scale, big.mark = ","))
}

# Fonts ship with the code (D305): showtext draws them on any device, offline
register_fonts <- function() {
  iwalk(FONT_FILES, \(file, family) sysfonts::font_add(family, file.path(FONT_DIR, file)))
  showtext::showtext_auto()
  showtext::showtext_opts(dpi = DPI)
}

# Width of a line of text in mm, measured from the font file (widest line if several)
text_w_mm <- function(label, family, pt) {
  lines <- strsplit(label, "\n", fixed = TRUE)[[1]]
  w <- systemfonts::string_width(lines, path = file.path(FONT_DIR, FONT_FILES[[family]]), size = pt, res = 72)
  max(w) * 25.4 / 72
}

# Words of `text` wrapped to lines no wider than width_mm. The measured widths run a few per
# cent narrow of the rendered text, so lines are broken at WRAP_FILL of the width.
WRAP_FILL <- 0.92
wrap_mm <- function(text, family, pt, width_mm) {
  width_mm <- width_mm * WRAP_FILL
  words <- strsplit(text, " ", fixed = TRUE)[[1]]
  lines <- character()
  line <- ""
  for (w in words) {
    try_line <- if (nzchar(line)) paste(line, w) else w
    if (nzchar(line) && text_w_mm(try_line, family, pt) > width_mm) {
      lines <- c(lines, line)
      line <- w
    } else {
      line <- try_line
    }
  }
  paste(c(lines, line), collapse = "\n")
}

read_layers <- function() {
  rd <- \(layer) st_read(GPKG, layer, quiet = TRUE)
  opt <- \(path) if (file.exists(path)) st_read(path, quiet = TRUE) else NULL
  csv <- \(path) if (file.exists(path)) utils::read.csv(path) else NULL
  list(
    frame = rd("frame"),
    water = rd("water"),
    wetlands = if ("wetlands" %in% st_layers(GPKG)$name) rd("wetlands") else st_sf(geometry = st_sfc(crs = DISPLAY_CRS)),
    divides = rd("divides"),
    drainage = rd("drainage"),
    three_waters = rd("three_waters"),
    lake_whole = rd("lake_whole"),
    pits_2026 = rd("pits"),
    pits_1958 = opt(file.path(HTMC_DIR, "pits_1958.gpkg")),
    doves = rd("doves"),
    places = rd("places"),
    rose = read_rose(),
    waves = opt(file.path(DERIVED_DIR, "waves_week.gpkg")),
    plss = opt(file.path(RAW_DIR, "plss_townships.geojson")),
    states = opt(file.path(RAW_DIR, "states.geojson")),
    roads_out = csv(file.path(DERIVED_DIR, "roads_out.csv"))
  )
}

# The double rose (10 m and 700 hPa, step 05) if it exists, else the 10 m rose (step 02)
read_rose <- function() {
  double <- file.path(DERIVED_DIR, "wind_rose_double.csv")
  if (file.exists(double)) {
    return(utils::read.csv(double) |> rename(sector = sector_from_deg))
  }
  utils::read.csv(file.path(DERIVED_DIR, "wind_rose.csv")) |> mutate(level = "10m")
}

# Page and map in one coordinate system: map metres, with the page around the frame
page_geometry <- function(frame) {
  bb <- st_bbox(frame)
  m_per_mm <- (bb[["xmax"]] - bb[["xmin"]]) / PAGE$map_w_mm
  left_mm <- (PAGE$w_mm - PAGE$map_w_mm) / 2
  x0 <- bb[["xmin"]] - left_mm * m_per_mm
  y_top <- bb[["ymax"]] + PAGE$map_top_mm * m_per_mm
  map_h_mm <- (bb[["ymax"]] - bb[["ymin"]]) / m_per_mm
  list(
    frame_bb = bb, m = m_per_mm, left_mm = left_mm, right_mm = left_mm + PAGE$map_w_mm,
    map_h_mm = map_h_mm, map_top_mm = PAGE$map_top_mm, map_bottom_mm = PAGE$map_top_mm + map_h_mm,
    xlim = c(x0, x0 + PAGE$w_mm * m_per_mm),
    ylim = c(y_top - PAGE$h_mm * m_per_mm, y_top),
    # page millimetres (x from left, y from top) to map metres
    at = \(x_mm, y_mm) c(x0 + x_mm * m_per_mm, y_top - y_mm * m_per_mm),
    # a point given as a share of the map's width and height (from its top-left corner)
    on_map = \(u, v) c(bb[["xmin"]] + u * (bb[["xmax"]] - bb[["xmin"]]), bb[["ymax"]] - v * (bb[["ymax"]] - bb[["ymin"]])),
    scale = round(m_per_mm * 1000, -3),
    px = c(ncol = round(PAGE$map_w_mm / 25.4 * BASE_DPI), nrow = round(map_h_mm / 25.4 * BASE_DPI))
  )
}

# ---- The base image ---------------------------------------------------------------------

# One RGB image of the frame at print resolution: paper, multiplied by each raster layer
compose_base <- function(layers, page) {
  grid <- rast(ext(vect(layers$frame)), ncols = page$px[["ncol"]], nrows = page$px[["nrow"]],
               crs = paste0("EPSG:", DISPLAY_CRS))
  shade <- rast(file.path(DERIVED_DIR, "relief.tif")) |> resample(grid, method = "bilinear")
  opacity <- list(
    relief = 1 - clamp(shade / 255, 0, 1),
    water = max(rasterize(vect(layers$water), grid, field = 1, background = 0),   # NCEI lake + OSM water (02)
                sheet_water(grid)),                                              # the sheets' own lakes
    wetland = if (nrow(layers$wetlands) > 0) rasterize(vect(layers$wetlands), grid, field = 1, background = 0)
  ) |> compact()
  inks <- c("green", "urban", "brown", "blue", "red", "black") |>
    set_names() |>
    map(\(ink) file.path(HTMC_DIR, paste0("ink_", ink, ".tif"))) |>
    keep(file.exists) |>
    map(\(path) resample(rast(path), grid, method = "average") / 255)
  opacity <- c(opacity, inks) |> map(\(r) as.matrix(clamp(r, 0, 1), wide = TRUE))
  message("Raster layers: ", paste(names(opacity), collapse = ", "))
  blend_plates(opacity, seed = 1962)
}

# The 1958 water plate (step 12), as the inland lakes take the same wash as Superior (GW, D327)
sheet_water <- function(grid) {
  path <- file.path(HTMC_DIR, "ink_water.tif")
  if (!file.exists(path)) return(rast(grid, vals = 0))
  w <- resample(rast(path), grid, method = "average") / 255
  ifel(is.na(w), 0, clamp(w / WATER_FULL, 0, 1))
}
WATER_FULL <- 0.6   # plate density read as full water: the tint is thinner than Superior's polygon

# Paper, multiplied by each plate in BLEND order; wash plates get the watercolour treatment
blend_plates <- function(opacity, seed) {
  dims <- dim(opacity[[1]])
  rgb <- col2rgb(INK[["paper"]])[, 1] / 255
  img <- map(1:3, \(i) matrix(rgb[i], dims[1], dims[2]))
  for (name in intersect(names(BLEND), names(opacity))) {
    a <- opacity[[name]]
    a[is.na(a)] <- 0
    if (BLEND[[name]]$wash) a <- watercolour(a, seed + match(name, names(BLEND)))
    a <- pmin(a, 1) * BLEND[[name]]$max
    col <- col2rgb(BLEND[[name]]$col)[, 1] / 255
    img <- map(1:3, \(i) img[[i]] * (1 - a + a * col[i]))   # multiply blend
  }
  as.raster(array(c(img[[1]], img[[2]], img[[3]]), dim = c(dims, 3)))
}

# A gentle watercolour wash (GW 11-16): pigment uneven at a few millimetres, pooled a little
# darker just inside each edge, and the edge itself softened
WASH_SCALE <- BASE_DPI / 300   # the wash sizes were set at 300 dpi
WASH_GRAIN_PX <- round(40 * WASH_SCALE)   # size of the unevenness, about 3.4 mm
WASH_EVEN <- 0.80         # 1 = flat; lower = more uneven
WASH_POOL <- 0.9          # extra pigment at the inner edge
WASH_POOL_PX <- 2 * round(9 * WASH_SCALE / 2) + 1   # odd, for focal()
WASH_SOFT_PX <- 2 * round(3 * WASH_SCALE / 2) + 1

watercolour <- function(a, seed) {
  set.seed(seed)
  n <- dim(a)
  nc <- ceiling(n / WASH_GRAIN_PX)
  coarse <- unit_rast(matrix(stats::rnorm(prod(nc)), nc[1], nc[2]))
  tex <- as.matrix(resample(coarse, unit_rast(a), method = "cubicspline"), wide = TRUE)
  tex <- WASH_EVEN + (1 - WASH_EVEN) * (1 + tex / max(abs(tex)))
  rim <- pmax(a - as.matrix(focal(unit_rast(a), WASH_POOL_PX, "mean", na.rm = TRUE), wide = TRUE), 0)
  as.matrix(focal(unit_rast(a * tex + WASH_POOL * rim), WASH_SOFT_PX, "mean", na.rm = TRUE), wide = TRUE)
}

# A matrix as a raster on the unit square (rows top to bottom)
unit_rast <- function(a) {
  r <- rast(nrows = nrow(a), ncols = ncol(a), xmin = 0, xmax = 1, ymin = 0, ymax = 1)
  values(r) <- as.vector(t(a))
  r
}

# The 1958 legend (step 14) in the same inks and washes as the map
compose_legend <- function() {
  path <- file.path(HTMC_DIR, "legend_plates.tif")
  if (!file.exists(path)) return(NULL)
  r <- suppressWarnings(rast(path))   # pixel space of the scan: no extent, by design
  names(r) <- c("black", "blue", "red", "brown", "green", "water", "urban")
  # no geotransform, so terra reads the rows bottom up: turn them back
  map(names(r), \(p) {
    a <- as.matrix(r[[p]], wide = TRUE) / 255
    a[nrow(a):1, ]
  }) |> set_names(names(r)) |> blend_plates(seed = 1958)
}

# ---- The map's own marks ------------------------------------------------------------------

# The three seas: the divides as a dashed line, the meeting point
draw_seas <- function(layers) {
  tp <- st_coordinates(layers$three_waters)
  list(
    geom_sf(data = layers$divides, colour = INK[["charcoal"]], linewidth = 0.45 * K,
            linetype = "42", lineend = "round"),
    annotate("point", x = tp[1], y = tp[2], shape = 21, size = 2.6 * K, stroke = 0.6 * K,
             fill = INK[["paper"]], colour = INK[["charcoal"]]),
    annotate("point", x = tp[1], y = tp[2], size = 0.7 * K, colour = INK[["charcoal"]])
  )
}

# The 1958 pits in rust; what the pits took after 1958 as rust stipple over the paper
# (change as texture, not a tint: topo judgement 5). Without the 1958 layer (no rule finds the
# pits on the sheets, step 13, D323), the 2026 pits are a rust outline and stipple over the
# 1958 print, where the pits of that year show through as their own tight brown contours.
# Softened 11-16 (GW): the pits stood out above every other mark; now a little above the lakes.
PIT_FILL_ALPHA <- 0.16
PIT_EDGE_ALPHA <- 0.55
PIT_DOT_ALPHA <- 0.55

pit_marks <- function(area, page) {
  list(
    geom_sf(data = st_sf(geometry = area), fill = INK[["rust"]], colour = alpha(INK[["rust"]], PIT_EDGE_ALPHA),
            alpha = PIT_FILL_ALPHA, linewidth = 0.25 * K, inherit.aes = FALSE),
    geom_sf(data = stipple(area, page, step_mm = 0.6 * K), colour = INK[["rust"]], alpha = PIT_DOT_ALPHA,
            size = 0.25 * K, stroke = 0, inherit.aes = FALSE)
  )
}

draw_pits <- function(layers, page) {
  if (is.null(layers$pits_1958)) return(pit_marks(st_union(layers$pits_2026), page))
  old <- st_union(layers$pits_1958)
  grown <- st_difference(st_union(layers$pits_2026), old)
  list(
    geom_sf(data = st_sf(geometry = old), fill = INK[["rust"]], colour = NA, alpha = 0.9),
    geom_sf(data = stipple(grown, page), colour = INK[["rust"]], size = 0.18 * K, stroke = 0)
  )
}

# Offset rows of dots, step_mm apart on the page, inside `area`
stipple <- function(area, page, step_mm = 0.95) {
  step <- step_mm * page$m
  bb <- st_bbox(area)
  ys <- seq(bb[["ymin"]], bb[["ymax"]], by = step * sqrt(3) / 2)
  pts <- imap(ys, \(y, i) cbind(seq(bb[["xmin"]] + (i %% 2) * step / 2, bb[["xmax"]], by = step), y)) |>
    reduce(rbind)
  st_as_sf(as.data.frame(pts), coords = c(1, 2), crs = DISPLAY_CRS) |> st_filter(st_sf(geometry = area))
}

# The estimated waves of 10-16 April 1962 (step 07, D320): at each lake point three short
# crests across the direction of travel, longer where the waves were higher, fainter where
# the direction changed through the week. An estimate from wind and fetch, not a record.
draw_ripples <- function(layers, page, max_len_mm = 3.2 * K, gap_mm = 0.6 * K) {
  if (is.null(layers$waves)) return(NULL)
  w <- layers$waves
  xy <- st_coordinates(w)
  to <- w$to_deg * pi / 180
  along <- cbind(sin(to), cos(to))          # direction of travel
  across <- cbind(cos(to), -sin(to))        # along the crest
  len <- (0.8 * K + (max_len_mm - 0.8 * K) * w$hs_m / max(w$hs_m)) * page$m
  crests <- map(c(-1, 0, 1), \(k) {
    centre <- xy + along * k * gap_mm * page$m
    tibble::tibble(x = centre[, 1] - across[, 1] * len / 2, y = centre[, 2] - across[, 2] * len / 2,
                   xend = centre[, 1] + across[, 1] * len / 2, yend = centre[, 2] + across[, 2] * len / 2,
                   alpha = 0.25 + 0.5 * w$steadiness)
  }) |> bind_rows()
  geom_segment(data = crests, aes(x = x, y = y, xend = xend, yend = yend, alpha = alpha),
               colour = INK[["graphite"]], linewidth = 0.18 * K, lineend = "round",
               inherit.aes = FALSE, show.legend = FALSE)
}

draw_doves <- function(layers) {
  geom_sf(data = layers$doves, shape = 21, size = 0.55 * K, stroke = 0.12 * K,
          fill = INK[["dove"]], colour = INK[["charcoal"]], alpha = 0.9)
}

draw_places <- function(layers, variant) {
  pts <- layers$places |> filter(id %in% c("duluth", "hibbing"))
  out <- list(geom_sf(data = pts, shape = 21, size = 1.6 * K, stroke = 0.5 * K,
                      fill = INK[["paper"]], colour = INK[["charcoal"]]))
  if (variant == "B") {
    mem <- layers$places |> filter(id == "memorial")
    out <- c(out, list(geom_sf(data = mem, shape = 22, size = 1.3 * K, stroke = 0.45 * K,
                               fill = INK[["paper"]], colour = INK[["charcoal"]])))
  }
  out
}

# The double rose in the lake: petal length is the share of the month's 720 hours
# blowing from each of 16 directions; 10 m filled, 700 hPa (about 10,000 ft) as an outline.
rose_petals <- function(rose, centre, scale_m) {
  petal <- \(sector, share, level) {
    half <- 11.25 * 0.82
    th <- (sector + c(-half, -half / 2, 0, half / 2, half)) * pi / 180
    r <- share * scale_m
    tibble::tibble(x = c(centre[1], centre[1] + r * sin(th)), y = c(centre[2], centre[2] + r * cos(th)),
                   id = paste(level, sector), level = level)
  }
  pmap(rose |> select(sector, share, level), petal) |> bind_rows()
}

draw_rose <- function(layers, page, radius_mm = 12 * K) {
  centre <- st_sfc(st_point(ROSE_AT), crs = 4326) |> st_transform(DISPLAY_CRS) |> st_coordinates() |> c()
  scale_m <- radius_mm * page$m / max(layers$rose$share)
  petals <- rose_petals(layers$rose, centre, scale_m)
  rings <- c(0.1, 0.2) |> map(\(s) {
    th <- seq(0, 2 * pi, length.out = 120)
    tibble::tibble(x = centre[1] + s * scale_m * sin(th), y = centre[2] + s * scale_m * cos(th), share = s)
  }) |> bind_rows()
  lab <- centre + 0.2 * scale_m * c(0.71, 0.71) + c(0.6, 0.6) * page$m
  list(
    geom_path(data = rings, aes(x, y, group = share), colour = INK[["graphite"]],
              linewidth = 0.15 * K, linetype = "22", inherit.aes = FALSE),
    geom_polygon(data = petals |> filter(level == "10m"), aes(x, y, group = id),
                 fill = INK[["suede"]], colour = NA, alpha = 0.75, inherit.aes = FALSE),
    geom_polygon(data = petals |> filter(level != "10m"), aes(x, y, group = id),
                 fill = NA, colour = INK[["charcoal"]], linewidth = 0.3 * K, inherit.aes = FALSE),
    annotate("text", x = lab[1], y = lab[2], label = "20 % of hours", hjust = 0,
             vjust = 0, family = "jost", size = pt_to_mm(5.5), colour = INK[["graphite"]])
  )
}

# The neatline round the map, and the heavy outer border round the collar, as on the sheets
draw_frame <- function(page) {
  bb <- page$frame_bb
  o <- COLLAR_MM * page$m
  list(
    annotate("rect", xmin = bb[["xmin"]], xmax = bb[["xmax"]], ymin = bb[["ymin"]],
             ymax = bb[["ymax"]], fill = NA, colour = INK[["charcoal"]], linewidth = 0.45),
    annotate("rect", xmin = bb[["xmin"]] - o, xmax = bb[["xmax"]] + o, ymin = bb[["ymin"]] - o,
             ymax = bb[["ymax"]] + o, fill = NA, colour = INK[["charcoal"]], linewidth = 1.1)
  )
}

# ---- Handwritten notes --------------------------------------------------------------------

# Text with a paper-coloured halo, so it reads over the 1958 inks
halo_text <- function(x, y, label, family, pt, colour = INK[["charcoal"]], hjust = 0, vjust = 0.5,
                      lineheight = 0.85, halo_mm = 0.3, page_m, angle = 0) {
  r <- halo_mm * page_m
  offsets <- expand.grid(dx = c(-1, 0, 1), dy = c(-1, 0, 1)) |> filter(dx != 0 | dy != 0)
  halo <- pmap(offsets, \(dx, dy) annotate("text", x = x + dx * r, y = y + dy * r, label = label,
                                          family = family, size = pt_to_mm(pt), colour = INK[["paper"]],
                                          alpha = 0.8, hjust = hjust, vjust = vjust, lineheight = lineheight,
                                          angle = angle))
  c(halo, list(annotate("text", x = x, y = y, label = label, family = family, size = pt_to_mm(pt),
                        colour = colour, hjust = hjust, vjust = vjust, lineheight = lineheight,
                        angle = angle)))
}

# A handwritten note at (u, v), a share of the map's width and height from its top-left corner,
# with a thin leader to the feature. The leader leaves from the middle of the side of the text
# block nearest the feature (GW 11-16), so it never crosses the writing.
NOTE_LINEHEIGHT <- 0.85
note_at <- function(page, feature_xy, u, v, label, pt, hjust = 0) {
  pt <- pt * K
  at <- page$on_map(u, v)
  out <- halo_text(at[1], at[2], label, "caveat", pt, hjust = hjust, lineheight = NOTE_LINEHEIGHT,
                   page_m = page$m)
  w <- text_w_mm(label, "caveat", pt) * page$m
  h <- length(strsplit(label, "\n")[[1]]) * pt * 0.3528 * NOTE_LINEHEIGHT * 1.25 * page$m
  x0 <- at[1] - hjust * w
  sides <- rbind(left = c(x0, at[2]), right = c(x0 + w, at[2]),
                 top = c(x0 + w / 2, at[2] + h / 2), bottom = c(x0 + w / 2, at[2] - h / 2))
  out_dir <- rbind(left = c(-1, 0), right = c(1, 0), top = c(0, 1), bottom = c(0, -1))
  near <- which.min((sides[, 1] - feature_xy[1])^2 + (sides[, 2] - feature_xy[2])^2)
  start <- sides[near, ] + out_dir[near, ] * 0.9 * page$m
  toward <- feature_xy - start
  end <- feature_xy - toward / sqrt(sum(toward^2)) * 1.4 * page$m   # stop short of the mark
  c(list(annotate("segment", x = start[1], y = start[2], xend = end[1], yend = end[2],
                  colour = INK[["charcoal"]], linewidth = 0.22 * K)), out)
}

draw_notes <- function(page, layers, variant) {
  xy <- \(id) st_coordinates(layers$places[layers$places$id == id, ])[1, 1:2]
  tp <- st_coordinates(layers$three_waters)[1, 1:2]
  sides <- sea_label_points(layers)
  c(
    note_at(page, xy("duluth"), 0.457, 0.644, "Duluth — born here, 1941", 9.5, hjust = 1),
    note_at(page, xy("hibbing"), 0.017, 0.350,
            "Hibbing — grew up here.\nThe town moved south from 1919\nto make way for the pit", 8.5),
    note_at(page, tp, 0.076, 0.057, "how many seas —\na raindrop here can run to three", 9.5),
    note_at(page, pit_anchor(layers), 0.272, 0.294, paste(
      "how many years can a mountain exist —",
      "the Mesabi, dug out and sent by rail",
      "to the docks, and down the lake", sep = "\n"), 8.5),
    note_at(page, xy("duluth"), 0.691, 0.717, "the ore docks:\niron for the steel,\nsteel for the cannonballs", 8.5),
    note_at(page, xy("minnesota_point"), 0.680, 0.836, "before she sleeps in the sand —\nMinnesota Point", 8.5),
    pmap(sides, \(x, y, label) halo_text(x, y, label, "caveat", 7.5 * K, INK[["graphite"]],
                                          hjust = 0.5, page_m = page$m)) |>
      flatten(),
    if (variant == "B") memorial_note(page, xy("memorial")) else NULL
  )
}

# Where to write each sea's name: a point inside that drainage, within 18 km of the triple point
sea_label_points <- function(layers) {
  ring <- st_buffer(layers$three_waters, 18000) |> st_geometry()
  names <- c("04" = "to the Atlantic", "07" = "to the Gulf of Mexico", "09" = "to Hudson Bay")
  pts <- suppressWarnings(st_intersection(layers$drainage, ring) |> st_point_on_surface())
  xy <- st_coordinates(pts)
  tibble::tibble(x = xy[, 1], y = xy[, 2], label = names[pts$huc2])
}

# A point inside the largest pit, to hang the mountain note on
pit_anchor <- function(layers) {
  pits <- if (is.null(layers$pits_1958)) layers$pits_2026 else layers$pits_1958
  biggest <- pits[which.max(st_area(pits)), ]
  st_coordinates(suppressWarnings(st_point_on_surface(st_geometry(biggest))))[1, 1:2]
}

memorial_note <- function(page, xy) {
  note_at(page, xy, 0.527, 0.818, paste(
    "Elias Clayton, Elmer Jackson and Isaac McGhie",
    "were lynched here by a mob on 15 June 1920.",
    "Their memorial stands at First Street and Second Avenue East.", sep = "\n"),
    7.5, hjust = 1)
}

# ---- The collar ---------------------------------------------------------------------------
# Outside the neatline, in the custom of the 1958 sheets (D325; GW 11-16: latitude and
# longitude and imperial units only, no UTM grid):
#   tier 1: latitude and longitude every 15 minutes at their ticks (whole degrees in full,
#           the rest as minutes), and township and range numbers between the survey lines;
#   tier 2: where a numbered road leaves the map, the town it leads to and the miles (step 08),
#           with an arrow on the road at the neatline.
# Ticks follow the meridians and parallels where they meet the neatline. Labels are placed
# per edge and tier: graticule first, then survey numbers where they fit, then road notes,
# each slid along the edge until it clears the others.
GRAT_STEP_DEG <- 0.25
TICK_MM <- c(grat = 2.2, survey = 1.4, arrow = 2.0)
TIER_MM <- c(`1` = 2.8, `2` = 11.5)           # outward offset of each tier's inner edge; on the sides tier 2 (the road notes,
                                              # turned as on the 1958 sheets) clears the widest tier-1 label, "T. 54 N."
TIER2_TB_MM <- 6.6                            # tier 2 on top and bottom (labels there are short)
CORNER_MM <- 3
PAD_MM <- 1.6
SLIDE_MM <- c(0, rbind(seq(2, 40, by = 2), -seq(2, 40, by = 2)))
COLLAR_PT <- c(grat = 7.5, survey = 6, road = 6.5)

draw_collar <- function(page, layers) {
  grat <- graticule_points(page)
  survey <- survey_points(layers$plss, page$frame_bb)
  roads <- road_points(layers$roads_out)
  ticks <- bind_rows(
    grat |> mutate(kind = "grat"),
    survey$ticks |> mutate(kind = "survey")
  )
  labels <- bind_rows(
    grat |> mutate(kind = "grat", tier = 1, priority = 0, km = 0),
    survey$labels |> mutate(kind = "survey", tier = 1, priority = 1, km = 0),
    roads |> mutate(kind = "road", tier = 2, priority = 2)
  )
  placed <- place_collar(labels, page)
  c(collar_ticks(ticks, page), road_arrows(filter(placed, kind == "road"), page), collar_text(placed, page))   # no arrow without its note
}

# Where each 15-minute meridian meets the top and bottom of the frame, and each parallel the
# sides, with the direction of the line there (unit vector, outward)
graticule_points <- function(page) {
  bb <- page$frame_bb
  crs <- paste0("EPSG:", DISPLAY_CRS)
  steps <- \(lo, hi) seq(ceiling(lo / GRAT_STEP_DEG) * GRAT_STEP_DEG, hi, by = GRAT_STEP_DEG)
  meet <- function(value, is_lon, at_edge) {
    t <- seq(-1.5, 1.5, by = 0.0005)
    ll <- if (is_lon) cbind(value, mean(FRAME_LL[c("ymin", "ymax")]) + t)
          else cbind(mean(FRAME_LL[c("xmin", "xmax")]) + 2 * t, value)
    xy <- sf_project("EPSG:4326", crs, ll)
    k <- if (is_lon) which.min(abs(xy[, 2] - at_edge)) else which.min(abs(xy[, 1] - at_edge))
    d <- xy[min(k + 1, nrow(xy)), ] - xy[max(k - 1, 1), ]
    c(pos = if (is_lon) xy[k, 1] else xy[k, 2], dx = d[1] / sqrt(sum(d^2)), dy = d[2] / sqrt(sum(d^2)))
  }
  lon <- steps(FRAME_LL[["xmin"]], FRAME_LL[["xmax"]])
  lat <- steps(FRAME_LL[["ymin"]], FRAME_LL[["ymax"]])
  rows <- list()
  for (v in lon) {
    for (edge in c("top", "bottom")) {
      p <- meet(v, TRUE, if (edge == "top") bb[["ymax"]] else bb[["ymin"]])
      s <- if (edge == "top") 1 else -1
      rows[[length(rows) + 1]] <- tibble::tibble(edge = edge, along = p[["pos"]], dx = s * p[["dx"]],
                                                 dy = s * p[["dy"]], label = dms(v))
    }
  }
  for (v in lat) {
    for (edge in c("left", "right")) {
      p <- meet(v, FALSE, if (edge == "right") bb[["xmax"]] else bb[["xmin"]])
      s <- if (edge == "right") 1 else -1
      rows[[length(rows) + 1]] <- tibble::tibble(edge = edge, along = p[["pos"]], dx = s * p[["dx"]],
                                                 dy = s * p[["dy"]], label = dms(v))
    }
  }
  bind_rows(rows)
}

dms <- function(v) {
  deg <- floor(abs(v) + 1e-9)
  mins <- round((abs(v) - deg) * 60)
  if (mins == 0) sprintf("%d°%02d'", deg, mins) else sprintf("%02d'", mins)
}

# Township rows (left, right) and range columns (top, bottom) along each edge: a tick where
# one ends and the next begins, a label at the middle of each
survey_points <- function(plss, bb) {
  empty <- list(ticks = NULL, labels = NULL)
  if (is.null(plss)) return(empty)
  t <- st_transform(plss, DISPLAY_CRS)
  sides <- list(
    left = rbind(c(bb[["xmin"]], bb[["ymin"]]), c(bb[["xmin"]], bb[["ymax"]])),
    right = rbind(c(bb[["xmax"]], bb[["ymin"]]), c(bb[["xmax"]], bb[["ymax"]])),
    top = rbind(c(bb[["xmin"]], bb[["ymax"]]), c(bb[["xmax"]], bb[["ymax"]])),
    bottom = rbind(c(bb[["xmin"]], bb[["ymin"]]), c(bb[["xmax"]], bb[["ymin"]]))
  )
  out <- imap(sides, \(xy, edge) {
    vertical <- edge %in% c("left", "right")
    line <- st_sfc(st_linestring(xy), crs = DISPLAY_CRS)
    hit <- suppressWarnings(st_intersection(t, line))
    hit <- hit[st_geometry_type(hit) %in% c("LINESTRING", "MULTILINESTRING"), ]   # a corner touch is a point
    if (nrow(hit) == 0) return(NULL)
    coords <- st_coordinates(hit)
    pos <- if (vertical) coords[, "Y"] else coords[, "X"]
    feat <- coords[, ncol(coords)]   # the feature each vertex belongs to
    key <- if (vertical) paste0("T. ", as.integer(hit$TWNSHPNO), " ", hit$TWNSHPDIR, ".")
           else paste0("R. ", as.integer(hit$RANGENO), " ", hit$RANGEDIR, ".")
    spans <- tibble::tibble(label = key[feat], pos = pos) |>
      group_by(label) |>
      summarise(lo = min(pos), hi = max(pos), .groups = "drop")
    ends <- range(if (vertical) xy[, 2] else xy[, 1])
    cuts <- sort(unique(round(c(spans$lo, spans$hi))))
    cuts <- cuts[cuts > ends[1] + 500 & cuts < ends[2] - 500]
    out_dir <- switch(edge, left = c(-1, 0), right = c(1, 0), top = c(0, 1), bottom = c(0, -1))
    list(
      ticks = tibble::tibble(edge = edge, along = cuts, dx = out_dir[1], dy = out_dir[2]),
      labels = spans |> filter(hi - lo > 4000) |>          # partial rows at the corners: no label
        transmute(edge = edge, along = (lo + hi) / 2, label)
    )
  })
  list(ticks = map(out, "ticks") |> bind_rows(), labels = map(out, "labels") |> bind_rows())
}

road_points <- function(roads_out) {
  if (is.null(roads_out) || nrow(roads_out) == 0) return(NULL)
  roads_out |>
    arrange(km) |>
    distinct(edge, town, .keep_all = TRUE) |>   # two roads to one town on one edge: the nearer
    transmute(edge, along = if_else(edge %in% c("left", "right"), y, x), km,
              label = paste0(toupper(town), " ", miles, " MI."))
}

# Size of each label along its edge and out from it, in mm. Road notes on the sides run along
# the edge, as on the sheets; everything else is upright.
label_extent <- function(labels) {
  fam <- if_else(labels$kind == "road", "jostit", "jost")
  pt <- COLLAR_PT[labels$kind]
  w <- pmap_dbl(list(labels$label, fam, pt), text_w_mm)
  h <- pt * 0.3528 * 0.95
  side <- labels$edge %in% c("left", "right")
  along_road <- side & labels$kind == "road"
  labels |> mutate(
    family = fam, pt = pt,
    angle = case_when(along_road & edge == "left" ~ 90, along_road & edge == "right" ~ -90, TRUE ~ 0),
    ext = if_else(side & !along_road, h, w),
    depth = if_else(side & !along_road, w, h)
  )
}

# Greedy placement per edge and tier; returns the labels kept, with `at` (along the edge, map m)
place_collar <- function(labels, page) {
  bb <- page$frame_bb
  m <- page$m
  labels <- label_extent(labels) |> arrange(priority, km)
  ends <- \(edge) if (edge %in% c("left", "right")) c(bb[["ymin"]], bb[["ymax"]]) else c(bb[["xmin"]], bb[["xmax"]])
  taken <- list()
  keep <- rep(NA_real_, nrow(labels))
  for (i in seq_len(nrow(labels))) {
    e <- labels$edge[i]
    key <- paste(e, labels$tier[i])
    half <- (labels$ext[i] + PAD_MM) * m / 2
    lim <- ends(e) + c(-1, 1) * (if (labels$kind[i] == "grat") 6 else -CORNER_MM) * m
    slides <- if (labels$kind[i] == "road") SLIDE_MM else 0
    for (dz in slides) {
      at <- labels$along[i] + dz * m
      if (at - half < lim[1] || at + half > lim[2]) next
      if (any(map_lgl(taken[[key]], \(r) at + half > r[1] && at - half < r[2]))) next
      keep[i] <- at
      taken[[key]] <- c(taken[[key]], list(c(at - half, at + half)))
      break
    }
    if (labels$kind[i] == "grat" && is.na(keep[i])) keep[i] <- labels$along[i]   # always printed
  }
  labels |> mutate(at = keep) |> filter(!is.na(at))
}

collar_ticks <- function(ticks, page) {
  bb <- page$frame_bb
  t <- ticks |>
    mutate(
      x = case_when(edge == "left" ~ bb[["xmin"]], edge == "right" ~ bb[["xmax"]], TRUE ~ along),
      y = case_when(edge == "top" ~ bb[["ymax"]], edge == "bottom" ~ bb[["ymin"]], TRUE ~ along),
      len = TICK_MM[kind] * page$m,
      xend = x + dx * len, yend = y + dy * len,
      colour = if_else(kind == "grat", INK[["charcoal"]], INK[["graphite"]]),
      lw = if_else(kind == "grat", 0.35, 0.25)
    )
  list(geom_segment(data = t, aes(x = x, y = y, xend = xend, yend = yend, colour = colour, linewidth = lw),
                    inherit.aes = FALSE, show.legend = FALSE),
       scale_colour_identity(), scale_linewidth_identity())
}

# An arrow on each road at the neatline, pointing out of the map
road_arrows <- function(roads, page) {
  if (is.null(roads) || nrow(roads) == 0) return(NULL)
  bb <- page$frame_bb
  len <- TICK_MM[["arrow"]] * page$m
  a <- roads |>
    mutate(
      x = case_when(edge == "left" ~ bb[["xmin"]], edge == "right" ~ bb[["xmax"]], TRUE ~ along),
      y = case_when(edge == "top" ~ bb[["ymax"]], edge == "bottom" ~ bb[["ymin"]], TRUE ~ along),
      xend = x + case_when(edge == "left" ~ -len, edge == "right" ~ len, TRUE ~ 0),
      yend = y + case_when(edge == "top" ~ len, edge == "bottom" ~ -len, TRUE ~ 0)
    )
  list(geom_segment(data = a, aes(x = x, y = y, xend = xend, yend = yend), inherit.aes = FALSE,
                    colour = INK[["charcoal"]], linewidth = 0.3,
                    arrow = grid::arrow(length = grid::unit(0.9, "mm"), type = "closed")))
}

collar_text <- function(placed, page) {
  bb <- page$frame_bb
  m <- page$m
  tier_mm <- \(edge, tier) if (tier == 2 && edge %in% c("top", "bottom")) TIER2_TB_MM else TIER_MM[[as.character(tier)]]
  t <- placed |>
    mutate(
      d = map2_dbl(edge, tier, tier_mm) * m,
      x = case_when(edge == "left" ~ bb[["xmin"]] - d, edge == "right" ~ bb[["xmax"]] + d, TRUE ~ at),
      y = case_when(edge == "top" ~ bb[["ymax"]] + d, edge == "bottom" ~ bb[["ymin"]] - d, TRUE ~ at),
      hjust = case_when(angle != 0 ~ 0.5, edge == "left" ~ 1, edge == "right" ~ 0, TRUE ~ 0.5),
      vjust = case_when(angle != 0 ~ 0, edge == "top" ~ 0, edge == "bottom" ~ 1, TRUE ~ 0.5),
      colour = case_when(kind == "grat" ~ INK[["charcoal"]], kind == "road" ~ INK[["charcoal"]],
                         TRUE ~ INK[["graphite"]])
    )
  pmap(select(t, x, y, label, family, pt, colour, hjust, vjust, angle),
       \(x, y, label, family, pt, colour, hjust, vjust, angle) {
         annotate("text", x = x, y = y, label = label, family = family, size = pt_to_mm(pt),
                  colour = colour, hjust = hjust, vjust = vjust, angle = angle)
       })
}

# ---- Page text ----------------------------------------------------------------------------

# Text placed in page millimetres
text_mm <- function(page, x_mm, y_mm, label, pt, family, colour = INK[["charcoal"]],
                    hjust = 0, vjust = 1, lineheight = 1, angle = 0) {
  at <- page$at(x_mm, y_mm)
  annotate("text", x = at[1], y = at[2], label = label, family = family, size = pt_to_mm(pt),
           colour = colour, hjust = hjust, vjust = vjust, lineheight = lineheight, angle = angle)
}

seg_mm <- function(page, x, y, xend, yend, colour = INK[["charcoal"]], lw = 0.3, linetype = "solid") {
  a <- page$at(x, y)
  b <- page$at(xend, yend)
  annotate("segment", x = a[1], y = a[2], xend = b[1], yend = b[2], colour = colour,
           linewidth = lw, linetype = linetype)
}

rect_mm <- function(page, x0, y0, x1, y1, fill = NA, colour = INK[["charcoal"]], lw = 0.3) {
  a <- page$at(x0, y0)
  b <- page$at(x1, y1)
  annotate("rect", xmin = a[1], xmax = b[1], ymin = b[2], ymax = a[2], fill = fill, colour = colour,
           linewidth = lw)
}

draw_title <- function(page) {
  l <- page$left_mm - COLLAR_MM
  list(
    text_mm(page, l, 12, "DAY 7  ·  10 MINUTE MAP  ·  #30DAYMAPCHALLENGE", 7.5, "jost", INK[["graphite"]]),
    text_mm(page, l, 17, "Ten Minutes in April, 1962", 34, "elite"),
    text_mm(page, l, 32, "A geography of Blowin' in the Wind", 17, "caveat", INK[["suede"]])
  )
}

# ---- Under the map: the 1958 collar -------------------------------------------------------
# Left: the 1958 legend centred over what this map adds, then the song, then the production
# note. Right: the scales and notes, the declination, location diagram and sectionized
# township, then the land and the data credits. No imprint line (GW 11-16 markup).
LOWER_GAP_MM <- 4
LEGEND_SCALE <- 0.66      # the 1958 legend at this share of its printed size
ADDED_W_MM <- 126         # width of the ADDED IN 2026 legend
LEGEND_SRC_MM <- c(w = 1780, h = 700) / 300 * 25.4   # step 14's window, at 300 dpi

draw_lower_collar <- function(page, layers, variant) {
  l <- page$left_mm - COLLAR_MM
  r <- page$right_mm + COLLAR_MM
  top <- page$map_bottom_mm + COLLAR_MM + LOWER_GAP_MM
  leg_w <- LEGEND_SRC_MM[["w"]] * LEGEND_SCALE
  leg_h <- LEGEND_SRC_MM[["h"]] * LEGEND_SCALE
  leg_x <- l + (ADDED_W_MM - leg_w) / 2
  scale_x <- l + ADDED_W_MM + 4
  row2 <- top + leg_h + 4
  c(
    legend_1958(page, leg_x, top, leg_w, leg_h),
    scale_block(page, scale_x, top, r - scale_x),
    added_legend(page, l, row2, ADDED_W_MM, variant, layers),
    declination_block(page, l + 130, row2, 54),
    location_diagram(page, layers, l + 190, row2, 38),
    section_diagram(page, r - 26, row2, 26),
    story(page, l, row2 + 38, r - l)
  )
}

CREDIT_TEXT <- paste(
  "Drawn by Graham Watt with Claude Code (Anthropic), 2026, from a design drafted with Gemini (Google).",
  "The base is the four USGS 1:250,000 sheets Duluth, Ashland, Hibbing and Two Harbors, 1958 (Army Map",
  "Service; compiled in 1955 from 1953 aerial photography), redrawn from their own inks. Latitude and",
  "longitude ticks every 15 minutes, NAD 1983 (the sheets: NAD 1927)."
)

legend_1958 <- function(page, x, y, w, h) {
  img <- compose_legend()
  if (is.null(img)) return(NULL)
  a <- page$at(x, y)
  b <- page$at(x + w, y + h)
  list(annotation_raster(img, a[1], b[1], b[2], a[2], interpolate = TRUE),
       text_mm(page, x + w / 2, y + h + 0.6, "LEGEND OF THE 1958 SHEETS (DULUTH SHEET)",
               4.8, "jost", INK[["graphite"]], hjust = 0.5))
}

# Scale bars in the sheets' manner: two thin rules, every other division filled; a short
# extension left of zero in single units
scale_bar <- function(page, x0, y, unit_m, main, step, left, unit_label, pt = 6.5) {
  mm <- unit_m / page$m
  h <- 0.9
  out <- list()
  segs <- c(seq(-left, -1, by = 1), seq(0, main - step, by = step))
  ends <- c(seq(-left + 1, 0, by = 1), seq(step, main, by = step))
  for (i in seq_along(segs)) {
    xa <- x0 + segs[i] * mm
    xb <- x0 + ends[i] * mm
    filled <- (i %% 2 == 1)
    out <- c(out, list(rect_mm(page, xa, y, xb, y + h, fill = if (filled) INK[["charcoal"]] else NA, lw = 0.2)))
  }
  ticks <- c(-left, 0, seq(step, main, by = step))
  out <- c(out, map(ticks, \(t) text_mm(page, x0 + t * mm, y - 0.6, format(abs(t)), pt, "jost",
                                        hjust = 0.5, vjust = 0)))
  c(out, list(text_mm(page, x0 + main * mm + 2, y - 0.6, unit_label, pt, "jost", vjust = 0)))
}

scale_block <- function(page, x, y, w) {
  mi <- 1609.344
  nmi <- 1852
  cx <- x + w / 2
  x0 <- x + 14
  c(
    list(text_mm(page, cx, y + 1, paste0("Scale 1:", format(page$scale, big.mark = ",")), 9, "jost",
                 hjust = 0.5)),
    scale_bar(page, x0, y + 9.5, mi, 25, 5, 5, "Statute Miles"),
    scale_bar(page, x0, y + 16.5, nmi, 20, 5, 5, "Nautical Miles"),
    list(
      text_mm(page, cx, y + 22, "CONTOUR INTERVAL 50 FEET", 7.5, "jost", hjust = 0.5),
      text_mm(page, cx, y + 26, "WITH SUPPLEMENTARY CONTOURS AT 25 FOOT INTERVALS", 7.5, "jost", hjust = 0.5),
      text_mm(page, cx, y + 30.5, "TRANSVERSE MERCATOR PROJECTION", 7.5, "jost", hjust = 0.5),
      text_mm(page, cx, y + 34.5, "(UTM ZONE 15, NORTH AMERICAN DATUM 1983)", 6, "jost", INK[["graphite"]],
              hjust = 0.5)
    )
  )
}

# What this map adds to the 1958 sheets: one row per mark, symbol then words
added_legend <- function(page, x, y, w, variant, layers) {
  pt <- 6.2
  col_w <- w / 2
  row_h <- 6
  items <- list(
    list("pits", "Iron pits of the Mesabi, as mapped in 2026 (OpenStreetMap)"),
    list("divide", "Continental divide (USGS Watershed Boundary Dataset)"),
    list("triple", "Where the three drainages meet"),
    list("dove", "Mourning dove, an April record, 1981–2026 (GBIF)"),
    list("waves", "Waves of 10–16 April 1962, estimated from the ERA5 wind and the fetch"),
    list("rose", "Wind of April 1962 at Duluth: share of hours by direction, at 33 ft (filled) and 10,000 ft"),
    list("road", "Where a road leaves the map: miles to the next town"),
    list("survey", "Township and range, Public Land Survey"),
    if (nrow(layers$wetlands) > 0) list("wetland", "Wetlands of 10 acres and more, National Wetlands Inventory (modern)") else NULL,
    if (variant == "B") list("memorial", "Clayton-Jackson-McGhie Memorial") else NULL
  ) |> compact()
  out <- list(text_mm(page, x, y, "ADDED IN 2026", 7.5, "jost"))
  for (i in seq_along(items)) {
    col <- (i - 1) %/% 5
    row <- (i - 1) %% 5
    sx <- x + col * col_w
    sy <- y + 5 + row * row_h
    out <- c(out, legend_symbol(page, items[[i]][[1]], sx, sy, layers),
             list(text_mm(page, sx + 11, sy + 1.6, wrap_mm(items[[i]][[2]], "jost", pt, col_w - 13), pt, "jost",
                          vjust = 0.5, lineheight = 1.05)))
  }
  out
}

# A small symbol in a 9 x 3.2 mm box at (x, y), top-left
legend_symbol <- function(page, kind, x, y, layers) {
  cy <- y + 1.6
  at <- page$at
  switch(kind,
    wetland = {
      a <- at(x, y + 0.2)
      b <- at(x + 9, y + 3.0)
      list(annotate("rect", xmin = a[1], xmax = b[1], ymin = b[2], ymax = a[2],
                    fill = INK[["water"]], alpha = BLEND$wetland$max, colour = NA))
    },
    pits = {
      a <- at(x, y + 0.2)
      b <- at(x + 9, y + 3.0)
      box <- st_sfc(st_polygon(list(rbind(c(a[1], a[2]), c(b[1], a[2]), c(b[1], b[2]), c(a[1], b[2]), c(a[1], a[2])))),
                    crs = DISPLAY_CRS)
      pit_marks(box, page)
    },
    divide = list(seg_mm(page, x, cy, x + 9, cy, lw = 0.45 * K, linetype = "42")),
    triple = {
      p <- at(x + 4.5, cy)
      list(annotate("point", x = p[1], y = p[2], shape = 21, size = 2.6 * K, stroke = 0.6 * K,
                    fill = INK[["paper"]], colour = INK[["charcoal"]]),
           annotate("point", x = p[1], y = p[2], size = 0.7 * K, colour = INK[["charcoal"]]))
    },
    dove = {
      p <- rbind(at(x + 2, cy), at(x + 4.5, cy - 0.6), at(x + 7, cy + 0.4))
      list(annotate("point", x = p[, 1], y = p[, 2], shape = 21, size = 0.55 * K, stroke = 0.12 * K,
                    fill = INK[["dove"]], colour = INK[["charcoal"]]))
    },
    waves = map(c(-0.8, 0, 0.8), \(k) seg_mm(page, x + 2.5 + k, cy - 1.1, x + 6.5 + k, cy + 1.1,
                                             colour = INK[["graphite"]], lw = 0.18 * K)),
    rose = {
      c0 <- at(x + 4.5, cy)
      rose <- layers$rose
      petals <- rose_petals(rose, c0, 2.4 * page$m / max(rose$share))
      list(geom_polygon(data = petals |> filter(level == "10m"), aes(x, y, group = id),
                        fill = INK[["suede"]], alpha = 0.75, inherit.aes = FALSE),
           geom_polygon(data = petals |> filter(level != "10m"), aes(x, y, group = id),
                        fill = NA, colour = INK[["charcoal"]], linewidth = 0.2, inherit.aes = FALSE))
    },
    road = {
      a <- at(x + 1, cy)
      b <- at(x + 4, cy)
      list(annotate("segment", x = a[1], y = a[2], xend = b[1], yend = b[2], colour = INK[["charcoal"]],
                    linewidth = 0.3, arrow = grid::arrow(length = grid::unit(0.9, "mm"), type = "closed")),
           text_mm(page, x + 4.6, cy, "9 MI.", 5.5, "jostit", vjust = 0.5))
    },
    survey = list(text_mm(page, x, cy, "T. 52 N.", 5.5, "jost", INK[["graphite"]], vjust = 0.5)),
    memorial = {
      p <- at(x + 4.5, cy)
      list(annotate("point", x = p[1], y = p[2], shape = 22, size = 1.3 * K, stroke = 0.45 * K,
                    fill = INK[["paper"]], colour = INK[["charcoal"]]))
    }
  )
}

# April 1962 declination at the centre of the frame's west and east edges, from the 1955
# values and annual changes printed on the four sheets (config.R), interpolated linearly
declination_1962 <- function(lon, lat) {
  years <- DECLINATION_AT - DECLINATION_EPOCH
  d <- DECLINATION_1955 |>
    mutate(west = west_deg + change_min / 60 * years, east = east_deg + change_min / 60 * years)
  # for each of the two latitude rows, interpolate along the row of sheets in longitude
  row_value <- function(row_lat) {
    s <- d |> filter(lat == row_lat) |> arrange(lon_west)
    xs <- c(s$lon_west, max(s$lon_west) + 2)
    ys <- c(s$west, s$east[nrow(s)])
    # inner edges: the two sheets agree there (checked on the scans: 4 00 and 3 45 E)
    stats::approx(xs, ys, xout = lon)$y
  }
  rows <- sort(unique(d$lat))
  v <- map_dbl(rows, row_value)
  stats::approx(rows, v, xout = lat, rule = 2)$y
}

deg_min <- function(x) {   # whole minutes first, so 3°59.7' prints 4°00'; an apostrophe, as Jost has no prime
  mins <- round(x * 60)
  sprintf("%d°%02d'", mins %/% 60, mins %% 60)
}

declination_block <- function(page, x, y, w) {
  mid_lat <- mean(FRAME_LL[c("ymin", "ymax")])
  west <- declination_1962(FRAME_LL[["xmin"]], mid_lat)
  east <- declination_1962(FRAME_LL[["xmax"]], mid_lat)
  mean_dec <- declination_1962(mean(FRAME_LL[c("xmin", "xmax")]), mid_lat)
  bb <- page$frame_bb
  centre <- c(mean(c(bb[["xmin"]], bb[["xmax"]])), mean(c(bb[["ymin"]], bb[["ymax"]])))
  true_n <- true_north_deg(centre, DISPLAY_CRS)
  note <- paste0("APRIL 1962 MAGNETIC DECLINATION FOR THIS MAP VARIES FROM ", deg_min(west),
                 " EASTERLY FOR THE CENTER OF THE WEST EDGE TO ", deg_min(east),
                 " EASTERLY FOR THE CENTER OF THE EAST EDGE, FROM THE 1955 VALUES AND ANNUAL CHANGES",
                 " PRINTED ON THE FOUR SHEETS.")
  # diagram: true north (star) and magnetic north (half arrow), from a base point
  base <- c(x + 8, y + 24)
  len <- 18
  ray <- \(ang) base + len * c(sin(ang * pi / 180), -cos(ang * pi / 180))
  tn <- ray(true_n)
  mn <- ray(true_n + mean_dec)
  star <- star_points(page, tn + c(0, -1.6), 1.3)
  list(
    seg_mm(page, base[1], base[2], tn[1], tn[2], lw = 0.35),
    seg_mm(page, base[1], base[2], mn[1], mn[2], lw = 0.35),
    geom_polygon(data = star, aes(x, y), fill = INK[["charcoal"]], inherit.aes = FALSE),
    text_mm(page, mn[1] + 0.8, mn[2] + 1.5, "MN", 6, "jost", vjust = 0.5),
    text_mm(page, base[1] + 3, base[2] - 4, deg_min(mean_dec), 6, "jost", vjust = 0.5),
    text_mm(page, x + 16, y + 5, wrap_mm(note, "jost", 5.4, w - 16), 5.4, "jost", lineheight = 1.15),
    text_mm(page, x + 16, y, "MEAN DECLINATION, APRIL 1962", 6, "jost")
  )
}

star_points <- function(page, at_mm, r_mm) {
  th <- seq(0, 2 * pi, length.out = 11)[-11] - pi / 2
  rr <- rep(c(r_mm, r_mm * 0.42), 5)
  xy <- map(seq_along(th), \(i) page$at(at_mm[1] + rr[i] * cos(th[i]), at_mm[2] + rr[i] * sin(th[i]))) |>
    reduce(rbind)
  tibble::tibble(x = xy[, 1], y = xy[, 2])
}

# The four 1958 sheets and this map's frame among their neighbours, as the sheets' own
# location diagram drew them
LOCATION_LL <- c(xmin = -98, xmax = -88, ymin = 44, ymax = 49.5)
SHEET_IDS <- tibble::tribble(
  ~name,          ~id,       ~xmin, ~ymin,
  "HIBBING",      "NL 15-2", -94,   47,
  "TWO HARBORS",  "NL 15-3", -92,   47,
  "DULUTH",       "NL 15-5", -94,   46,
  "ASHLAND",      "NL 15-6", -92,   46
)

location_diagram <- function(page, layers, x, y, w) {
  kx <- w / (LOCATION_LL[["xmax"]] - LOCATION_LL[["xmin"]])
  ky <- kx / cos(46.75 * pi / 180)
  h <- ky * (LOCATION_LL[["ymax"]] - LOCATION_LL[["ymin"]])
  top <- y + 5
  to_map <- \(lon, lat) {
    xm <- x + (lon - LOCATION_LL[["xmin"]]) * kx
    ym <- top + (LOCATION_LL[["ymax"]] - lat) * ky
    t(mapply(\(a, b) page$at(a, b), xm, ym))
  }
  poly_df <- function(sfc, group_prefix) {
    sfc <- suppressWarnings(st_cast(st_collection_extract(sfc, "POLYGON"), "POLYGON"))
    co <- st_coordinates(sfc)
    xy <- to_map(co[, 1], co[, 2])
    # L2 is the polygon, L1 its ring: rings after the first are holes (islands), drawn as subgroups
    tibble::tibble(x = xy[, 1], y = xy[, 2], g = paste(group_prefix, co[, "L2"]), ring = co[, "L1"])
  }
  out <- list(text_mm(page, x, y, "LOCATION DIAGRAM", 7, "jost"))
  s2 <- suppressMessages(sf_use_s2(FALSE))       # crop in plain lon/lat, not on the sphere
  on.exit(suppressMessages(sf_use_s2(s2)), add = TRUE)
  crop_ll <- \(x) suppressWarnings(st_crop(st_make_valid(x), st_bbox(LOCATION_LL, crs = 4326)))
  lake <- crop_ll(layers$lake_whole)   # the lake runs on east past the diagram
  if (!is.null(layers$states)) {
    states <- crop_ll(layers$states)
    out <- c(out, list(geom_polygon(data = poly_df(st_geometry(states), "s"), aes(x, y, group = g, subgroup = ring),
                                    fill = NA, colour = INK[["graphite"]], linewidth = 0.18, inherit.aes = FALSE)))
  }
  out <- c(out, list(geom_polygon(data = poly_df(st_geometry(lake), "lake"), aes(x, y, group = g, subgroup = ring),
                                  fill = INK[["water"]], alpha = 0.6, colour = NA, inherit.aes = FALSE)))
  # the sheet grid, 2 degrees by 1
  for (lon in seq(LOCATION_LL[["xmin"]], LOCATION_LL[["xmax"]], by = 2)) {
    p <- to_map(c(lon, lon), c(LOCATION_LL[["ymin"]], 49))
    out <- c(out, list(annotate("segment", x = p[1, 1], y = p[1, 2], xend = p[2, 1], yend = p[2, 2],
                                colour = INK[["charcoal"]], linewidth = 0.18)))
  }
  for (lat in seq(LOCATION_LL[["ymin"]], 49, by = 1)) {
    p <- to_map(c(LOCATION_LL[["xmin"]], LOCATION_LL[["xmax"]]), c(lat, lat))
    out <- c(out, list(annotate("segment", x = p[1, 1], y = p[1, 2], xend = p[2, 1], yend = p[2, 2],
                                colour = INK[["charcoal"]], linewidth = 0.18)))
  }
  for (i in seq_len(nrow(SHEET_IDS))) {
    s <- SHEET_IDS[i, ]
    p <- to_map(s$xmin + 1, s$ymin + 0.5)
    out <- c(out, list(annotate("text", x = p[1, 1], y = p[1, 2], label = paste0(s$id, "\n", s$name),
                                family = "jost", size = pt_to_mm(3.6), colour = INK[["charcoal"]],
                                lineheight = 0.95)))
  }
  f <- to_map(FRAME_LL[c("xmin", "xmax", "xmax", "xmin", "xmin")], FRAME_LL[c("ymin", "ymin", "ymax", "ymax", "ymin")])
  out <- c(out, list(annotate("path", x = f[, 1], y = f[, 2], colour = INK[["rust"]], linewidth = 0.6)))
  out <- c(out, list(rect_mm(page, x, top, x + w, top + h, lw = 0.25),
                     text_mm(page, x + w * 0.62, top + 1.2, "CANADA", 4.5, "jost", INK[["graphite"]]),
                     text_mm(page, x, top + h + 0.8,
                             paste0(LOCATION_LL[["ymin"]], "° N, ", -LOCATION_LL[["xmin"]], "° W"),
                             4.5, "jost", INK[["graphite"]]),
                     text_mm(page, x + w, top + h + 0.8, "THIS MAP IN RUST", 4.5, "jost", INK[["rust"]],
                             hjust = 1)))
  out
}

# The sectionized township, numbered as the survey numbers it, as on the sheets
section_diagram <- function(page, x, y, w) {
  cell <- w / 6
  top <- y + 5
  nums <- c(6:1, 7:12, 18:13, 19:24, 30:25, 31:36)
  out <- list(text_mm(page, x + w / 2, y, "SECTIONIZED TOWNSHIP", 6.5, "jost", hjust = 0.5))
  for (k in 1:5) {
    out <- c(out, list(seg_mm(page, x + k * cell, top, x + k * cell, top + w, lw = 0.2, linetype = "11"),
                       seg_mm(page, x, top + k * cell, x + w, top + k * cell, lw = 0.2, linetype = "11")))
  }
  for (i in seq_along(nums)) {
    r <- (i - 1) %/% 6
    c <- (i - 1) %% 6
    out <- c(out, list(text_mm(page, x + (c + 0.5) * cell, top + (r + 0.5) * cell, nums[i], 6, "jost",
                               hjust = 0.5, vjust = 0.5)))
  }
  c(out, list(rect_mm(page, x, top, x + w, top + w, lw = 0.4)))
}

# The story of the map, below the collar, in two columns: the song and its weather; the land,
# then the data credits
STORY_PT <- 8.6
story <- function(page, x, y, w) {
  song <- paste(
    "Dylan said he wrote \u201cBlowin\u2019 in the Wind\u201d in ten minutes, in a Greenwich Village caf\u00e9 in April 1962,",
    "setting new words to \u201cNo More Auction Block\u201d. This is the land he came from, Duluth to Hibbing, as the",
    "four USGS sheets of 1958 drew it, with the wind and the waves of that April. At the surface the wind came from",
    "every side; 10,000 feet up it held from the west and north-west. The waves are the week of 10 to 16 April, when",
    "he first sang the song at Gerde\u2019s Folk City: no wave record exists for that week, so they are estimated from",
    "the wind and the fetch across the lake, and any ice is unknown."
  )
  land <- paste(
    "This is Anishinaabe (Ojibwe) land, ceded to the United States by treaty in 1842 (Superior and the Wisconsin",
    "shore), 1854 (Duluth, Cloquet and the Arrowhead) and 1855 (Hibbing and the country west of Chisholm). The",
    "Fond du Lac Reservation, reserved in the 1854 treaty, lies inside this map. The roads are those of 1958:",
    "US 61 along the North Shore became MN 61 in 1991, and the interstate came later."
  )
  gap <- 8
  col_w <- (w - gap) / 2
  col1 <- wrap_mm(song, "garamond", STORY_PT, col_w)
  col2 <- wrap_mm(land, "garamond", STORY_PT, col_w)
  data <- paste(
    "Data: USGS Historical Topographic Map Collection; USGS Watershed Boundary Dataset; NOAA NCEI Great Lakes",
    "Bathymetry; AWS Terrain Tiles; ERA5 (Copernicus Climate Change Service), via the CDS and Open-Meteo (CC BY 4.0);",
    "GBIF.org (16 Nov 2026), derived dataset https://doi.org/10.15468/dd.8w6ahv; \u00a9 OpenStreetMap contributors",
    "(ODbL); BLM PLSS CadNSDI; USFWS National Wetlands Inventory. Map CC BY 4.0, code MIT."
  )
  small <- 6.8
  # Height of a wrapped block: lines x pt x line height; 1.14 measured on the 11-16 render
  block_h <- function(txt, pt) length(strsplit(txt, "\n")[[1]]) * pt * 0.3528 * 1.1 * 1.14
  credit <- wrap_mm(CREDIT_TEXT, "garamond", small, col_w)
  data <- wrap_mm(data, "garamond", small, col_w)
  credit_y <- y + block_h(col1, STORY_PT) + 3.5
  bottom <- credit_y + block_h(credit, small)
  data_y <- max(y + block_h(col2, STORY_PT) + 1.5, bottom - block_h(data, small))
  if (bottom > PAGE$h_mm - 3) warning(   # block_h runs high, so this is conservative
    "Lower collar runs to ", round(bottom, 1), " mm of ", PAGE$h_mm, call. = FALSE)
  list(
    text_mm(page, x, y, col1, STORY_PT, "garamond", lineheight = 1.1),
    text_mm(page, x + col_w + gap, y, col2, STORY_PT, "garamond", lineheight = 1.1),
    text_mm(page, x, credit_y, credit, small, "garamond", INK[["graphite"]], lineheight = 1.1),
    text_mm(page, x + col_w + gap, data_y, data, small, "garamond", INK[["graphite"]], lineheight = 1.1)
  )
}

# ---- Output -------------------------------------------------------------------------------

# Film grain over the whole page, PNG only (D305): one noise raster, about 150 per inch
grain_layer <- function(page, seed = 1963) {
  set.seed(seed)
  n <- c(round(PAGE$h_mm / 25.4 * 150), round(PAGE$w_mm / 25.4 * 150))
  a <- pmin(abs(stats::rnorm(prod(n), sd = 0.045)), 0.12)
  col <- col2rgb(INK[["charcoal"]])[, 1]
  grain <- matrix(grDevices::rgb(col[1], col[2], col[3], a * 255, maxColorValue = 255), n[1], n[2])
  annotation_raster(grain, page$xlim[1], page$xlim[2], page$ylim[1], page$ylim[2], interpolate = FALSE)
}

# Pixel positions of named places in the 300 dpi PNG, for step 04's crops
write_layout <- function(page, layers, path) {
  px <- function(xy) round(c((xy[1] - page$xlim[1]) / page$m, (page$ylim[2] - xy[2]) / page$m) / 25.4 * DPI)
  spots <- list(
    duluth = st_coordinates(layers$places[layers$places$id == "duluth", ])[1, 1:2],
    three_waters = st_coordinates(layers$three_waters)[1, 1:2]
  ) |> map(px)
  # Page pixels to map metres, for step 04's 1958 sample: x = x0 + px * m_per_px, y = y_top - py * m_per_px
  ground <- list(x0 = page$xlim[1], y_top = page$ylim[2], m_per_px = page$m * 25.4 / DPI,
                 map_left_px = round(page$left_mm / 25.4 * DPI))
  jsonlite::write_json(c(spots, list(page_px = round(c(PAGE$w_mm, PAGE$h_mm) / 25.4 * DPI), ground = ground)),
                       path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
}

save_pdf <- function(p, path) {
  grDevices::cairo_pdf(path, width = PAGE$w_mm / 25.4, height = PAGE$h_mm / 25.4)
  print(p)
  grDevices::dev.off()
}

save_png <- function(p, path) {
  grDevices::png(path, width = PAGE$w_mm / 25.4, height = PAGE$h_mm / 25.4, units = "in",
                 res = DPI, type = "cairo", bg = INK[["paper"]])
  print(p)
  grDevices::dev.off()
}

main()
