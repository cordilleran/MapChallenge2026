#!/usr/bin/env Rscript
# Day 7 step 01: fetch every source into $MC26_DAY07_DATA/raw, as published.
# A source already on disk is not fetched again (delete its file to refresh).
# No API keys. Sources and licences are in day-07/README.md.
#   relief  AWS Terrain Tiles (elevatr)            -> dem_terrain_z10.tif
#   lake    NOAA NCEI Lake Superior 3" grid        -> superior_lld/superior_lld.tif
#   OSM     Geofabrik Minnesota and Wisconsin extracts (dated), clipped once to the box
#           -> osm_clip.gpkg; then pits and places -> osm_<layer>.gpkg (roads, rail and rivers
#           come from the 1958 sheets since v2; OSM roads beyond the frame feed the road notes)
#   seas    USGS WBD HUC8 (ArcGIS REST)            -> wbd_huc8.geojson
#   dove    GBIF occurrence search                 -> gbif_doves.csv
#   wind    Open-Meteo archive (ERA5), April 1962  -> wind_hourly.csv
#   survey  BLM PLSS CadNSDI townships (ArcGIS REST) -> plss_townships.geojson
#   states  the same service's state boundaries, for the location diagram -> states.geojson
#   beyond  numbered roads and towns 1 degree round the frame, from the same extracts
#           -> osm_roads_beyond.gpkg, osm_towns_beyond.gpkg (for the collar road notes)
#
# Layout: main() first, the helpers follow; main() is called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages({
  library(dplyr)
  library(purrr)
  library(sf)
})

main <- function() {
  box <- FRAME_LL + FETCH_PAD_DEG * c(-1, -1, 1, 1)
  fetch_once(file.path(RAW_DIR, "dem_terrain_z10.tif"), fetch_terrain, box)
  fetch_once(NCEI_TIF, fetch_ncei)
  pbfs <- OSM_EXTRACTS |> map_chr(\(state) {
    fetch_once(file.path(RAW_DIR, paste0(state, "-", OSM_SNAPSHOT, ".osm.pbf")), fetch_extract)
  })
  clip <- fetch_once(file.path(RAW_DIR, "osm_clip.gpkg"), clip_extracts, box, pbfs)
  OSM_QUERIES |> iwalk(\(where, name) {
    fetch_once(file.path(RAW_DIR, paste0("osm_", name, ".gpkg")), select_osm, clip, where)
  })
  fetch_once(file.path(RAW_DIR, "osm_places.gpkg"), select_places, clip)
  fetch_once(file.path(RAW_DIR, "wbd_huc8.geojson"), fetch_wbd, box)
  fetch_once(file.path(RAW_DIR, "gbif_doves.csv"), fetch_gbif, box)   # padded: the projected frame's corners reach past FRAME_LL
  fetch_once(file.path(RAW_DIR, "wind_hourly.csv"), fetch_wind, box)
  fetch_once(file.path(RAW_DIR, "plss_townships.geojson"), fetch_plss, box)
  fetch_once(file.path(RAW_DIR, "states.geojson"), fetch_states, LOCATION_BOX)
  fetch_once(file.path(RAW_DIR, "nwi_wetlands.gpkg"), fetch_nwi, box)
  wide <- FRAME_LL + BEYOND_PAD_DEG * c(-1, -1, 1, 1)
  fetch_once(file.path(RAW_DIR, "osm_roads_beyond.gpkg"), extract_beyond, pbfs, wide, "lines",
             "highway IN ('motorway','trunk','primary','secondary') AND other_tags LIKE '%\"ref\"%'")
  fetch_once(file.path(RAW_DIR, "osm_towns_beyond.gpkg"), extract_beyond, pbfs, wide, "points",
             "place IN ('city','town','village')")
  message("Step 01 done. Raw files in ", RAW_DIR)
}

# OSM from Geofabrik's daily extracts, not Overpass: the public Overpass server refused
# scripted queries on 2026-11-16 (502, "intended for browser-based tools"), and a dated
# extract pins the data. Superior, Wisconsin, is inside the frame, so both states.
OSM_SNAPSHOT <- Sys.getenv("MC26_OSM_SNAPSHOT", "261115")   # Geofabrik file date, YYMMDD
OSM_EXTRACTS <- c("minnesota", "wisconsin")

