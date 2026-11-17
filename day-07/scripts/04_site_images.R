#!/usr/bin/env Rscript
# Day 7 step 04: the images on the Day 7 web page, cut from the finished 300 dpi map (step 03)
# as WebP at quality 90 with sharp colour edges (D44). The full-resolution PNG stays local.
#   page   : the whole map at 1,200 px wide, shown in the zoom viewer until its tiles arrive
#            (the viewer now carries the legible detail; was 2,400 px, D312)
#   detail : a full-resolution window on Duluth and the head of the lake
#   divide : a full-resolution window on Hibbing and the Hill of Three Waters
#   thumb  : the calendar tile, 360 px square, on the triple divide and the range
# Crops are centred on the pixel positions step 03 writes to out/day07_B_layout.json.
# In : day-07/out/day07_B.png, day07_B_layout.json   Out: site/img/day07_*.webp
#
# Layout: main() first, helpers below, main() called on the last line.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages(library(magick))

IMG_DIR <- file.path(ROOT, "site", "img")
PAGE_PX <- 1200
DETAIL_PX <- c(w = 1400, h = 1000)
THUMB_SRC_PX <- 1100
THUMB_PX <- 360

main <- function() {
  map <- image_read(file.path(OUT_DIR, "day07_B.png"))
  spots <- jsonlite::read_json(file.path(OUT_DIR, "day07_B_layout.json"), simplifyVector = TRUE)
  map |> image_resize(paste0(PAGE_PX, "x")) |> write_webp("day07_page")
  map |> image_crop(centred(spots$duluth, DETAIL_PX, spots$page_px)) |> write_webp("day07_detail")
  map |> image_crop(centred(spots$three_waters, DETAIL_PX, spots$page_px)) |> write_webp("day07_divide")
  map |>
    image_crop(centred(spots$three_waters + c(250, 150), c(w = THUMB_SRC_PX, h = THUMB_SRC_PX), spots$page_px)) |>
    image_resize(paste0(THUMB_PX, "x", THUMB_PX)) |>
    write_webp("day07_thumb")
  cat("site images written to", IMG_DIR, "\n")
}

# A magick geometry string for a w x h window centred on `at`, kept inside the page
centred <- function(at, size, page_px) {
  left <- min(max(0, at[1] - size[["w"]] / 2), page_px[1] - size[["w"]])
  top <- min(max(0, at[2] - size[["h"]] / 2), page_px[2] - size[["h"]])
  sprintf("%dx%d+%d+%d", size[["w"]], size[["h"]], round(left), round(top))
}

# Writes `img` as IMG_DIR/<name>.webp, quality 90, sharp YUV; returns `img` invisibly.
write_webp <- function(img, name) {
  dir.create(IMG_DIR, showWarnings = FALSE, recursive = TRUE)
  image_write(img, file.path(IMG_DIR, paste0(name, ".webp")), format = "webp", quality = 90,
              defines = c("webp:use-sharp-yuv" = "true"))
  invisible(img)
}

main()
