#!/usr/bin/env Rscript
# Day 2 step 03: the images on the Day 2 web page, cut from the finished 300 dpi map
# (step 02), as WebP at quality 90 with sharp colour edges (as Day 1). The full-resolution
# PNG stays local in day-02/out.
#   page   : the whole map at 1,275 px wide
#   detail : a full-resolution window on the lower Granby, where it meanders toward
#            Grand Forks
#   thumb  : the calendar tile, 360 px square
# In : day-02/out/day02_final.png   Out: site/img/day02_*.webp
#
# Layout: main() first, helpers below, main() called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages(library(magick))

IMG_DIR <- file.path(ROOT, "site", "img")
# Crops: width x height + left + top, in pixels of the 2,550 x 3,300 page. The map is
# drawn in UTM 11N, which put the mouth 108 px left of where BC Albers put it, so both
# crops start 108 px further left than they did before the reprojection.
DETAIL_CROP <- "1300x1000+1142+2000"
THUMB_CROP <- "1250x1250+1152+1560"   # the lower basin down to the mouth, scaled to 360 px
THUMB_PX <- 360
PAGE_PX <- 1275

main <- function() {
  map <- image_read(file.path(OUT_DIR, "day02_final.png"))
  map |>
    image_resize(paste0(PAGE_PX, "x")) |>
    write_webp(IMG_DIR, "day02_page")
  map |>
    image_crop(DETAIL_CROP) |>
    write_webp(IMG_DIR, "day02_detail")
  map |>
    image_crop(THUMB_CROP) |>
    image_resize(paste0(THUMB_PX, "x", THUMB_PX)) |>
    write_webp(IMG_DIR, "day02_thumb")
  cat("site images written to", IMG_DIR, "\n")
}

# Writes `img` as <dir>/<name>.webp, quality 90, sharp YUV; returns `img` invisibly.
write_webp <- function(img, dir, name) {
  dir.create(dir, showWarnings = FALSE, recursive = TRUE)
  image_write(img, file.path(dir, paste0(name, ".webp")), format = "webp", quality = 90,
              defines = c("webp:use-sharp-yuv" = "true"))
  invisible(img)
}

main()