# Each layer: the GDAL OSM layer and an SQL filter (ref and industrial live in other_tags)
OSM_QUERIES <- list(
  pits   = "SELECT osm_id, osm_way_id, name, landuse, geom FROM multipolygons
            WHERE landuse = 'quarry'
               OR (landuse = 'industrial' AND other_tags LIKE '%\"industrial\"=>\"mine\"%')"
)

options(timeout = max(1800, getOption("timeout")))   # the PBF extracts and the NCEI archive are large

fetch_once <- function(path, fun, ...) {
  if (file.exists(path)) {
    message("have ", basename(path))
    return(invisible(path))
  }
  message("fetching ", basename(path))
  fun(path, ...)
  stopifnot(file.exists(path))
  invisible(path)
}

fetch_terrain <- function(path, box) {
  area <- sf::st_as_sf(sf::st_as_sfc(sf::st_bbox(box, crs = 4326)))
  dem <- elevatr::get_elev_raster(area, z = DEM_ZOOM, clip = "bbox", verbose = FALSE)
  terra::writeRaster(terra::rast(dem), path, overwrite = FALSE)
}

fetch_ncei <- function(path) {
  if (nzchar(Sys.getenv("MC26_NCEI_SUPERIOR"))) {
    stop("MC26_NCEI_SUPERIOR is set but ", path, " is missing; unset it to download into ", RAW_DIR, call. = FALSE)
  }
  archive <- file.path(RAW_DIR, "superior_lld.geotiff.tar.gz")
  download_whole(NCEI_URL, archive)
  utils::untar(archive, exdir = RAW_DIR)   # holds superior_lld/superior_lld.tif
}

fetch_extract <- function(path) {
  url <- paste0("https://download.geofabrik.de/north-america/us/", basename(path))
  download_whole(url, path)
}

# Download to a .part file and rename it only when complete, so a broken download is not
# taken for a finished one on the next run
download_whole <- function(url, path) {
  part <- paste0(path, ".part")
  unlink(part)
  utils::download.file(url, part, mode = "wb", quiet = TRUE)
  file.rename(part, path)
}

# ArcGIS REST answers an error with HTTP 200 and an "error" object; stop before it is cached
arcgis_body <- function(resp, what) {
  body <- httr2::resp_body_string(resp)
  if (grepl('^\\s*\\{\\s*"error"', body)) stop(what, " query failed: ", substr(body, 1, 200), call. = FALSE)
  if (grepl('"exceededTransferLimit":\\s*true', body)) stop(what, " query hit the record limit", call. = FALSE)
  body
}

# One pass per extract: every OSM layer, clipped to the box, into one GeoPackage
clip_extracts <- function(path, box, pbfs) {
  layers <- c("points", "lines", "multipolygons")
  tmp <- paste0(path, ".partial.gpkg")   # renamed only when every pass is done
  unlink(tmp)
  pbfs |> iwalk(\(pbf, i) {
    layers |> walk(\(layer) {
      sf::gdal_utils("vectortranslate", pbf, tmp, options = c(
        "-spat", box[["xmin"]], box[["ymin"]], box[["xmax"]], box[["ymax"]],
        if (i > 1 || file.exists(tmp)) c("-update", "-append"),
        "-nln", layer, layer
      ))
    })
  })
  file.rename(tmp, path)
}

select_osm <- function(path, clip, where) {
  # a feature on the state line is in both extracts: keep it once
  layer <- st_read(clip, query = where, quiet = TRUE)
  stopifnot(inherits(layer, "sf"), nrow(layer) > 0)   # a query without `geom` returns a plain table
  layer <- distinct(layer, across(any_of(c("osm_id", "osm_way_id"))), .keep_all = TRUE)
  st_write(layer, path, quiet = TRUE)
}

# One point per named place: a place node if there is one, else the centroid of the
# first polygon with that exact name.
select_places <- function(path, clip) {
  found <- OSM_PLACES |> imap(\(name, id) {
    nm <- gsub("'", "''", name)
    pts <- st_read(clip, quiet = TRUE,
                   query = paste0("SELECT osm_id, name, place, geom FROM points WHERE name = '", nm, "'"))
    pts <- pts |> arrange(is.na(place))
    if (nrow(pts) == 0) {
      polys <- st_read(clip, quiet = TRUE, query = paste0(
        "SELECT osm_id, osm_way_id, name, geom FROM multipolygons WHERE name = '", nm, "'"))
      if (nrow(polys) == 0) stop("No OSM feature named '", name, "'", call. = FALSE)
      pts <- polys[1, ] |> mutate(geometry = st_centroid(st_make_valid(st_geometry(polys[1, ]))))
      pts <- st_set_geometry(pts, "geometry")
    }
    st_sf(id = id, name = name, geometry = st_geometry(pts[1, ]))
  }) |> bind_rows()
  st_write(found, path, quiet = TRUE)
}

