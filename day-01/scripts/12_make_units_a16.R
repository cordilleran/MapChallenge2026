# Day 1 step 12: write the derived local units for the whole Kettle basin, area chain rule, A = 16 km2 on the
# 5 km2 stream network. Rule: at each confluence the larger branch continues the unit; the smaller starts a new unit only if it drains at least A km2.
# A = 16 km2 gave the best overlap with the 125 official Kettle units (median IoU 0.80); the trials are in exploration/11_chain_units.R and 11b_chain_fine.R.
# Out (day01/): units_a16.tif, units_a16.gpkg (layer units), units_a16_match.csv. Safe rerun: stops if they exist.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])); source(file.path(.here, "..", "config.R"))
source(file.path(.here, "lib_chain.R"))
A_KM2 <- 16; MOUTH <- c(1582134, 438381); KETTLE_KM2 <- 10893
out_tif <- file.path(D, "units_a16.tif"); stopifnot(!file.exists(out_tif))
nt <- load_net(5); rc <- nt$rc
st <- rast(file.path(D, "streams_t5km2.tif"))
win <- unique(na.omit(as.vector(values(crop(st, ext(MOUTH[1]-1500, MOUTH[1]+1500, MOUTH[2]-1500, MOUTH[2]+1500))))))
cand <- rc[rc$stream %in% win, c("stream","cumA")]; print(cand)
R0 <- cand$stream[which.min(abs(cand$cumA - KETTLE_KM2))]; cat("mouth reach", R0, "cumA", cand$cumA[cand$stream==R0], "\n")
# reaches that drain to R0
e <- rc[!is.na(rc$next_stream), c("stream","next_stream")]
g <- graph_from_data_frame(e, directed=TRUE, vertices=data.frame(name=rc$stream))
up <- as.numeric(names(subcomponent(g, as.character(R0), mode="in")))
u <- unit_A(nt, A_KM2); u <- u[names(u) %in% as.character(up)]
ras <- classify(nt$ras, cbind(as.numeric(names(u)), as.numeric(u)), others=NA)
ras <- trim(ras); writeRaster(ras, out_tif, datatype="INT4S", gdal=c("COMPRESS=DEFLATE"))
pol <- st_as_sf(as.polygons(ras, dissolve=TRUE)); names(pol)[1] <- "unit"; pol <- st_make_valid(pol)
pol$area_km2 <- as.numeric(st_area(pol))/1e6
pol$cumA_km2 <- rc$cumA[match(pol$unit, rc$stream)]
pol$order_out <- rc$strahler[match(pol$unit, rc$stream)]
pol$next_unit <- u[as.character(rc$next_stream[match(pol$unit, rc$stream)])]
# side: share of the unit inside the 125 official BC units, and its best official match
offu <- st_union(OFF); ix_off <- st_intersection(pol, offu) |> st_make_valid()            # intersect once, reuse for area and unit id
inter <- as.numeric(st_area(ix_off))
pol$share_in_bc50k <- inter[match(pol$unit, ix_off$unit)] / as.numeric(st_area(pol))
pol$share_in_bc50k[is.na(pol$share_in_bc50k)] <- 0
pol$side <- ifelse(pol$share_in_bc50k >= 0.5, "bc50k_covered", "outside_bc50k_set")
ix <- st_intersection(pol[, c("unit","area_km2")], OFF[, c("NEW_WATERSHED_CODE","GAZETTED_NAME","WATERSHED_AREA")]) |> st_make_valid()
ix$ov <- as.numeric(st_area(ix))/1e6
ix <- st_drop_geometry(ix) |> mutate(a_off=WATERSHED_AREA/1e6, iou=ov/(area_km2 + a_off - ov))
best <- ix |> group_by(unit) |> slice_max(iou, n=1, with_ties=FALSE) |> ungroup() |>
  transmute(unit, bc50k_code=NEW_WATERSHED_CODE, bc50k_name=GAZETTED_NAME, iou_bc50k=round(iou,3), ratio=round(area_km2/a_off,2))
pol <- left_join(pol, best, by="unit")
st_write(pol, file.path(D, "units_a16.gpkg"), layer="units", quiet=TRUE)
write.csv(st_drop_geometry(pol), file.path(D, "units_a16_match.csv"), row.names=FALSE)
cat("units:", nrow(pol), " total km2:", round(sum(pol$area_km2)), "\n")
print(pol |> st_drop_geometry() |> group_by(side) |> summarise(n=n(), km2=round(sum(area_km2)), med_area=round(median(area_km2),1), med_iou=round(median(iou_bc50k, na.rm=TRUE),2)))
