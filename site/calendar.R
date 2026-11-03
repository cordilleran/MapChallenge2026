#!/usr/bin/env Rscript
# Writes the calendar (site/_calendar.md) from site/days.yml. Run it after editing days.yml:
#   Rscript site/calendar.R
# The page (index.qmd) includes the file, so building the site runs no R.
.here <- dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1]))
out <- file(file.path(.here, "_calendar.md"), "w")
sink(out)
cat("```{=html}\n")
library(yaml)
days <- yaml::read_yaml(file.path(.here, "days.yml"))
start <- as.Date("2026-11-01")
lead <- as.POSIXlt(start)$wday                      # 0 = Sunday
icon <- function(k) paste(readLines(file.path(.here, "icons", paste0(k, ".svg")), warn = FALSE), collapse = "")
esc <- function(x) gsub("&", "&amp;", x, fixed = TRUE)
tile <- function(d) {
  st <- d$status
  front <- sprintf('<span class="n">%d</span><span class="ico">%s</span><span class="t">%s</span>', d$day, icon(d$icon), esc(d$theme))
  if (st == "done" && nzchar(d$thumb) && nzchar(d$href)) {
    # done: an advent door. The glyph side flips to the map, and the map links to the day's page.
    back <- sprintf('<span class="n">%d</span><img src="%s" alt=""><span class="t">%s</span>', d$day, d$thumb, esc(d$theme))
    sprintf(paste0('<div class="tile done flip" data-day="%d"><div class="card">',
                   '<button type="button" class="face front" aria-label="Day %d, %s: open">%s</button>',
                   '<a class="face back" href="%s" aria-label="Day %d, %s: go to the map">%s</a></div></div>'),
            d$day, d$day, esc(d$theme), front, d$href, d$day, esc(d$theme), back)
  } else {
    sprintf('<div class="tile %s" data-day="%d" aria-label="Day %d, %s, %s"><span class="face">%s</span></div>', st, d$day, d$day, esc(d$theme), st, front)
  }
}
cat('<main class="wrap">\n')
cat('<header><p class="kicker">30 Day Map Challenge · November 2026</p><h1>Every day or so, a map.</h1></header>\n')
cat('<div class="cal" aria-label="November 2026, one tile per day">\n')
for (w in c("Sun","Mon","Tue","Wed","Thu","Fri","Sat")) cat(sprintf('<div class="wd" aria-hidden="true">%s</div>\n', w))
for (i in seq_len(lead)) cat('<div class="blank" aria-hidden="true"></div>\n')
for (d in days) cat(tile(d), "\n")
cat('</div>\n')
cat('<footer>Themes from the <a href="https://30daymapchallenge.com/">30 Day Map Challenge</a>. Code and maps: <a href="https://github.com/cordilleran/MapChallenge2026">github.com/cordilleran/MapChallenge2026</a>. Each map says how it was made, including the AI tools used, and credits its data.</footer>\n')
# Browser-side: mark today while the month runs, and make the doors open. Without the script, done tiles show the map.
cat('<script>(function(){',
  'var cal=document.querySelector(".cal");cal.classList.add("js");',
  'var t=new Date();if(t.getFullYear()===2026&&t.getMonth()===10){var e=document.querySelector(\'.tile[data-day="\'+t.getDate()+\'"]\');if(e){e.classList.add("today");e.setAttribute("aria-current","date");}}',
  'var seen=[];try{seen=JSON.parse(localStorage.getItem("mc26-open")||"[]");}catch(x){}',
  'document.querySelectorAll(".flip").forEach(function(f){var d=f.dataset.day,b=f.querySelector(".front"),a=f.querySelector(".back");',
  'function set(o){f.classList.toggle("open",o);b.tabIndex=o?-1:0;a.tabIndex=o?0:-1;b.setAttribute("aria-hidden",o);a.setAttribute("aria-hidden",!o);}',
  'set(seen.indexOf(d)>=0);',
  'b.addEventListener("click",function(){set(true);a.focus({preventScroll:true});if(seen.indexOf(d)<0){seen.push(d);try{localStorage.setItem("mc26-open",JSON.stringify(seen));}catch(x){}}});});',
  '})();</script>\n', sep = "")
cat('</main>\n')
cat("```\n")
sink()
close(out)
message("calendar written: ", file.path(.here, "_calendar.md"))