fetch_wbd <- function(path, box) {
  url <- "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4/query"
  resp <- httr2::request(url) |>
    httr2::req_url_query(
      where = "1=1", geometry = paste(box, collapse = ","),
      geometryType = "esriGeometryEnvelope", inSR = 4326, outSR = 4326,
      spatialRel = "esriSpatialRelIntersects", outFields = "huc8,name",
      maxAllowableOffset = 0.0005, f = "geojson"
    ) |>
    httr2::req_retry(max_tries = 3) |>
    httr2::req_perform()
  writeLines(arcgis_body(resp, "WBD"), path)
}

# Public Land Survey townships (BLM CadNSDI, public domain): the T and R labels of the collar
fetch_plss <- function(path, box) {
  url <- "https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer/1/query"
  resp <- httr2::request(url) |>
    httr2::req_url_query(
      where = "1=1", geometry = paste(box, collapse = ","),
      geometryType = "esriGeometryEnvelope", inSR = 4326, outSR = 4326,
      spatialRel = "esriSpatialRelIntersects",
      outFields = "PLSSID,STATEABBR,PRINMERCD,TWNSHPNO,TWNSHPDIR,RANGENO,RANGEDIR,TWNSHPLAB",
      f = "geojson"
    ) |>
    httr2::req_retry(max_tries = 3) |>
    httr2::req_perform()
  writeLines(arcgis_body(resp, "PLSS"), path)
}

# State outlines for the location diagram (same BLM service, layer 0; generalised to 0.02 deg)
LOCATION_BOX <- c(xmin = -98, ymin = 44, xmax = -86, ymax = 49.5)
fetch_states <- function(path, box) {
  url <- "https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer/0/query"
  resp <- httr2::request(url) |>
    httr2::req_url_query(
      where = "1=1", geometry = paste(box, collapse = ","),
      geometryType = "esriGeometryEnvelope", inSR = 4326, outSR = 4326,
      spatialRel = "esriSpatialRelIntersects", outFields = "STUSPS,NAME",
      maxAllowableOffset = 0.02, f = "geojson"
    ) |>
    httr2::req_retry(max_tries = 3) |>
    httr2::req_perform()
  writeLines(arcgis_body(resp, "States"), path)
}

# National Wetlands Inventory (USFWS, public domain; D327): emergent and forested or shrub
# wetlands of NWI_MIN_ACRES or more, the size a 1:250,000 sheet could draw. The service gives
# 500 features a request, so the object ids come first, then the features in batches.
NWI_URL <- "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query"
NWI_TYPES <- c("Freshwater Emergent Wetland", "Freshwater Forested/Shrub Wetland")
NWI_MIN_ACRES <- 10
NWI_OFFSET_DEG <- 0.0002   # about 20 m: the service generalises the outlines it sends
fetch_nwi <- function(path, box) {
  where <- sprintf("WETLAND_TYPE IN (%s) AND ACRES >= %d",
                   paste0("'", NWI_TYPES, "'", collapse = ","), NWI_MIN_ACRES)
  ask <- \(...) httr2::request(NWI_URL) |>
    httr2::req_body_form(where = where, geometry = paste(box, collapse = ","),
                         geometryType = "esriGeometryEnvelope", inSR = 4326,
                         spatialRel = "esriSpatialRelIntersects", ...) |>
    httr2::req_retry(max_tries = 4) |>
    httr2::req_timeout(300) |>
    httr2::req_perform()
  ids <- jsonlite::fromJSON(arcgis_body(ask(returnIdsOnly = "true", f = "json"), "NWI ids"))$objectIds
  message("  NWI wetlands: ", length(ids))
  batches <- split(sort(ids), ceiling(seq_along(ids) / 500))
  tmp <- paste0(path, ".partial.gpkg")
  unlink(tmp)
  iwalk(batches, \(b, i) {
    body <- arcgis_body(ask(objectIds = paste(b, collapse = ","), outFields = "OBJECTID,ATTRIBUTE,WETLAND_TYPE,ACRES",
                            outSR = 4326, maxAllowableOffset = NWI_OFFSET_DEG, f = "geojson"), "NWI")
    sf::st_read(body, quiet = TRUE) |> sf::st_cast("MULTIPOLYGON") |>
      sf::st_write(tmp, "nwi", append = file.exists(tmp), quiet = TRUE)
  })
  file.rename(tmp, path)
}

