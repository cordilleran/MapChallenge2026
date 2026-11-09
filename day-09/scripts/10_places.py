"""Day 9 slice S6: places, urban-rural classes, regions and North-South lenses.

Builds three tables in `day09.duckdb`:

- `places`: every origin institution and every study place (a candidate the
  role call marked `study_site` or `data_extent`), one row per place, with:
  - `kind`: point (a town, institution, river, peak, lake) or area (country,
    admin area, continent, ocean, region);
  - `smod`: the GHS-SMOD 2020 class of the 1 km cell under a point
    (30 urban centre ... 11 very low density rural, 10 water), sampled with
    `gdallocationinfo`; areas get none;
  - `ur`: urban (21 to 30), rural (11 to 13), water (10), feature (a river,
    lake, glacier, island or peak: its GeoNames point, often the mouth, has
    no meaningful cell class), area, or unknown;
  - `region` and `subregion` (UN, from Natural Earth admin-0), and three
    North-South lenses (D105): `ns_m49` (UN M49's former developed regions:
    Europe, Northern America, Japan, Australia and New Zealand), `ns_wb`
    (World Bank high income, from Natural Earth's INCOME_GRP), `ns_brandt`
    (north of the 1980 Brandt line: Northern America, Europe, the former
    USSR, Japan, Australia and New Zealand);
- `papers`: one row per academic record with scope, OpenAlex field, top topic
  and top three keywords (D112), and how it was placed;
- `arcs`: one row per (record, origin, study place) with the author weight in
  both origin views.

Global papers have no study place; they are drawn as a halo at the origin.

Usage: python 10_places.py
"""
import csv
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
RAW = OUT_DIR / "raw-261108"
SMOD_ZIP = RAW / "ghs" / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.zip"
NE_ZIP = RAW / "ne" / "ne_50m_admin_0_countries.zip"
AREA_CODES = ("PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "ADM1", "ADM2", "CONT", "OCN", "SEA",
              "RGN", "GULF", "AREA", "PRK", "MTS", "PLAT", "VAL", "PEN", "ISLS", "BAY")
M49_NORTH_SUB = {"Northern America", "Northern Europe", "Western Europe", "Southern Europe",
                 "Eastern Europe", "Australia and New Zealand"}
FORMER_USSR = {"RU", "UA", "BY", "MD", "EE", "LV", "LT", "GE", "AM", "AZ", "KZ", "UZ", "TM", "KG", "TJ"}


def smod_tif():
    """Extract the GeoTIFF once beside the zip (the zip stays as downloaded)."""
    out = RAW / "ghs" / "x"
    tifs = list(out.glob("*.tif"))
    if not tifs:
        with zipfile.ZipFile(SMOD_ZIP) as z:
            z.extractall(out)
        tifs = list(out.glob("*.tif"))
    return tifs[0]


def sample_smod(tif, pts):
    """pts: list of (lon, lat). Returns a list of int or None, same order."""
    if not pts:
        return []
    inp = "\n".join(f"{lon} {lat}" for lon, lat in pts) + "\n"
    p = subprocess.run(["gdallocationinfo", "-valonly", "-wgs84", str(tif)],
                       input=inp, capture_output=True, text=True, check=True)
    vals = p.stdout.split("\n")
    out = []
    for i in range(len(pts)):
        v = vals[i].strip() if i < len(vals) else ""
        out.append(int(float(v)) if v not in ("", "-200") else None)
    return out


def ne_countries():
    d = RAW / "ne" / "x_admin0"
    if not list(d.glob("*.shp")):  # also redo an interrupted extraction (S5 review 3.3)
        with zipfile.ZipFile(NE_ZIP) as z:
            z.extractall(d)
    shp = next(d.glob("*.shp"))
    p = subprocess.run(["ogr2ogr", "-f", "CSV", "/vsistdout/", str(shp), "-select",
                        "ISO_A2,ISO_A2_EH,ADM0_A3,NAME,REGION_UN,SUBREGION,INCOME_GRP"],
                       capture_output=True, text=True, check=True)
    rows, seen = [], set()
    # One row per ISO code: the feature whose own ISO_A2 is the code wins over
    # dependencies that share it through ISO_A2_EH (Ashmore and Cartier is "AU").
    recs = sorted(csv.DictReader(io.StringIO(p.stdout)), key=lambda r: r["ISO_A2"] in ("", "-99"))
    for r in recs:
        iso = r["ISO_A2_EH"] if r["ISO_A2_EH"] not in ("", "-99") else r["ISO_A2"]
        if iso in ("", "-99") or iso in seen:
            continue
        seen.add(iso)
        sub = r["SUBREGION"]
        rows.append((iso, r["NAME"], r["REGION_UN"], sub,
                     sub in M49_NORTH_SUB or iso == "JP",
                     r["INCOME_GRP"].startswith(("1.", "2.")),
                     r["REGION_UN"] == "Europe" or sub == "Northern America" or iso in FORMER_USSR
                     or iso in ("JP", "AU", "NZ")))
    return rows


FEATURE_CODES = ("STM", "LK", "RSV", "GLCR", "ISL", "MT", "BAY", "LKS", "STMS")


