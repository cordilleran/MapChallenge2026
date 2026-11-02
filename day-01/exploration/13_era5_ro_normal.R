# Day 1 step 13: 1991-2020 mean annual runoff depth (mm) from the REPAIRED ERA5-Land monthly file.
# Layers are monthly means of daily runoff (m/day); annual depth = sum(month value * days in month).
# ECMWF's accumulated-variable fault covers Sep 2022 to Feb 2024 only, outside this normal.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages(library(terra))
D <- DATA_DIR
f <- input("MC26_ERA5_RO", "ERA5-Land monthly NetCDF with runoff ro (repaired copy)")
out <- file.path(D, "ro_mm_1991_2020_3005_1km.tif"); stopifnot(!file.exists(out))
r <- sds(f)[["ro"]]; stopifnot(nlyr(r) >= 360)
yrs <- rep(1991:2020, each=12); mon <- rep(1:12, 30)
dim_ <- as.numeric(difftime(as.Date(sprintf("%d-%02d-01", yrs + (mon==12), ifelse(mon==12, 1, mon+1))), as.Date(sprintf("%d-%02d-01", yrs, mon)), units="days"))
x <- r[[1:360]] * dim_ * 1000                       # mm per month
ann <- tapp(x, yrs, "sum"); mean_ann <- mean(ann); names(mean_ann) <- "ro_mm"
crs(mean_ann) <- "EPSG:4326"
cat("region mean annual ro (mm), 1991-2020:", round(global(mean_ann, "mean", na.rm=TRUE)$mean), "\n")
cat("range of the 0.1 deg cells:", round(range(values(mean_ann), na.rm=TRUE)), "\n")
cat("year-to-year sd of the regional mean (mm):", round(sd(global(ann, "mean", na.rm=TRUE)$mean)), "\n")
writeRaster(mean_ann, file.path(D, "ro_mm_1991_2020_4326.tif"))
tmpl <- rast(xmin=1465000, xmax=1595000, ymin=420000, ymax=612000, resolution=1000, crs="EPSG:3005")
p <- project(mean_ann, tmpl, method="bilinear"); writeRaster(p, out)
