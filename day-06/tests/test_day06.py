"""Checks for Day 6 that can fail. Run after the pipeline: python3 day-06/tests/test_day06.py

They read the derived files (MC26_DAY06_DIR) and the site page, and check:
1. georeferencing: the held-out station error stays under 200 m;
2. the 1913 ice: the central area lies inside its method range, and most 1985 ice lies inside it;
3. order: 1913 ice > 1985 ice > 2021 ice;
4. the page quotes the numbers in site/data/day06.json, rounded as written;
5. summit heights quoted on the page match derived/map.gpkg, and each height printed comes from OSM;
6. the colour match fits each ink of the scan to its target within 0.1 OD.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
os.environ.setdefault("MC26_SHEET16", "unused-by-tests")

from sheet import DERIVED

SITE = HERE.parent / "site"
fails = []


def r(x):
    """Round half up, as the page is written (Python's round() gives 156 for 156.5)."""
    return int(x + 0.5)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main():
    g = json.loads((DERIVED / "georef_report.json").read_text())
    check(g["held_out_rms_m"] < 200, f"held-out georeferencing RMS {g['held_out_rms_m']} m < 200 m")
    check(g["warp_check_m"] < 1, f"the warp reproduces the georeferencing model (largest gap {g['warp_check_m']} m)")

    c = json.loads((DERIVED / "compare_metrics.json").read_text())
    a, (lo, hi) = c["area_km2"], c["area_1913_range_km2"]
    check(lo <= a["1913"] <= hi, f"1913 central area {a['1913']} within its range {lo} to {hi}")
    check(c["share_1985_inside_1913"] >= 0.8, f"share of 1985 ice inside 1913 line {c['share_1985_inside_1913']} >= 0.8")
    check(a["1913"] > a["1985"] > a["2021"], f"areas shrink: {a['1913']} > {a['1985']} > {a['2021']}")

    site = json.loads((SITE / "data" / "day06.json").read_text())
    check(site["area_km2"] == a, "site/data/day06.json matches derived/compare_metrics.json")
    page = (SITE / "day-06.qmd").read_text()
    lo_pct, hi_pct = site["loss_1913_2021_pct_range"]
    lo_a, hi_a = site["area_1913_range_km2"]
    quoted = {
        f"about **{r(a['1913'])} km²**": "1913 area",
        f"{r(a['1985'])} km² in 1985": "1985 area",
        f"{r(a['2021'])} km² in 2021": "2021 area",
        f"about {r(site['loss_1913_2021_pct'])} %": "loss",
        f"{r(lo_pct)} to {r(hi_pct)} %": "loss range",
        f"{r(lo_a)} to {r(hi_a)} km²": "1913 range",
        f"{r(100 * site['share_1985_inside_1913'])} % of the 1985 ice": "1985 share",
        f"**{r(site['georef_held_out_rms_m'])} m**": "georeferencing error",
    }
    for text, what in quoted.items():
        check(text in page, f"page quotes the {what} as '{text}'")
    stray = re.findall(r"\b\d{2,3}(?:\.\d+)? km²", page)
    allowed = {f"{r(v)} km²" for v in (a["1913"], a["1985"], a["2021"], hi_a)}
    check(all(s in allowed for s in stray), f"no other km² figures on the page ({sorted(set(stray))})")
    from osgeo import ogr
    ogr.UseExceptions()
    ds = ogr.Open(str(DERIVED / "map.gpkg"))
    peaks = list(ds.GetLayerByName("peaks"))  # a list, not keyed by name: two summits can share one
    for name, ft in (("Mount Balfour", 10735), ("Trolltinder Mountain", 9570)):
        hits = [f for f in peaks if f["name"] == name]
        check(len(hits) == 1 and hits[0]["ele_ft"] == ft and hits[0]["show_ele"] == 1, f"{name} printed once, at {ft} ft")
        check(f"{ft:,}" in page, f"page quotes {name} as {ft:,}")
    pk = ogr.Open(str(DERIVED / "peaks.gpkg"))
    shown = [f for f in peaks if f["show_ele"] == 1]
    src = {(f["name"], round(f.GetGeometryRef().GetX()), round(f.GetGeometryRef().GetY())): f["ele_src"]
           for f in pk.GetLayerByName("peaks")}
    key = [(f["name"], round(f.GetGeometryRef().GetX()), round(f.GetGeometryRef().GetY())) for f in shown]
    check(all(src.get(k) == "OSM" for k in key), f"all {len(key)} printed summit heights are OSM heights")

    # Reviewed places where blue creeks were read as ice (data/not_ice.json) stay out of the 1913 ice.
    ice = ogr.Open(str(DERIVED / "ice1913.gpkg"))
    for pt in json.loads((HERE / "data" / "not_ice.json").read_text())["points"]:
        p = ogr.Geometry(ogr.wkbPoint)
        p.AddPoint_2D(pt["E"], pt["N"])
        inside = any(f.GetGeometryRef().Contains(p) for f in ice.GetLayer(0))
        check(not inside, f"not-ice point E{pt['E']} N{pt['N']} is outside the 1913 ice")

    col = json.loads((DERIVED / "scan_colour.json").read_text())
    err = max(max(abs(a - b) for a, b in zip(v["mapped_od"], v["target_od"], strict=True)) for v in col["plates"].values())
    check(err < 0.1, f"colour match within 0.1 OD for every ink (worst {err:.3f})")
    if fails:
        sys.exit(f"{len(fails)} check(s) failed")


if __name__ == "__main__":
    main()
