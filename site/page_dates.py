"""Posted and revised dates for every map page, from git history.

Writes site/data/dates.json, which the `dates` shortcode (site/dates.lua) prints under each page's
title, and fills the dates line in the two standalone pages (day09/, day10/). Run it before each
commit that adds or revises a day; the deploy workflow clones only the latest commit, so the dates
cannot be computed there.

- Posted: the day the page file was first committed (today, for a page not committed yet).
- Revised: the last commit that touched any of that day's files (its page, scripts, styles, images,
  data and day-NN/ folder). A commit that touches three or more days is a site-wide change (like the
  one that added these dates) and does not count as a revision.

usage: python3 -I site/page_dates.py   (from the repo root or anywhere inside it)
"""
import datetime as dt
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

SWEEP = 3  # a commit touching this many days or more is site-wide
ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           check=True, cwd=Path(__file__).parent).stdout.strip())
SITE = ROOT / "site"
STANDALONE = ["site/day09/index.html", "site/day10/index.html"]
PATTERNS = [r"^site/day-(\d\d)[-.]", r"^site/day(\d\d)", r"^site/(?:js|css|img|data)/day(\d\d)", r"^day-(\d\d)/"]


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True, cwd=ROOT).stdout


def day_of(path):
    for p in PATTERNS:
        m = re.match(p, path)
        if m:
            return int(m.group(1))
    return None


def long_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"


# every commit, oldest first: (date, files)
commits, cur = [], None
for line in git("log", "--reverse", "--format=@%as", "--name-only").splitlines():
    if line.startswith("@"):
        cur = (line[1:], []); commits.append(cur)
    elif line.strip():
        cur[1].append(line.strip())

touched = defaultdict(list)            # day -> dates of commits that revised it
added = {}                             # path -> first commit date
for date, files in commits:
    days = {d for d in map(day_of, files) if d is not None}
    for f in files:
        added.setdefault(f, date)
    if len(days) < SWEEP:
        for d in days:
            touched[d].append(date)

pages = [p for p in git("ls-files", "site").splitlines()
         if re.match(r"^site/day-\d\d[^/]*\.qmd$", p)] + STANDALONE
today = dt.date.today().isoformat()
out = {}
for p in pages:
    d = day_of(p)
    posted = added.get(p, today)
    revised = max([posted] + touched.get(d, []))
    key = p[len("site/"):]
    out[key] = {"day": d, "posted": posted, "revised": revised,
                "posted_text": long_date(posted), "revised_text": long_date(revised)}


def line_html(e):
    s = f'Posted <time datetime="{e["posted"]}">{e["posted_text"]}</time>'
    if e["revised"] != e["posted"]:
        s += f' · Revised <time datetime="{e["revised"]}">{e["revised_text"]}</time>'
    return s


(SITE / "data" / "dates.json").write_text(json.dumps(out, indent=1) + "\n")
for p in STANDALONE:
    f = ROOT / p
    t = f.read_text()
    filled = line_html(out[p[len("site/"):]])
    t2, n = re.subn(r'(<p class="dates"[^>]*>).*?(</p>)', lambda m: m.group(1) + filled + m.group(2), t, count=1)
    if n != 1:
        raise SystemExit(f'{p}: no <p class="dates"> line to fill')
    if t2 != t:
        f.write_text(t2)
for k, e in out.items():
    print(f'{k:22} posted {e["posted"]}  revised {e["revised"]}')
