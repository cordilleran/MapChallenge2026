# Day 1 step 25: export the junction glyph data for the Leaflet map (site/data/day01_junctions.js).
# One row per junction (braid re-joins excluded): [lat, lng, rises, outOrder, outMag, outBearing, us, [bearing, order, mag, ...inflows]].
# Bearings are recomputed in Web Mercator (EPSG:3857, conformal, so the angle on screen is the angle in 3857) from the node to the
# point 150 m along each arm; the static maps use BC Albers grid bearings (about 5.7 degrees different at this longitude).
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr)})
D <- DATA_DIR; OUT <- SITE_DATA; dir.create(OUT, FALSE, TRUE)
f <- file.path(OUT, "day01_junctions.js")      # rewritten on every run (derived from the network files)
cf <- st_read(file.path(D, paste0("network3dhp", TAG, ".gpkg")), "confluences", quiet = TRUE); cf$conf <- seq_len(nrow(cf))
arms <- read.csv(file.path(D, paste0("arms3dhp", TAG, "_mag.csv")))
keep <- cf$conf[!cf$braid]; arms <- arms[arms$conf %in% keep, ]
p0 <- st_transform(st_as_sf(arms, coords = c("nx", "ny"), crs = 3005), 3857) |> st_coordinates()
p1 <- st_transform(st_as_sf(arms, coords = c("bx", "by"), crs = 3005), 3857) |> st_coordinates()
arms$brg <- round((atan2(p1[, 1] - p0[, 1], p1[, 2] - p0[, 2]) * 180 / pi) %% 360)
nd <- st_transform(cf[cf$conf %in% keep, ], 4326); ll <- st_coordinates(nd)
J <- vector("list", nrow(nd)); sp <- split(arms, arms$conf)
for (i in seq_len(nrow(nd))) { a <- sp[[as.character(nd$conf[i])]]; o <- a[a$arm == "out", ][1, ]; inn <- a[a$arm == "in", ]
  J[[i]] <- sprintf("[%.5f,%.5f,%d,%d,%d,%d,%d,[%s]]", ll[i, 2], ll[i, 1], as.integer(nd$order_changes[i]), o$order, round(o$mag), o$brg, as.integer(ll[i, 2] < 49),
                    paste(sprintf("%d,%d,%d", inn$brg, inn$order, round(inn$mag)), collapse = ",")) }
bb <- st_bbox(nd); MMAX <- max(arms$mag[arms$arm == "out"], na.rm = TRUE); K <- log(4) / log(MMAX)   # same Shreve length rule as 24_final_static.R
writeLines(c(sprintf("// Day 1 junctions, %d rows. Fields: lat, lng, rises, outOrder, outMag, outBearing, us, [inBearing, inOrder, inMag, ...]", length(J)),
  "// Derived from the BC Freshwater Atlas (Province of British Columbia; contains information licensed under the Open Government Licence - British Columbia) and the USGS 3D Hydrography Program (public domain). Code MIT, maps CC BY 4.0: see the repository LICENSE files.",
  sprintf("window.DAY01_K=%.4f; window.DAY01_MAGMAX=%d;", K, round(MMAX)),
  sprintf("window.DAY01_BOUNDS=[[%.4f,%.4f],[%.4f,%.4f]];", bb["ymin"], bb["xmin"], bb["ymax"], bb["xmax"]),
  "window.DAY01_JUNCTIONS=[", paste(unlist(J), collapse = ",\n"), "];"), f)
cat("junctions:", length(J), " file kB:", round(file.size(f) / 1024), "\n")
cat("outflow order counts:\n"); print(table(sapply(sp[as.character(nd$conf)], function(a) a$order[a$arm == "out"][1])))
