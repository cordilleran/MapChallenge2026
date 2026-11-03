# North arrow and scale bar for the static maps (style A, chosen 11-02, decision D48).
# The compass is the calendar's day-6 tile: a ring, an accent north half,
# an outlined south half, an "N".
# The scale bar is a ticked line at 0, 1/4, 1/2 and 1 of a round length, labelled in km.
# Both return lists of ggplot layers in map units; add them to a plot with `+`.
# Needs look.R (PALETTE, FONT) sourced first.

pt_to_mm <- function(points) points / ggplot2::.pt   # ggplot text size from points

# Angle of true north at a point, in degrees clockwise from grid up (negative leans left).
# Projects the point and one 0.01 deg north of it,
# then takes the bearing between them in the map grid.
true_north_deg <- function(at, crs) {
  here <- sf::st_sfc(sf::st_point(at), crs = crs)
  lonlat <- sf::st_coordinates(sf::st_transform(here, 4326))
  north <- sf::st_sfc(sf::st_point(lonlat + c(0, 0.01)), crs = 4326)
  step <- sf::st_coordinates(sf::st_transform(north, crs)) - at
  atan2(step[1], step[2]) * 180 / pi
}

# Icon points on a 24-unit grid (y down, as in the calendar's SVG) to map units,
# rotated about the icon centre.
icon_to_map <- function(pts, at, size_mm, angle_deg, m_per_mm) {
  unit <- size_mm / 24 * m_per_mm
  turn <- -angle_deg * pi / 180                          # clockwise on the page
  dx <- (pts$x - 12) * unit
  dy <- -(pts$y - 12) * unit   # flip y: the icon grid runs down, map y runs up
  # rule 9: compute both offsets before tibble(), which would let a new column x shadow a local one
  x_out <- at[1] + dx * cos(turn) - dy * sin(turn)
  y_out <- at[2] + dx * sin(turn) + dy * cos(turn)
  tibble::tibble(x = x_out, y = y_out)
}

ring_pts <- function(radius, n = 90) {
  theta <- seq(0, 2 * pi, length.out = n)
  tibble::tibble(x = 12 + radius * cos(theta), y = 12 + radius * sin(theta))
}

# Compass rose at `at` (map units), `size_mm` across,
# pointing to true north (`angle_deg`, from true_north_deg()).
compass_rose <- function(at, angle_deg, m_per_mm, size_mm = 13,
                         accent = PALETTE[["amber"]], ink = PALETTE[["ink"]],
                         mute = PALETTE[["mute"]], family = FONT[["mono"]]) {
  place <- function(pts) icon_to_map(pts, at, size_mm, angle_deg, m_per_mm)
  ring  <- place(ring_pts(9))
  north <- place(tibble::tibble(x = c(12, 14, 10), y = c(5, 12, 12)))
  south <- place(tibble::tibble(x = c(14, 12, 10, 14), y = c(12, 19, 12, 12)))
  label <- place(tibble::tibble(x = 12, y = -1.4))
  list(
    ggplot2::annotate("path", x = ring$x, y = ring$y, colour = mute, linewidth = .3),
    ggplot2::annotate("polygon", x = north$x, y = north$y, fill = accent, colour = accent,
                      linewidth = .2, linejoin = "round"),
    ggplot2::annotate("path", x = south$x, y = south$y, colour = ink, linewidth = .3,
                      linejoin = "round"),
    ggplot2::annotate("point", x = at[1], y = at[2], colour = ink, size = .5),
    ggplot2::annotate("text", x = label$x, y = label$y, label = "N", family = family,
                      size = pt_to_mm(5.4), colour = ink)
  )
}

# A round bar length in km, the largest of 1-2-5 steps that fits in `max_mm` of page.
nice_km <- function(m_per_mm, max_mm = 45) {
  steps <- as.vector(outer(c(1, 2, 5), 10^(-1:3)))
  fits <- steps[steps * 1000 / m_per_mm <= max_mm]
  stopifnot(length(fits) > 0)   # rule 11: a page this small would need a metre scale
  max(fits)
}

# Ticked scale bar from `at` (map units, the left end of the line);
# ticks at 0, 1/4, 1/2 and 1 of `km`.
scale_ticked <- function(at, m_per_mm, km = nice_km(m_per_mm),
                         ink = PALETTE[["ink"]], mute = PALETTE[["mute"]],
                         family = FONT[["mono"]]) {
  marks_km <- km * c(0, .25, .5, 1)
  x <- at[1] + marks_km * 1000
  tick <- 1.4 * m_per_mm
  gap <- 1.2 * m_per_mm
  labels <- format(marks_km, trim = TRUE, drop0trailing = TRUE)
  labels[marks_km %% 1 != 0] <- ""   # a fractional quarter (1.25) would crowd its neighbours
  list(
    ggplot2::annotate("segment", x = min(x), xend = max(x), y = at[2], yend = at[2],
                      colour = ink, linewidth = .35, lineend = "round"),
    ggplot2::annotate("segment", x = x, xend = x, y = at[2], yend = at[2] + tick,
                      colour = ink, linewidth = .3, lineend = "round"),
    ggplot2::annotate("text", x = x, y = at[2] - gap, label = labels, family = family,
                      size = pt_to_mm(4.6), colour = mute, vjust = 1),
    ggplot2::annotate("text", x = max(x) + 2 * m_per_mm, y = at[2] - gap, label = "km",
                      family = family, size = pt_to_mm(4.6), colour = mute, vjust = 1, hjust = 0)
  )
}
