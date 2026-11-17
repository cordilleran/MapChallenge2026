#!/usr/bin/env Rscript
# Opt-in: install the R packages Day 7 needs (D318). The pipeline itself never installs
# anything; config.R stops with a list of what is missing. Run this on purpose:
#   Rscript day-07/install_packages.R
# sf and terra need GDAL, GEOS and PROJ on the system first
# (Debian/Ubuntu: libgdal-dev libgeos-dev libproj-dev libudunits2-dev).
needed <- c("sf", "terra", "elevatr", "httr2", "jsonlite", "dplyr", "purrr", "tidyr",
            "ggplot2", "showtext", "sysfonts", "systemfonts", "magick", "igraph", "units", "tibble")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing) == 0) {
  message("All Day 7 packages are installed.")
} else {
  message("Installing: ", paste(missing, collapse = ", "))
  repo <- unname(getOption("repos")["CRAN"])
  if (is.na(repo) || repo == "@CRAN@") repo <- "https://cloud.r-project.org"
  install.packages(missing, repos = repo)
}