def ur_class(v, kind, fcode):
    if kind == "area":
        return "area"
    if fcode in FEATURE_CODES:
        return "feature"  # a river's or lake's GeoNames point (often its mouth) has no meaningful cell class
    if v is None:
        return "unknown"
    if v >= 21:
        return "urban"
    if v >= 11:
        return "rural"
    return "water"


def main():
    tif = smod_tif()
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    con.execute("CREATE OR REPLACE TABLE countries (iso VARCHAR, name VARCHAR, region VARCHAR, "
                "subregion VARCHAR, ns_m49 BOOLEAN, ns_wb BOOLEAN, ns_brandt BOOLEAN)")
    con.executemany("INSERT INTO countries VALUES (?,?,?,?,?,?,?)", ne_countries())

    # Study places: role-call study_site or data_extent, joined back to the gazetteer match.
    study = con.execute("""
        SELECT 'g' || m.geonameid AS place_id, min(m.name), any_value(m.fcode), any_value(m.country),
               any_value(m.lat), any_value(m.lon)
        FROM roles r JOIN mentions_l1 m
          ON m.record_id = r.record_id AND m.surface = r.surface
         AND m.field IN ('title','abstract','keywords','jurisdiction')
        WHERE r.role IN ('study_site','data_extent') GROUP BY 1""").fetchall()
    insts = con.execute("""SELECT 'i' || inst_id, any_value(inst), 'INST', any_value(country),
                                  any_value(lat), any_value(lon) FROM origins GROUP BY 1""").fetchall()
    rows = study + insts
    kinds = ["area" if r[2] in AREA_CODES else "point" for r in rows]
    vals = sample_smod(tif, [(r[5], r[4]) for r, k in zip(rows, kinds) if k == "point"])
    it = iter(vals)
    out = []
    for r, k in zip(rows, kinds):
        v = next(it) if k == "point" else None
        out.append((*r, k, v, ur_class(v, k, r[2])))
    con.execute("""CREATE OR REPLACE TABLE places (place_id VARCHAR, name VARCHAR, fcode VARCHAR,
                   country VARCHAR, lat DOUBLE, lon DOUBLE, kind VARCHAR, smod INTEGER, ur VARCHAR)""")
    con.executemany("INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?)", out)
    con.execute("""CREATE OR REPLACE TABLE places AS
        SELECT p.*, c.region, c.subregion, c.ns_m49, c.ns_wb, c.ns_brandt
        FROM places p LEFT JOIN countries c ON c.iso = p.country""")

    con.execute("""
    CREATE OR REPLACE TABLE papers AS
    WITH kw AS (SELECT doi, string_agg(keyword, '; ' ORDER BY score DESC) AS kws
                FROM (SELECT *, row_number() OVER (PARTITION BY doi ORDER BY score DESC) rk FROM oa_keywords)
                WHERE rk <= 3 GROUP BY doi),
         tp AS (SELECT doi, topic, subfield, field FROM oa_topics WHERE rank = 0
                QUALIFY row_number() OVER (PARTITION BY doi ORDER BY score DESC) = 1),
         st AS (SELECT DISTINCT record_id FROM roles WHERE role IN ('study_site','data_extent')),
         og AS (SELECT DISTINCT record_id FROM origins)
    SELECT r.record_id, r.year, r.itype, s.scope, tp.field, tp.subfield, tp.topic, kw.kws AS keywords,
           og.record_id IS NOT NULL AS has_origin, st.record_id IS NOT NULL AS has_study_place
    FROM records r LEFT JOIN scopes s USING (record_id) LEFT JOIN tp ON tp.doi = r.doi
    LEFT JOIN kw ON kw.doi = r.doi LEFT JOIN og USING (record_id) LEFT JOIN st USING (record_id)
    WHERE r.academic""")

    con.execute("""
    CREATE OR REPLACE TABLE arcs AS
    WITH sp AS (
        SELECT DISTINCT r.record_id, 'g' || m.geonameid AS dest_id
        FROM roles r JOIN mentions_l1 m ON m.record_id = r.record_id AND m.surface = r.surface
         AND m.field IN ('title','abstract','keywords','jurisdiction')
        WHERE r.role IN ('study_site','data_extent')
          AND r.record_id NOT IN (SELECT record_id FROM scopes WHERE scope = 'global')),  -- global papers are halos (S5 review 1.4)
    nsp AS (SELECT record_id, count(*) AS n_dest FROM sp GROUP BY 1)
    SELECT o.record_id, 'i' || o.inst_id AS origin_id, sp.dest_id,
           o.w_all / nsp.n_dest AS w_all, CASE WHEN o.corr_view THEN o.w_corr / nsp.n_dest END AS w_corr
    FROM origins o JOIN sp USING (record_id) JOIN nsp USING (record_id)""")

    print(con.execute("""SELECT left(place_id,1) AS src, kind, ur, count(*) n FROM places
                         GROUP BY ALL ORDER BY ALL""").df().to_string(index=False))
    print(con.execute("SELECT count(*) arcs, count(DISTINCT record_id) records FROM arcs").df().to_string(index=False))
    print(con.execute("""SELECT scope, count(*) n, sum(has_study_place::INT) placed, sum(has_origin::INT) with_origin
                         FROM papers GROUP BY 1 ORDER BY 2 DESC""").df().to_string(index=False))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
