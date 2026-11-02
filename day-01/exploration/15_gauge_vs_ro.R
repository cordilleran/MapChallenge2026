# Day 1 step 15: accumulated ERA5-Land runoff (mean upstream depth) against observed gauge yield, 9 gauges.
# Gauge setup and snapping repeat lines of 05_yield_and_arms.R so this runs on its own; writes only calibration_gauges_ro.csv.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(sf); library(terra); library(dplyr); library(DBI); library(RSQLite)})
sf_use_s2(FALSE)
DATA <- DATA_DIR
CELL <- 900                                  # m2 per 30 m cell
Y0 <- 1981; Y1 <- 2020; MIN_YEARS <- 10
acc  <- rast(file.path(DATA, "acc_area.tif")); accz <- rast(file.path(DATA, "acc_z.tif"))
crs(acc) <- "EPSG:3005"; crs(accz) <- "EPSG:3005"

# ---- 1. gauges -------------------------------------------------------------------------------------
db <- dbConnect(SQLite(), input("MC26_GAUGE_DB", "SQLite database of gauge annual metrics (HYDAT and USGS)"))
kettle_ids <- c("08NN015","08NN026","08NN002","08NN003","08NN023","08NN028","08NN019","12401500","12404500")
st <- dbGetQuery(db, sprintf("select * from streamflow_stations where station_id in ('%s')", paste(kettle_ids, collapse = "','")))
am <- dbGetQuery(db, sprintf("select station_id, water_year, annual_volume_m3 from streamflow_annual_metrics
   where n_days_data >= 330 and water_year between %d and %d", Y0, Y1))
yld <- am |> group_by(station_id) |> summarise(n_years = n(), vol_mm3 = mean(annual_volume_m3) / 1e6, .groups = "drop")
g <- st |> inner_join(yld, by = "station_id") |> filter(n_years >= MIN_YEARS)
g$q_obs_mm <- g$vol_mm3 * 1e6 / (g$drainage_area_km2 * 1e6) * 1000
pts <- st_transform(st_as_sf(g, coords = c("longitude", "latitude"), crs = 4326), 3005)
snap <- function(p, area_km2, R = 600) {
  xy <- st_coordinates(p); w <- ext(xy[1] - R, xy[1] + R, xy[2] - R, xy[2] + R)
  a <- crop(acc, w); v <- values(a)[, 1]; cc <- xyFromCell(a, seq_len(ncell(a)))
  ok <- !is.na(v) & v > 0 & sqrt((cc[, 1] - xy[1])^2 + (cc[, 2] - xy[2])^2) <= R
  err <- abs(log(v * CELL / 1e6 / area_km2)); err[!ok] <- Inf; i <- which.min(err)
  c(gx = cc[i, 1], gy = cc[i, 2], A_dem = v[i] * CELL / 1e6, snap_d_m = sqrt((cc[i, 1] - xy[1])^2 + (cc[i, 2] - xy[2])^2)) }
sn <- t(sapply(seq_len(nrow(g)), function(i) snap(pts[i, ], g$drainage_area_km2[i])))
colnames(sn) <- c("gx", "gy", "A_dem", "snap_d_m"); g <- cbind(g, as.data.frame(sn))
g$zbar <- terra::extract(accz, cbind(g$gx, g$gy))[, 1] / terra::extract(acc, cbind(g$gx, g$gy))[, 1]
g$area_err_pct <- 100 * (g$A_dem / g$drainage_area_km2 - 1)
# ---- 2/3. fit and scale -------------------------------------------------------------------------------
# ---- step 15: accumulated ERA5-Land runoff against observed yield -----------------------------------
ro <- rast(file.path(DATA, "acc_ro.tif")); crs(ro) <- "EPSG:3005"
g$ro_mean_mm <- terra::extract(ro, cbind(g$gx, g$gy))[,1] / terra::extract(acc, cbind(g$gx, g$gy))[,1]
g$ratio <- g$ro_mean_mm / g$q_obs_mm
print(g[, c("station_id","name","A_dem","zbar","q_obs_mm","ro_mean_mm","ratio")], digits=4)
f <- lm(q_obs_mm ~ ro_mean_mm, g); cat("\nq_obs ~ ro: R2", round(summary(f)$r.squared,2), " slope", round(coef(f)[2],3), " intercept", round(coef(f)[1],1), " p(slope)", signif(summary(f)$coefficients[2,4],2), "\n")
k <- sum(g$q_obs_mm*g$A_dem)/sum(g$ro_mean_mm*g$A_dem); cat("area-weighted single scale k =", round(k,3), "\n")
g$pred_k <- k*g$ro_mean_mm; g$err_pct <- 100*(g$pred_k-g$q_obs_mm)/g$q_obs_mm; print(round(g[, c("q_obs_mm","pred_k","err_pct")],0))
f2 <- lm(q_obs_mm ~ ro_mean_mm + zbar, g); cat("with elevation: R2", round(summary(f2)$r.squared,2), " coefs", round(coef(f2),3), "\n")
write.csv(g[, c("station_id","name","drainage_area_km2","A_dem","gx","gy","zbar","n_years","q_obs_mm","ro_mean_mm","ratio","pred_k","err_pct")], file.path(DATA, "calibration_gauges_ro.csv"), row.names=FALSE)
