#!/usr/bin/env Rscript
# Day 1 step 27: the images on the Day 1 web page, cut from the finished 300 dpi maps (step 24).
#   page   : each whole map at 1,275 px wide
#   detail : a full-resolution window on the border and the lower Kettle (1,300 x 700 px), clear of the key
#   thumb  : the calendar tile, 360 px square, from the Strahler map
# The unthinned comparison crop needs the unthinned render: MC26_TAG="" MC26_VARIANT=shreve Rscript 24_final_static.R
# The web images are WebP at quality 90 with sharp colour edges (about a quarter of the PNG size; at 80 the amber dots dull).
# The full-resolution PNGs stay in day-01/out.
# In : day-01/out/day01_final_*.png   Out: site/img/day01_*.webp
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages(library(magick))
IMG <- file.path(ROOT, "site", "img")
web <- function(img, name) image_write(img, file.path(IMG, paste0(name, ".webp")), format = "webp", quality = 90,
                                       defines = c("webp:use-sharp-yuv" = "true"))
DETAIL <- "1300x700+720+1960"           # width x height + left + top, in pixels of the 2,550 x 3,300 page: the border runs across the middle
THUMB  <- "1900x1900+380+520"           # the basin without the header, then scaled to 360 px

for (v in c("strahler", "shreve")) {
  m <- image_read(file.path(OUT_DIR, paste0("day01_final_", v, ".png")))
  web(image_resize(m, "1275x"), paste0("day01_", v, "_page"))
  web(image_crop(m, DETAIL), paste0("day01_", v, "_detail"))
  if (v == "strahler") web(image_resize(image_crop(m, THUMB), "360x360"), "day01_thumb")
}
unthinned <- file.path(OUT_DIR, "day01_final_shreve_unthinned.png")
if (file.exists(unthinned)) {
  web(image_crop(image_read(unthinned), DETAIL), "day01_shreve_detail_unthinned")
} else message("no unthinned render; the comparison crop is left as it is")
cat("site images written to", IMG, "\n")
