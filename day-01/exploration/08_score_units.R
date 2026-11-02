# Day 1 step 8: score DEM-derived local units against the 125 official BC 1:50k Kettle units.
# For each official polygon: the derived unit with the largest overlap, and IoU between them.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
suppressMessages({library(terra); library(sf); library(dplyr)})
D <- DATA_DIR
OFF <- st_read(input("MC26_BC50K", "BC Watershed Atlas 1:50k watersheds, Kettle region (GeoPackage, BC Data Catalogue)"), quiet=TRUE)
OFF <- OFF[grepl("^320-", OFF$NEW_WATERSHED_CODE), ]; OFF <- st_transform(OFF, 3005)
res <- list()
for (T in c(5,10,20)) {
  u <- rast(file.path(D, sprintf("units_t%dkm2.tif", T)))
  ov <- vect(OFF); ov$id <- seq_len(nrow(OFF))
  rid <- rasterize(ov, u, field="id")
  df <- data.frame(unit=as.vector(values(u)), off=as.vector(values(rid)))
  df <- df[!is.na(df$off) & !is.na(df$unit), ]
  ov_tab <- df |> count(off, unit, name="n")
  best <- ov_tab |> group_by(off) |> slice_max(n, n=1, with_ties=FALSE) |> ungroup()
  utot <- as.data.frame(freq(u)); names(utot) <- c("layer","unit","utot"); utot <- utot[,c("unit","utot")]
  otot <- df |> count(off, name="otot")
  r <- best |> left_join(utot, by="unit") |> left_join(otot, by="off") |>
    mutate(iou = n/(utot+otot-n), T=T, a_off=OFF$WATERSHED_AREA[off]/1e6, ord=OFF$STREAM_ORDER[off], a_der=utot*900/1e6)
  # how many derived units have >50% of area inside the official footprint
  allu <- df |> count(unit, name="in_off"); allu <- allu |> left_join(utot, by="unit") |> mutate(f=in_off/utot)
  r$n_der_in <- sum(allu$f > 0.5)
  res[[as.character(T)]] <- r
}
r <- bind_rows(res)
r$cls <- cut(r$a_off, c(0,15,30,60,150,2000), labels=c("<15","15-30","30-60","60-150",">150"))
cat("Official units: ", nrow(OFF), "\n")
print(r |> group_by(T) |> summarise(n_der_in=first(n_der_in), med_iou=median(iou), iou_ge_0.8=mean(iou>=0.8), iou_ge_0.5=mean(iou>=0.5), med_area_ratio=median(a_der/a_off)))
print(r |> group_by(T, cls) |> summarise(n=n(), med_iou=round(median(iou),2), ge_0.8=round(mean(iou>=0.8),2), .groups="drop") |> tidyr::pivot_wider(names_from=T, values_from=c(med_iou, ge_0.8)))
write.csv(r, file.path(D, "units_vs_bc50k.csv"), row.names=FALSE)
