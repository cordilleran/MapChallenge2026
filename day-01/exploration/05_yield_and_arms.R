#!/usr/bin/env Rscript
# Day 1 step 5: specific yield by elevation-weighted area, and the arms of every confluence glyph.
#  1. snap the Kettle gauges onto the DEM accumulation by matching published drainage area
#  2. fit mean annual runoff depth (mm) against mean upstream elevation at those gauges: q = a + b*zbar
#  3. scale (k) so the Laurier gauge volume is matched exactly (water balance of the whole basin)
#  4. for each confluence, sample the DEM accumulation on each inflow arm and on the outflow arm:
#       area A, mean elevation zbar, volume V = k*(a*A + b*zbar*A), specific yield q = V/A,
#       relative yield q_rel = q / q_mouth
#  5. check DEM area against NHDPlus V2 totdasqkm on the US arms
# In : acc_area.tif, acc_z.tif (step 4), network.gpkg, swe_regional.db
# Out: $DATA/arms.csv, $DATA/calibration_gauges.csv, $DATA/validation_nhd.csv
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
fit <- lm(q_obs_mm ~ zbar, data = g)
cat("fit q = a + b*zbar:\n"); print(summary(fit)$coefficients); cat("R2", round(summary(fit)$r.squared, 3), "n", nrow(g), "\n")
a <- coef(fit)[1]; b <- coef(fit)[2]
vol_model <- function(A_km2, zbar) (a + b * zbar) * A_km2 * 1e6 / 1000       # m3, unscaled
lau <- g[g$station_id == "12404500", ]
k <- (lau$vol_mm3 * 1e6) / vol_model(lau$A_dem, lau$zbar)
cat("scale k to match Laurier volume:", round(k, 3), "\n")
g$q_mod_mm <- k * (a + b * g$zbar)
g$err_pct <- 100 * (g$q_mod_mm / g$q_obs_mm - 1)
# leave-one-out error for the unscaled fit (gauges are nested, so this is optimistic)
g$loo_pct <- sapply(seq_len(nrow(g)), function(i) { f <- lm(q_obs_mm ~ zbar, data = g[-i, ]); 100 * (k * predict(f, g[i, ]) / g$q_obs_mm[i] - 1) })
write.csv(g |> select(station_id, name, drainage_area_km2, A_dem, area_err_pct, snap_d_m, zbar, n_years, q_obs_mm, q_mod_mm, err_pct, loo_pct),
          file.path(DATA, "calibration_gauges.csv"), row.names = FALSE)
print(g |> select(station_id, drainage_area_km2, area_err_pct, zbar, q_obs_mm, q_mod_mm, err_pct, loo_pct) |> mutate(across(where(is.numeric), ~ round(.x, 1))), row.names = FALSE)

# ---- 4. arms ---------------------------------------------------------------------------------------
seg <- st_read(file.path(DATA, "network.gpkg"), "segments", quiet = TRUE)
cf  <- st_read(file.path(DATA, "network.gpkg"), "confluences", quiet = TRUE)
mats <- lapply(st_geometry(seg), function(l) unclass(l)[, 1:2, drop = FALSE]); names(mats) <- seg$seg_id
pt_along <- function(m, d, from_end) {
  if (from_end) m <- m[nrow(m):1, , drop = FALSE]
  seglen <- sqrt(rowSums(diff(m)^2)); cum <- c(0, cumsum(seglen)); d <- min(d, max(cum))
  i <- max(which(cum <= d)); if (i >= nrow(m)) return(m[nrow(m), ])
  f <- (d - cum[i]) / seglen[i]; m[i, ] + f * (m[i + 1, ] - m[i, ]) }
