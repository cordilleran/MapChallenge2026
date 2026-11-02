# Day 1 step 20: clip the 3DHP flowlines to the Kettle basin footprint (units_a16 outline) and compare with NHDPlus V2.
# Read-only on the vendored 3DHP file. Out (day01/): us_3dhp.gpkg (layer flowline_kettle), 20_3dhp_summary.txt.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(dplyr)})
D <- DATA_DIR; out <- file.path(D, "us_3dhp.gpkg"); stopifnot(!file.exists(out))
f <- input("MC26_3DHP", "USGS 3DHP flowlines for the region (GeoPackage with a flowline layer)")
u <- st_read(file.path(D, "units_a16.gpkg"), "units", quiet = TRUE); fp <- st_union(st_make_valid(u)); fp <- st_buffer(fp, 300)
crs_f <- st_crs(st_read(f, "flowline", query = "select * from flowline limit 1", quiet = TRUE)); cat("3DHP CRS:", crs_f$input, "\n")
fp_f <- st_transform(fp, crs_f)
x <- st_read(f, "flowline", wkt_filter = st_as_text(st_geometry(fp_f)), quiet = TRUE)
x <- st_zm(x, drop = TRUE, what = "ZM")                     # GEOS cannot take XYM/XYZM; direction is checked against the DEM later
x <- x[lengths(st_intersects(x, fp_f)) > 0, ]; x <- st_transform(x, 3005)
cat("flowlines in basin footprint:", nrow(x), "\n")
cat("featuretype:\n"); print(table(x$featuretypelabel %||% x$featuretype, useNA = "ifany"))
cat("flowdirection:\n"); print(table(x$flowdirection, useNA = "ifany"))
cat("streamorder populated:", sum(!is.na(x$streamorder)), " hydrosequence populated:", sum(!is.na(x$hydrosequence)), " divergence:", paste(names(table(x$divergence)), table(x$divergence), collapse = "; "), "\n")
cat("workunit:\n"); print(table(x$workunitid, useNA = "ifany"))
st_write(x, out, layer = "flowline_kettle", quiet = TRUE)
# US portion: latitude below 49 N
xc <- st_coordinates(st_centroid(st_geometry(st_transform(x, 4326))))[, 2]; us <- x[xc < 49, ]
len_km <- function(l) sum(as.numeric(st_length(l))) / 1000
# US area below the 49th parallel (drawn as a curve, not a chord) for stream length per km2
lon <- seq(-125, -110, by = 0.01); box <- st_sfc(st_polygon(list(rbind(cbind(lon, 49), c(-110, 40), c(-125, 40), c(-125, 49)))), crs = 4326) |> st_transform(3005)
us_area <- as.numeric(st_area(st_intersection(st_transform(fp, 3005), box))) / 1e6
cat(sprintf("US part: 3DHP %d lines, %.0f km (%.2f km/km2) | area %.0f km2\n", nrow(us), len_km(us), len_km(us) / us_area, us_area))
# Optional comparison with NHDPlus V2 (made by exploration/01_fetch_us_network.R); skipped when that file is absent
nhd_file <- file.path(D, "us_nhdplus_v2.gpkg")
if (file.exists(nhd_file)) {
  nhd <- st_read(nhd_file, quiet = TRUE) |> st_transform(3005)
  nc <- st_coordinates(st_centroid(st_geometry(st_transform(nhd, 4326))))[, 2]; nhd <- nhd[nc < 49, ]
  cat(sprintf("NHDPlus V2: %d lines, %.0f km (%.2f km/km2)\n", nrow(nhd), len_km(nhd), len_km(nhd) / us_area))
}
cat("3DHP line length quantiles (m):", paste(round(quantile(as.numeric(st_length(us)), c(.1, .5, .9))), collapse = " "), "\n")
