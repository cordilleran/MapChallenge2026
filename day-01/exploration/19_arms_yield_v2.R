# Day 1 step 19: yield axis v2 on the arms: relative yield from the BEC wetness weight, anchored at the 9 gauges.
#   ln q(arm) = a + b * bec_up   (a, b fitted at the 9 gauges; R2 0.95, leave-one-out RMSE 41 mm, worst gauge 15 percent;
#   a straight line gave R2 0.91 and goes negative for the dry zones). bec_up = upstream mean BEC weight (step 17).
#   q_rel = q(arm) / q(mouth), so any constant scale (Laurier mass balance) cancels.
#   The gauges span bec_up 0.90 to 1.16. Arms outside 0.85 to 1.20 are extrapolated and flagged.
#   No BEC south of the border: weight 1 there (GW 2026-11-01).
# In: arms.csv (step 5, untouched), acc_area.tif, acc_bec.tif, calibration_gauges_predictors.csv. Out: arms_v2.csv.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(terra); library(dplyr)})
DATA <- DATA_DIR; CELL <- 900
out <- file.path(DATA, "arms_v2.csv"); stopifnot(!file.exists(out))
acc <- rast(file.path(DATA, "acc_area.tif")); ab <- rast(file.path(DATA, "acc_bec.tif")); crs(acc) <- crs(ab) <- "EPSG:3005"
arms <- read.csv(file.path(DATA, "arms.csv"))
gc <- read.csv(file.path(DATA, "calibration_gauges_predictors.csv")); fit <- lm(log(q_obs_mm) ~ bec, gc)
a <- coef(fit)[1]; b <- coef(fit)[2]; cat("ln q = a + b*bec: a", round(a, 3), " b", round(b, 3), " R2", round(summary(fit)$r.squared, 2), "\n")
off <- expand.grid(dx = c(-1, 0, 1) * 30, dy = c(-1, 0, 1) * 30)                  # same 3x3 snap as step 5
vals <- sapply(seq_len(nrow(off)), function(j) terra::extract(acc, cbind(arms$sx + off$dx[j], arms$sy + off$dy[j]))[, 1])
best <- apply(vals, 1, function(v) if (all(is.na(v))) NA_integer_ else which.max(v))
cx <- arms$sx + off$dx[best]; cy <- arms$sy + off$dy[best]
chk <- terra::extract(acc, cbind(cx, cy))[, 1] * CELL / 1e6; stopifnot(max(abs(chk - arms$A_km2), na.rm = TRUE) < 1e-6)   # reproduces step 5 areas
arms$bec_up <- terra::extract(ab, cbind(cx, cy))[, 1] / terra::extract(acc, cbind(cx, cy))[, 1]
arms$extrapolated <- arms$bec_up < 0.85 | arms$bec_up > 1.20
mouth <- arms |> filter(arm == "out") |> slice_max(A_km2, n = 1, with_ties = FALSE)
cat("mouth: A", round(mouth$A_km2), "km2, bec_up", round(mouth$bec_up, 3), "\n")
arms$q_mm_v2 <- exp(a + b * arms$bec_up); arms$q_rel_v2 <- exp(b * (arms$bec_up - mouth$bec_up))
cat("share of arms outside the calibrated bec range:", round(100 * mean(arms$extrapolated, na.rm = TRUE), 1), "%\n")
cat("q_rel_v2 quantiles:\n"); print(round(quantile(arms$q_rel_v2, c(.01, .1, .25, .5, .75, .9, .99), na.rm = TRUE), 2))
write.csv(arms, out, row.names = FALSE)
