#!/usr/bin/env Rscript
# Day 1 step 25: export the junction glyphs for the Leaflet map (site/data/day01_junctions.js).
#
# One row per junction (braid re-joins excluded):
#   [lat, lng, rises, outOrder, outMag, outBearing, outName, us, areaKm2, [inBearing, inOrder, inMag, inName, ...]]
# Names are indexes into DAY01_NAMES (-1 = unnamed). DAY01_MOUTH holds the last junction, where the Kettle meets the Columbia.
# Bearings are recomputed in Web Mercator (EPSG:3857), from the node to the point 150 m along each arm: the projection is
# conformal, so that angle is the angle on screen. The static maps use BC Albers grid bearings (about 5.7 degrees apart here).
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr); library(terra); library(igraph)})
source(file.path(.here, "lib_area.R"))
dir.create(SITE_DATA, FALSE, TRUE)
f <- file.path(SITE_DATA, "day01_junctions.js")                      # rewritten on every run (derived from the network files)
net <- file.path(DATA_DIR, paste0("network3dhp", TAG, ".gpkg"))

cf <- st_read(net, "confluences", quiet = TRUE); cf$conf <- seq_len(nrow(cf))
seg <- st_read(net, "segments", quiet = TRUE) |> st_drop_geometry()
arms <- read.csv(file.path(DATA_DIR, paste0("arms3dhp", TAG, "_mag.csv")))
mouth <- read.csv(file.path(DATA_DIR, paste0("mouth3dhp", TAG, "_mag.csv")))
# ---- upstream area at each junction, from the DEM flow accumulation (step 04) ----------------------------------------
# The largest accumulation within 60 m of the node, then never less than at any junction upstream, since area cannot
# shrink downstream (lib_area.R). Areas are shown per junction, not per arm: 25a_check_upstream_area.R shows why.
# Approximate; shown rounded on the map.
acc <- rast(file.path(DATA_DIR, "acc_area.tif")); crs(acc) <- "EPSG:3005"
cxy <- st_coordinates(cf)
up <- raise_downstream(area_near(acc, cxy[, 1], cxy[, 2]), next_junction(cf, seg))
area <- up$area; raised <- up$raised
cf$area <- area
cat(sprintf("upstream area: %d junctions raised to their upstream maximum; %d without a value; largest %.0f km2\n", raised, sum(is.na(area)), max(area, na.rm = TRUE)))

cf <- cf[!cf$braid, ]; arms <- arms[arms$conf %in% cf$conf, ]

mercator_bearing <- function(nx, ny, bx, by) {
  p0 <- st_coordinates(st_transform(st_as_sf(data.frame(x = nx, y = ny), coords = c("x", "y"), crs = 3005), 3857))
  p1 <- st_coordinates(st_transform(st_as_sf(data.frame(x = bx, y = by), coords = c("x", "y"), crs = 3005), 3857))
  round((atan2(p1[, 1] - p0[, 1], p1[, 2] - p0[, 2]) * 180 / pi) %% 360)
}
arms$brg <- mercator_bearing(arms$nx, arms$ny, arms$bx, arms$by)

# stream names: one table, each arm points into it
arms$name <- seg$name[match(arms$seg_id, seg$seg_id)]
names_tbl <- sort(unique(na.omit(arms$name)))
arms$ni <- ifelse(is.na(arms$name), -1L, match(arms$name, names_tbl) - 1L)

ll <- st_coordinates(st_transform(cf, 4326))
by_conf <- split(arms, arms$conf)
rows <- vapply(seq_len(nrow(cf)), function(i) {
  a <- by_conf[[as.character(cf$conf[i])]]
  o <- a[a$arm == "out", ][1, ]; inn <- a[a$arm == "in", ]
  sprintf("[%.5f,%.5f,%d,%d,%d,%d,%d,%d,%s,[%s]]", ll[i, 2], ll[i, 1], as.integer(cf$order_changes[i]), o$order, round(o$mag), o$brg, o$ni,
          as.integer(ll[i, 2] < 49), if (is.na(cf$area[i])) "null" else signif(cf$area[i], 3), paste(sprintf("%d,%d,%d,%d", inn$brg, inn$order, round(inn$mag), inn$ni), collapse = ","))
}, character(1))

# the last junction: Kettle arm(s) carry order and magnitude; the Columbia arms carry only a bearing
m_ll <- st_coordinates(st_transform(st_sfc(st_point(c(mouth$nx[1], mouth$ny[1])), crs = 3005), 4326))
far <- function(b) { r <- b * pi / 180; c(mouth$nx[1] + 150 * sin(r), mouth$ny[1] + 150 * cos(r)) }
tip <- t(sapply(mouth$bearing, far))
mouth$brg <- mercator_bearing(mouth$nx, mouth$ny, tip[, 1], tip[, 2])
mouth_area <- max(cf$area, na.rm = TRUE)
mouth_js <- sprintf("{lat:%.5f,lng:%.5f,area:%s,arms:[%s]}", m_ll[2], m_ll[1], signif(mouth_area, 3),
                    paste(sprintf("{kind:'%s',b:%d,o:%s,m:%s}", mouth$arm, mouth$brg, ifelse(is.na(mouth$order), "null", mouth$order),
                                  ifelse(is.na(mouth$mag), "null", round(mouth$mag))), collapse = ","))

bb <- st_bbox(st_transform(cf, 4326))
MMAX <- max(arms$mag[arms$arm == "out"], na.rm = TRUE); K <- log(4) / log(MMAX)   # same Shreve length rule as 24_final_static.R
esc <- function(s) gsub("'", "\\\\'", s)
writeLines(c(
  sprintf("// Day 1 junctions, %d rows. Fields: lat, lng, rises, outOrder, outMag, outBearing, outName, us, areaKm2 (DEM, approximate), [inBearing, inOrder, inMag, inName, ...]", length(rows)),
  "// Derived from the BC Freshwater Atlas (Province of British Columbia; contains information licensed under the Open Government Licence - British Columbia) and the USGS 3D Hydrography Program (public domain). Code MIT, maps CC BY 4.0: see the repository LICENSE files.",
  sprintf("window.DAY01_K=%.4f; window.DAY01_MAGMAX=%d;", K, round(MMAX)),
  sprintf("window.DAY01_BOUNDS=[[%.4f,%.4f],[%.4f,%.4f]];", bb["ymin"], bb["xmin"], bb["ymax"], bb["xmax"]),
  sprintf("window.DAY01_NAMES=[%s];", paste0("'", esc(names_tbl), "'", collapse = ",")),
  sprintf("window.DAY01_MOUTH=%s;", mouth_js),
  "window.DAY01_JUNCTIONS=[", paste(rows, collapse = ",\n"), "];"), f)
cat("junctions:", length(rows), " names:", length(names_tbl), " named arms:", round(100 * mean(arms$ni >= 0)), "%  file kB:", round(file.size(f) / 1024), "\n")
