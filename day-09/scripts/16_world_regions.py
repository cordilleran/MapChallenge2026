"""Add a World Bank region column to the app's world outline file (D136).

`app/data/world50.json` holds Natural Earth 1:50m admin-0 countries with the
UN M49 region and subregion (Natural Earth REGION_UN, SUBREGION). This adds
`region_wb` (Natural Earth REGION_WB, the World Bank's seven regions) as the
last column, matched on the two-letter code (ISO_A2_EH, which fills the codes
Natural Earth leaves as -99). Re-running is safe: the column is replaced.

Usage: python 16_world_regions.py   (paths from MC26_DAY09_DIR)
"""
import glob
import json
import os
import sys
from pathlib import Path

import pyogrio

DAY = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
SHP = glob.glob(str(DAY / "raw-261108/ne/x_ne_50m_admin_0_countries/*.shp"))[0]
WORLD = Path(__file__).resolve().parents[1] / "app/data/world50.json"

def main():
    ne = pyogrio.read_dataframe(SHP, read_geometry=False, columns=["ISO_A2_EH", "NAME", "REGION_WB"])
    by_code = {c: r for c, r in zip(ne.ISO_A2_EH, ne.REGION_WB) if c != "-99"}
    by_name = dict(zip(ne.NAME, ne.REGION_WB))

    w = json.loads(WORLD.read_text())
    if "region_wb" in w["cols"]:
        k = w["cols"].index("region_wb")
        w["cols"].pop(k)
        for r in w["rows"]:
            r.pop(k)
    miss = []
    for r in w["rows"]:
        wb = by_code.get(r[0]) or by_name.get(r[1])
        if wb is None:
            miss.append(r[1])
        r.append(wb)
    w["cols"].append("region_wb")
    w["note"] = w["note"].split(" World Bank")[0] + " World Bank regions from Natural Earth REGION_WB (16_world_regions.py)."
    WORLD.write_text(json.dumps(w, separators=(",", ":")))
    print(f"{len(w['rows'])} countries; no World Bank region for {len(miss)}: {miss}")


if __name__ == "__main__":
    main()
