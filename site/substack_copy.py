"""A plain copy of any day page for pasting into Substack, with images and links on the live site.

Loads the page in headless Chromium (so numbers filled in by the page's script are there), then keeps
only what Substack's editor keeps on paste: headings, paragraphs, lists, links, emphasis and images,
one image per row. Interactive parts (a zoom viewer, an iframe, a canvas map) become their still
image when the element names one in `data-still` (alt text in `data-still-alt`), otherwise a link to the live page. Fold-down
sections (methods, sources) and controls are left out; a closing line links to them.

Every image and link points at the live site, so publish the day before pasting.

usage: substack_copy.py PAGE OUT_HTML [--base URL]
  PAGE  the page's path on the site, e.g. day-15.html or day09/
  --base  where to load the page from (default: the live site; use http://127.0.0.1:PORT/ for a local build)
needs: beautifulsoup4, and chromium on PATH
"""
import argparse
import subprocess
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment

LIVE = "https://cordilleran.github.io/MapChallenge2026/"
KEEP = {"h1", "h2", "h3", "p", "ul", "ol", "li", "a", "em", "strong", "i", "b", "img", "blockquote", "br"}
DROP = {"script", "style", "link", "noscript", "button", "select", "input", "label", "form", "svg",
        "details", "nav", "audio", "video", "template", "meta"}
INTERACTIVE = {"iframe", "canvas"}

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("page"); ap.add_argument("out"); ap.add_argument("--base", default=LIVE)
args = ap.parse_args()
page_live = urljoin(LIVE, args.page)

dom = subprocess.run(["chromium-browser", "--headless=new", "--no-sandbox", "--virtual-time-budget=8000",
                      "--window-size=1200,2000", "--dump-dom", urljoin(args.base, args.page)],
                     capture_output=True, text=True, check=True, timeout=120).stdout
soup = BeautifulSoup(dom, "html.parser")
title = soup.title.get_text(strip=True) if soup.title else args.page
root = soup.select_one(".wrap.day") or soup.body


def live(url):
    """A page-relative URL as seen from the live page."""
    return urljoin(page_live, url)


# 1. interactive blocks: a named still, or a link to the live page
for el in root.find_all(attrs={"data-still": True}):
    img = soup.new_tag("img", src=live(el["data-still"]), alt=el.get("data-still-alt") or el.get("aria-label") or title)
    el.replace_with(img)
for tag in INTERACTIVE:
    for el in root.find_all(tag):
        if root not in el.parents:        # already removed with an earlier block
            continue
        box = el
        while (box.parent is not None and box.parent is not root and box.parent.name in {"div", "section"}
               and not box.parent.find_all(["p", "h2", "h3"])):
            box = box.parent
        p = soup.new_tag("p"); a = soup.new_tag("a", href=page_live); a.string = "Open the interactive map on the live page →"
        p.append(a); box.replace_with(p)

# 2. drop controls, fold-downs, comments and hidden parts
for el in root.find_all(DROP):
    el.decompose()
for el in root.find_all(attrs={"hidden": True}):
    el.decompose()
for c in root.find_all(string=lambda s: isinstance(s, Comment)):
    c.extract()

# 3. figure captions become an italic line; images link to the live page
for cap in root.find_all("figcaption"):
    p = soup.new_tag("p"); em = soup.new_tag("em"); em.string = cap.get_text(" ", strip=True)
    p.append(em); cap.replace_with(p)
for img in root.find_all("img"):
    src = live(img.get("src", ""))
    if src.startswith("data:") or not img.get("src"):
        img.decompose(); continue
    new = soup.new_tag("img", src=src, alt=img.get("alt", ""))
    if img.parent and img.parent.name == "a":
        link = img.parent
        link["href"] = live(link.get("href", page_live)); img.replace_with(new)
        if link.parent is not None and link.parent.name != "p":
            link.wrap(soup.new_tag("p"))
    else:
        a = soup.new_tag("a", href=page_live); a.append(new)
        p = soup.new_tag("p"); p.append(a); img.replace_with(p)

# 4. keep only the tags Substack keeps; unwrap the rest; absolute links; no empty paragraphs
for el in list(root.find_all(True)):
    if el.name not in KEEP:
        if el.next_sibling is not None and getattr(el.next_sibling, "name", None):
            el.insert_after(" ")          # labels side by side stay apart once unwrapped
        el.unwrap(); continue
    attrs = {}
    if el.name == "a" and el.get("href"):
        attrs["href"] = live(el["href"])
    if el.name == "img":
        attrs = {"src": el["src"], "alt": el.get("alt", "")}
    el.attrs = attrs
for a in root.find_all("a"):              # heading anchors and other empty links
    if not a.get_text(strip=True) and not a.find("img"):
        a.decompose()
for p in root.find_all(["p", "li"]):
    if not p.get_text(strip=True) and not p.find("img"):
        p.decompose()

# 5. a page with no image left (an app page) leads with its link-preview image
if not root.find("img"):
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        h1 = root.find("h1")
        p = soup.new_tag("p"); a = soup.new_tag("a", href=page_live)
        a.append(soup.new_tag("img", src=og["content"], alt=title)); p.append(a)
        (h1.insert_after(p) if h1 else root.insert(0, p))

body = root.decode_contents() if root.name != "body" else "".join(str(c) for c in root.contents)
html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>body{{max-width:728px;margin:2em auto;padding:0 16px;font:18px/1.6 Georgia,serif;color:#222;background:#fff}}img{{display:block;max-width:100%;height:auto}}</style>
</head><body>
{body}
<p><a href="{page_live}">The live page: interactive map, methods and sources</a></p>
</body></html>
"""
with open(args.out, "w") as f:
    f.write(html)
print("wrote", args.out)