D_BEAR <- 150; D_SAMP <- 90
arms <- list()
for (r in seq_len(nrow(cf))) {
  ins <- strsplit(cf$in_ids[r], ";")[[1]]; node <- st_coordinates(cf[r, ])[1, 1:2]
  for (id in ins) { m <- mats[[id]]
    arms[[length(arms) + 1]] <- data.frame(conf = r, arm = "in", seg_id = id, nx = node[1], ny = node[2],
      bx = pt_along(m, D_BEAR, TRUE)[1], by = pt_along(m, D_BEAR, TRUE)[2],
      sx = pt_along(m, D_SAMP, TRUE)[1], sy = pt_along(m, D_SAMP, TRUE)[2]) }
  id <- cf$out_id[r]; m <- mats[[id]]
  arms[[length(arms) + 1]] <- data.frame(conf = r, arm = "out", seg_id = id, nx = node[1], ny = node[2],
      bx = pt_along(m, D_BEAR, FALSE)[1], by = pt_along(m, D_BEAR, FALSE)[2],
      sx = pt_along(m, D_SAMP, FALSE)[1], sy = pt_along(m, D_SAMP, FALSE)[2]) }
arms <- do.call(rbind, arms)
arms$bearing <- (atan2(arms$bx - arms$nx, arms$by - arms$ny) * 180 / pi) %% 360     # clockwise from north, node -> arm tip
# snap: best of the 3x3 window around the sample point (max upstream area = the DEM stream)
off <- expand.grid(dx = c(-1, 0, 1) * 30, dy = c(-1, 0, 1) * 30)
vals <- sapply(seq_len(nrow(off)), function(j) terra::extract(acc, cbind(arms$sx + off$dx[j], arms$sy + off$dy[j]))[, 1])
best <- apply(vals, 1, function(v) if (all(is.na(v))) NA_integer_ else which.max(v))
cx <- arms$sx + off$dx[best]; cy <- arms$sy + off$dy[best]
arms$A_km2 <- terra::extract(acc, cbind(cx, cy))[, 1] * CELL / 1e6
arms$zbar  <- terra::extract(accz, cbind(cx, cy))[, 1] / terra::extract(acc, cbind(cx, cy))[, 1]
arms$V_mm3 <- k * vol_model(arms$A_km2, arms$zbar) / 1e6
arms$q_mm  <- arms$V_mm3 * 1e6 / (arms$A_km2 * 1e6) * 1000
a_out <- arms[arms$arm == "out", ]; imax <- which.max(a_out$A_km2)
q_ref <- a_out$q_mm[imax]; cat("reference (largest outflow) A =", round(a_out$A_km2[imax]), "km2, q =", round(q_ref), "mm\n")
arms$q_rel <- arms$q_mm / q_ref
# QC: an inflow arm must drain less than its outflow
o <- arms |> filter(arm == "out") |> select(conf, A_out = A_km2)
arms <- arms |> left_join(o, by = "conf"); arms$qc_ok <- !is.na(arms$A_km2) & (arms$arm == "out" | arms$A_km2 < arms$A_out)
cat("arms:", nrow(arms), " qc ok:", round(100 * mean(arms$qc_ok), 1), "%\n")
arms <- arms |> left_join(seg |> st_drop_geometry() |> select(seg_id, src, order, order_src), by = "seg_id")
write.csv(arms, file.path(DATA, "arms.csv"), row.names = FALSE)

# ---- 5. NHDPlus check on the US arms -----------------------------------------------------------------
us <- st_read(file.path(DATA, "us_nhdplus_v2.gpkg"), quiet = TRUE) |> st_drop_geometry() |> transmute(seg_id = paste0("U", comid), nhd_totda = totdasqkm)
v <- arms |> inner_join(us, by = "seg_id") |> filter(qc_ok, !is.na(A_km2))
v$ratio <- v$A_km2 / v$nhd_totda
cat("US arms vs NHDPlus totdasqkm: n =", nrow(v), " median ratio", round(median(v$ratio), 2),
    " IQR", paste(round(quantile(v$ratio, c(.25, .75)), 2), collapse = "-"), " within +-25%:", round(100 * mean(abs(v$ratio - 1) < .25), 1), "%\n")
write.csv(v |> select(conf, seg_id, order, A_km2, nhd_totda, ratio), file.path(DATA, "validation_nhd.csv"), row.names = FALSE)
