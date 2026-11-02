# Day 1 step 16: biogeoclimatic-zone wetness weight on the 30 m DEM grid.
# Zone rank, driest to wettest: BG 1, PP 2, IDF 3, MS 4, ICH 5, ESSF 6 (a-priori ordinal, not fitted).
# Weight = rank / mean rank over the Kettle BC area, so the BC mean is 1. No BEC south of the border:
# those cells get weight 1.
# The BEC geojson is tagged WGS84 but its coordinates are BC Albers (same fault as the FWA extract): CRS set, not reprojected.
# those cells get weight 1 (GW 2026-11-01: fall back to 1 where nothing is known).
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(terra); library(sf)})
D <- DATA_DIR
out <- file.path(D, "bec_w.tif"); stopifnot(!file.exists(out))
b <- st_read(input("MC26_BEC", "BC biogeoclimatic zones, Kettle region (GeoJSON, BC Data Catalogue)"), quiet=TRUE)
b <- st_set_crs(b, 3005); b <- b[b$ZONE %in% c("BG","PP","IDF","MS","ICH","ESSF"), ]
b$rank <- match(b$ZONE, c("BG","PP","IDF","MS","ICH","ESSF"))
tmpl <- rast(file.path(D, "acc_area.tif")); crs(tmpl) <- "EPSG:3005"
rk <- rasterize(vect(b), tmpl, field="rank")
stopifnot(global(rk, "notNA")$notNA > 1e6)            # guard: an empty raster means the CRS is wrong again
u <- rast(file.path(D, "units_a16.tif")); crs(u) <- "EPSG:3005"
inb <- resample(u > -1, rk, method="near")                      # Kettle footprint
m <- global(mask(rk, inb), "mean", na.rm=TRUE)$mean; cat("mean rank over Kettle BC cells:", round(m, 3), "\n")
w <- rk / m; w <- ifel(is.na(w), 1, w); names(w) <- "bec_w"
writeRaster(w, out, datatype="FLT4S", gdal="COMPRESS=DEFLATE")
cat("zones by area share of Kettle footprint:\n"); print(round(table(values(mask(rk, inb)))/sum(!is.na(values(mask(rk, inb)))), 3))