# Numbered roads (or towns) in a wider box, from both state extracts, kept once
BEYOND_PAD_DEG <- 1.0
extract_beyond <- function(path, pbfs, box, layer, where) {
  tmp <- paste0(path, ".partial.gpkg")
  unlink(tmp)
  pbfs |> iwalk(\(pbf, i) {
    sf::gdal_utils("vectortranslate", pbf, tmp, options = c(
      "-spat", box[["xmin"]], box[["ymin"]], box[["xmax"]], box[["ymax"]],
      "-where", where, if (i > 1) c("-update", "-append"), "-nln", layer, layer
    ))
  })
  st_read(tmp, quiet = TRUE) |>
    distinct(across(any_of(c("osm_id", "osm_way_id"))), .keep_all = TRUE) |>
    st_write(path, quiet = TRUE)
  unlink(tmp)
}

fetch_gbif <- function(path, box) {
  page_size <- 300
  keep_cols <- c("key", "decimalLatitude", "decimalLongitude", "coordinateUncertaintyInMeters",
                 "year", "month", "license", "datasetKey", "basisOfRecord")
  get_page <- function(offset) {
    httr2::request("https://api.gbif.org/v1/occurrence/search") |>
      httr2::req_url_query(
        scientificName = DOVE_TAXON, hasCoordinate = "true", hasGeospatialIssue = "false",
        month = DOVE_MONTH, occurrenceStatus = "PRESENT",
        decimalLatitude = paste(box[["ymin"]], box[["ymax"]], sep = ","),
        decimalLongitude = paste(box[["xmin"]], box[["xmax"]], sep = ","),
        license = DOVE_LICENCES, limit = page_size, offset = offset, .multi = "explode"
      ) |>
      httr2::req_retry(max_tries = 3) |>
      httr2::req_perform() |>
      httr2::resp_body_json(simplifyVector = FALSE)   # records are deeply nested: pick fields by hand
  }
  as_row <- function(rec) {
    keep_cols |> set_names() |> map(\(f) rec[[f]] %||% NA) |> tibble::as_tibble()
  }
  first <- get_page(0)
  message("  GBIF records matching: ", first$count)
  offsets <- seq(page_size, max(page_size, first$count - 1), by = page_size)
  offsets <- offsets[offsets < first$count]
  records <- c(list(first), map(offsets, get_page)) |>
    map(\(page) map(page$results, as_row) |> bind_rows()) |>
    bind_rows()
  if (nrow(records) != first$count) warning("GBIF count changed during paging: ", nrow(records), " of ", first$count)
  utils::write.csv(records, path, row.names = FALSE)
}

fetch_wind <- function(path, box) {
  grid <- tidyr::expand_grid(
    lat = seq(floor(box[["ymin"]] * 4) / 4, ceiling(box[["ymax"]] * 4) / 4, by = WIND_STEP_DEG),
    lon = seq(floor(box[["xmin"]] * 4) / 4, ceiling(box[["xmax"]] * 4) / 4, by = WIND_STEP_DEG)
  )
  message("  wind grid points: ", nrow(grid))
  resp <- httr2::request("https://archive-api.open-meteo.com/v1/archive") |>
    httr2::req_url_query(
      latitude = paste(grid$lat, collapse = ","), longitude = paste(grid$lon, collapse = ","),
      start_date = WIND_MONTH[["start"]], end_date = WIND_MONTH[["end"]],
      hourly = "wind_speed_10m,wind_direction_10m", wind_speed_unit = "ms",
      models = "era5", timezone = "GMT"
    ) |>
    httr2::req_retry(max_tries = 3) |>
    httr2::req_perform() |>
    httr2::resp_body_json(simplifyVector = TRUE)
  # one row per grid point; the returned cell centre is recorded beside the asked point
  hourly <- seq_len(nrow(grid)) |> map(\(i) {
    tibble::tibble(
      asked_lat = grid$lat[i], asked_lon = grid$lon[i],
      lat = resp$latitude[i], lon = resp$longitude[i],
      time = resp$hourly$time[[i]],
      speed_ms = resp$hourly$wind_speed_10m[[i]],
      from_deg = resp$hourly$wind_direction_10m[[i]]
    )
  }) |> bind_rows()
  utils::write.csv(hourly, path, row.names = FALSE)
}

main()
