# Day 1 step 18: BEC wetness weight, elevation and ERA5-Land runoff as predictors of gauge yield (9 gauges, leave-one-out).
# Gauge setup and snapping repeat lines of 05_yield_and_arms.R so this runs on its own; writes only calibration_gauges_predictors.csv.
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
# ---- step 18 -----------------------------------------------------------------------------------------
pt <- cbind(g$gx, g$gy)
ab <- rast(file.path(DATA, "acc_bec.tif")); crs(ab) <- "EPSG:3005"; ro <- rast(file.path(DATA, "acc_ro.tif")); crs(ro) <- "EPSG:3005"
g$bec <- terra::extract(ab, pt)[,1] / terra::extract(acc, pt)[,1]
g$ro  <- terra::extract(ro, pt)[,1] / terra::extract(acc, pt)[,1]
print(data.frame(g["station_id"], A=round(g$A_dem), zbar=round(g$zbar), bec=round(g$bec,3), ro=round(g$ro), obs=round(g$q_obs_mm)), row.names=FALSE)
forms <- list(const = q_obs_mm ~ 1, elev = q_obs_mm ~ zbar, bec = q_obs_mm ~ bec, bec_elev = q_obs_mm ~ bec + zbar, bec_ro = q_obs_mm ~ bec + ro, ro = q_obs_mm ~ ro)
loo <- function(f) sapply(seq_len(nrow(g)), function(i) predict(lm(f, g[-i, ]), g[i, ]))
res <- do.call(rbind, lapply(names(forms), function(n) { fit <- lm(forms[[n]], g); p <- loo(forms[[n]])
  data.frame(model=n, R2=round(summary(fit)$r.squared,2), rmse_in=round(sqrt(mean(resid(fit)^2))), rmse_loo=round(sqrt(mean((p-g$q_obs_mm)^2))), max_loo_err_pct=round(max(abs(100*(p/g$q_obs_mm-1))))) }))
print(res, row.names=FALSE)
fb <- lm(q_obs_mm ~ bec, g); cat("\nbec slope p:", signif(summary(fb)$coefficients[2,4],2), " coefs:", round(coef(fb),1), "\n")
fe <- lm(q_obs_mm ~ bec + zbar, g); print(round(summary(fe)$coefficients,3))
write.csv(cbind(g[, c("station_id","name","A_dem","gx","gy","zbar","q_obs_mm")], bec=g$bec, ro=g$ro), file.path(DATA, "calibration_gauges_predictors.csv"), row.names=FALSE)
