#!/usr/bin/env Rscript
# Day 2 step 03: the images on the Day 2 web page, cut from the finished 300 dpi map (step 02), as WebP at quality 90
# with sharp colour edges (as Day 1). The full-resolution PNG stays local in day-02/out.
#   page   : the whole map at 1,275 px wide
#   detail : a full-resolution window on the lower Granby, where it meanders toward Grand Forks
#   thumb  : the calendar tile, 360 px square
# In : day-02/out/day02_final.png   Out: site/img/day02_*.webp
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
source(file.path(.here, "..", "config.R"))
suppressMessages(library(magick))
IMG <- file.path(ROOT, "site", "img")
DETAIL <- "1300x1000+1250+2000"        # width x height + left + top, in pixels of the 2,550 x 3,300 page
THUMB  <- "1250x1250+1260+1560"        # the lower basin down to the mouth, then scaled to 360 px
web <- function(img, name) image_write(img, file.path(IMG, paste0(name, ".webp")), format = "webp", quality = 90,
                                       defines = c("webp:use-sharp-yuv" = "true"))
m <- image_read(file.path(OUT_DIR, "day02_final.png"))
web(image_resize(m, "1275x"), "day02_page")
web(image_crop(m, DETAIL), "day02_detail")
web(image_resize(image_crop(m, THUMB), "360x360"), "day02_thumb")
cat("site images written to", IMG, "\n")
