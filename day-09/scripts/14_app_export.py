"""Corpus geography app, W4: export the real corpus in the data contract (D124, D128).

Reads `day09.duckdb` (layer 1: records, scopes, roles, mentions, origins,
places, countries, OpenAlex topics and keywords), `body_probe.duckdb` (the
body pass, D127: scope, setting and verified places) and
`derived-261108/area_settlement.csv` (15_area_settlement.py). Writes:

- `app/data/day09.json`: the public contract. No titles, record ids or text.
  Coarsened by default (D128, D135, D137): years in five-year
  bins, and a study place named by only one paper merged into its province
  or country. `--exact` turns coarsening off.
- `app/data/day09_expected.json`: totals the app must reproduce (tests).
- `app/data/day09_private.json` with `--private`: paper id to cite key and
  title, for the owner's local build. Gitignored; never published.
- `app/data/admin1/<ISO>.json`: province and state outlines (Natural Earth
  1:10m, simplified) for each country the corpus touches, loaded on zoom.

Scope and setting come from the body pass where it read the record, else
from layer 1 (scope) and "unclear" (setting). Places of study are the union
of layer 1 study places and verified body places, each tagged by source.

Usage: python 14_app_export.py [--private] [--exact] [--probe PATH]
"""
import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
RAW = OUT_DIR / "raw-261108"
APP = Path(__file__).resolve().parents[1] / "app" / "data"
SMOD = next((RAW / "ghs" / "x").glob("*.tif"))
ADM1_SHP = next((RAW / "ne" / "x_ne_10m_admin_1").glob("*.shp"))
AREA_CODES = {"PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "ADM1", "ADM2", "CONT", "OCN", "SEA",
              "RGN", "GULF", "AREA", "PRK", "MTS", "PLAT", "VAL", "PEN", "ISLS", "BAY", "ADMD", "ADM3"}
# areas published whatever their paper count: countries, provinces and the big areas; anything finer
# (a county, range, park or bay) named by one paper is merged like a point (preflight Ap1)
WHOLE = {"PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "ADM1", "CONT", "OCN", "SEA"}
BIG = {"CONT", "OCN", "SEA"}            # counted, not drawn: their point is a pole or a centroid
SETTINGS = {"rural", "mixed", "urban", "unclear", "not_applicable"}
# Paper ids are salted hashes of the record id. The salt is a local secret (D136): with a salt
# in the public code, anyone who can guess cite keys could link ids back to papers.
SALT_FILE = OUT_DIR / "pid_salt.txt"
if not SALT_FILE.exists():
    import secrets
    SALT_FILE.write_text(secrets.token_hex(16))
SALT = SALT_FILE.read_text().strip()


def pid(rid):
    return hashlib.sha1((SALT + rid).encode(), usedforsecurity=False).hexdigest()


def sample_smod(pts):
    if not pts:
        return []
    p = subprocess.run(["gdallocationinfo", "-valonly", "-wgs84", str(SMOD)],
                       input="".join(f"{lon} {lat}\n" for lon, lat in pts), capture_output=True, text=True, check=True)
    vals = p.stdout.split("\n")
    return [int(float(v)) if v.strip() not in ("", "-200") else None for v in (vals + [""] * len(pts))[:len(pts)]]


def admin1_table():
    p = subprocess.run(["ogr2ogr", "-f", "CSV", "/vsistdout/", str(ADM1_SHP), "-select",
                        "gn_id,iso_a2,name,latitude,longitude,gn_a1_code"], capture_output=True, text=True, check=True)
    return {r["gn_id"]: r for r in csv.DictReader(io.StringIO(p.stdout)) if r["gn_id"] not in ("", "-1", "0")}


def admin1_outlines(isos):
    """One small file per country: [[gn_id, name, rings], ...] at 0.01 degree."""
    out = APP / "admin1"
    out.mkdir(exist_ok=True)
    gj = json.loads(subprocess.run(["ogr2ogr", "-f", "GeoJSON", "/vsistdout/", str(ADM1_SHP), "-simplify", "0.01",
                                    "-select", "gn_id,iso_a2,name"], capture_output=True, text=True, check=True).stdout)
    by = defaultdict(list)
    for f in gj["features"]:
        g, pr = f["geometry"], f["properties"]
        if not g or pr["iso_a2"] not in isos:
            continue
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = []
        for poly in polys:
            r = [[round(x, 3), round(y, 3)] for x, y in poly[0]]
            r = [r[0]] + [q for i, q in enumerate(r[1:], 1) if q != r[i - 1]]
            if len(r) >= 4:
                rings.append(r)
        by[pr["iso_a2"]].append([str(pr["gn_id"]), pr["name"], rings])
    for iso, feats in by.items():
        (out / f"{iso}.json").write_text(json.dumps(feats, separators=(",", ":"), ensure_ascii=False))
    return sorted(by)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private", action="store_true", help="also write the local-only cite-key file")
    ap.add_argument("--exact", action="store_true", help="no coarsening: exact years and places, for local use only")
    ap.add_argument("--probe", default=str(OUT_DIR / "body_probe.duckdb"))
    a = ap.parse_args()
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"), read_only=True)
    con.execute(f"ATTACH '{a.probe}' AS b (READ_ONLY)")

    recs = con.execute("""
        WITH body AS (SELECT * FROM b.probe_calls WHERE answer IS NOT NULL
                      QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY ts DESC) = 1),
             st AS (SELECT * FROM b.probe_setting)
        SELECT r.record_id, r.year, r.title, s.scope, body.answer IS NOT NULL, st.scope, st.setting, st.quote_ok, st.labels
        FROM records r LEFT JOIN scopes s USING (record_id) LEFT JOIN body USING (record_id)
        LEFT JOIN st USING (record_id) WHERE r.academic ORDER BY r.record_id""").fetchall()
    # rows in salted-hash order, and the row number is the public id: no hex strings to look like secrets,
    # and the order says nothing about cite keys or titles
    recs.sort(key=lambda r: pid(r[0]))
    idx = {r[0]: i for i, r in enumerate(recs)}

    # topics and keywords (OpenAlex), dictionary-encoded
    vocab, vix = [], {}

    def v(t):
        if t not in vix:
            vix[t] = len(vocab)
            vocab.append(t)
        return vix[t]
    tk = defaultdict(list)
    for rid, t in con.execute("""SELECT r.record_id, t.topic FROM records r JOIN oa_topics t ON t.doi = r.doi
            WHERE t.rank = 0 QUALIFY row_number() OVER (PARTITION BY r.record_id ORDER BY t.score DESC, t.topic) = 1
            ORDER BY r.record_id""").fetchall():
        tk[rid].append(v(t))
    # the primary topic's OpenAlex subfield and field, for the app's topic table
    sf = {rid: [v(sub), v(fld)] for rid, sub, fld in con.execute("""SELECT r.record_id, t.subfield, t.field
            FROM records r JOIN oa_topics t ON t.doi = r.doi WHERE t.rank = 0
            QUALIFY row_number() OVER (PARTITION BY r.record_id ORDER BY t.score DESC, t.topic) = 1
            ORDER BY r.record_id""").fetchall()}
    for rid, k in con.execute("""SELECT r.record_id, k.keyword FROM records r JOIN oa_keywords k ON k.doi = r.doi
            QUALIFY row_number() OVER (PARTITION BY r.record_id ORDER BY k.score DESC, k.keyword) <= 3
            ORDER BY r.record_id, k.score DESC, k.keyword""").fetchall():
        tk[rid].append(v(k))

    # places of study: layer 1 and verified body places, by GeoNames id
    l1 = con.execute("""SELECT DISTINCT r.record_id, m.geonameid FROM roles r JOIN mentions_l1 m
        ON m.record_id = r.record_id AND m.surface = r.surface AND m.field IN ('title','abstract','keywords','jurisdiction')
        WHERE r.role IN ('study_site','data_extent') AND m.geonameid IS NOT NULL ORDER BY 1, 2""").fetchall()
    bd = con.execute("""SELECT DISTINCT record_id, geonameid FROM b.probe_places
        WHERE quote_ok AND name_in_quote AND geonameid IS NOT NULL ORDER BY 1, 2""").fetchall()
    src = defaultdict(dict)
    for rid, g in l1:
        src[rid][g] = "abstract"
    for rid, g in bd:
        src[rid][g] = "both" if g in src[rid] else "body"
    gids = sorted({g for d in src.values() for g in d})
    con.execute("CREATE TEMP TABLE want (geonameid BIGINT)")
    con.executemany("INSERT INTO want VALUES (?)", [[g] for g in gids])
    # one name per place, chosen the same way every run: the commonest name among its rows (alias rows can
    # carry another), then the shorter, then alphabetical; the other fields are the same on every row
    gaz = {r[0]: r[1:] for r in con.execute("""WITH n AS (SELECT geonameid, name, count(*) c FROM gazetteer JOIN want USING (geonameid) GROUP BY 1, 2
                QUALIFY row_number() OVER (PARTITION BY geonameid ORDER BY c DESC, length(name), name) = 1)
            SELECT g.geonameid, any_value(n.name), min(g.fcode), min(g.country), min(g.admin1), min(g.lon), min(g.lat)
            FROM gazetteer g JOIN want USING (geonameid) JOIN n USING (geonameid) GROUP BY 1 ORDER BY 1""").fetchall()}
    a1 = admin1_table()
    a1_by_code = {r["gn_a1_code"]: k for k, r in a1.items() if r.get("gn_a1_code")}

    places, pidx = [], {}

    def add(key, row):
        if key not in pidx:
            pidx[key] = len(places)
            places.append(row)
        return pidx[key]

    # areas first (country and admin-1 areas are also the merge targets for coarsening)
    country_name = dict(con.execute("SELECT iso, name FROM countries").fetchall())
    pts, ptkeys = [], []
    for g in gids:
        if g not in gaz:
            continue
        name, fc, cc, adm1, lon, lat = gaz[g]
        if fc in AREA_CODES:
            if fc.startswith("PCL") or fc == "TERR":
                code = cc or ""
            elif fc == "ADM1" and str(g) in a1:
                code = "a1:" + str(g)
            else:
                code = cc or ""
            if (fc.startswith("PCL") or fc == "TERR") and code in country_name:
                name = country_name[code]      # the short country name (GeoNames countryInfo), not "Kingdom of ..."
            add(("g", g), [name, "area", lon, lat, code, None, int(fc in BIG), fc])
        else:
            kind = "settlement" if fc.startswith("PPL") else "feature"
            pts.append((lon, lat))
            ptkeys.append((g, name, kind, lon, lat, cc, fc))
    for (g, name, kind, lon, lat, cc, fc), val in zip(ptkeys, sample_smod(pts)):
        ur = None if kind == "feature" else ("urban" if (val or 0) >= 21 else "rural" if (val or 0) >= 11 else None)
        add(("g", g), [name, kind, lon, lat, cc or "", ur, 0, fc])
    insts = con.execute("""SELECT o.inst_id, min(o.inst), min(o.country), min(o.lon), min(o.lat),
            min(p.ur) FROM origins o LEFT JOIN places p ON p.place_id = 'i' || o.inst_id GROUP BY 1 ORDER BY 1""").fetchall()
    for iid, name, cc, lon, lat, ur in insts:
        if lon is not None:
            add(("i", iid), [name, "institution", lon, lat, cc or "", ur, 0, "INST"])

    # studies, with optional coarsening of places named by one paper only
    per_place = Counter(g for d in src.values() for g in d)
    country_area = {}

    def merge_target(g):
        name, fc, cc, adm1, lon, lat = gaz[g]
        prov = a1_by_code.get(f"{cc}.{adm1}") if cc and adm1 else None
        if prov:                      # the province it lies in, when Natural Earth knows it
            r = a1[prov]
            return add(("g", int(prov)), [r["name"], "area", float(r["longitude"]), float(r["latitude"]),
                                          "a1:" + prov, None, 0, "ADM1"])
        if cc:
            if cc not in country_area:
                c = con.execute("""SELECT geonameid, name, lon, lat FROM gazetteer WHERE country = ? AND fcode LIKE 'PCL%'
                                   ORDER BY importance DESC LIMIT 1""", [cc]).fetchone()
                country_area[cc] = add(("c", cc), [country_name.get(cc, c[1] if c else cc), "area",
                                                   c[2] if c else 0, c[3] if c else 0, cc, None, 0, "PCLI"])
            return country_area[cc]
        return None
    studies, merged = [], 0
    for rid, d in src.items():
        if rid not in idx:
            continue
        ids = []
        for g, s in d.items():
            if ("g", g) not in pidx:
                continue
            p = pidx[("g", g)]
            if not a.exact and per_place[g] == 1 and places[p][7] not in WHOLE:
                t = merge_target(g)
                if t is not None:
                    p, merged = t, merged + 1
            ids.append((p, s))
        # two places merged into one area keep a combined source, whatever order they came in
        srcs = defaultdict(set)
        for p, s in ids:
            srcs[p] |= {"abstract", "body"} if s == "both" else {s}
        out = [(p, "both" if len(v) > 1 else next(iter(v))) for p, v in sorted(srcs.items())]
        for k, (p, s) in enumerate(out):
            w = round(1 / len(out), 6) if k < len(out) - 1 else round(1 - round(1 / len(out), 6) * (len(out) - 1), 6)
            studies.append([idx[rid], p, w, s])

    origins = []
    by_rec = defaultdict(list)
    for rid, iid, w, corr in con.execute("""SELECT record_id, inst_id, sum(w_all), bool_or(coalesce(corr_view, false))
                                            FROM origins GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
        if rid in idx and ("i", iid) in pidx:
            by_rec[rid].append([pidx[("i", iid)], w, bool(corr)])
    for rid, os_ in by_rec.items():
        tot = sum(w for _, w, _ in os_)
        for k, (p, w, corr) in enumerate(os_):
            origins.append([idx[rid], p, round(w / tot, 6), int(corr)])
        # make the shares sum to exactly 1 (the weight rule)
        drift = round(1 - sum(o[2] for o in origins[-len(os_):]), 6)
        origins[-1][2] = round(origins[-1][2] + drift, 6)

    # keep only places that a study or an origin refers to: a single-paper place merged into its area must
    # not be published by name and coordinates (D136; preflight Bp2)
    used = sorted({r[1] for r in studies} | {r[1] for r in origins})
    remap = {old: new for new, old in enumerate(used)}
    places = [places[i] for i in used]
    for r in studies:
        r[1] = remap[r[1]]
    for r in origins:
        r[1] = remap[r[1]]

    papers, private = [], {}
    for rid, year, title, l1scope, read, bscope, setting, qok, labels in recs:
        scope = bscope or l1scope or "non-spatial"
        if not read or setting not in SETTINGS or (setting not in ("not_applicable", "unclear") and not qok):
            setting = "unclear" if scope != "non-spatial" else "not_applicable"
        y = year if (a.exact or year is None) else (year // 5) * 5
        papers.append([idx[rid], y, scope, setting, tk.get(rid, []), json.loads(labels) if labels else [],
                       "body" if read else "abstract", *sf.get(rid, [None, None])])
        if a.private:
            private[idx[rid]] = [rid.split("-")[0], title]

    # public build: topic labels only where 3 or more papers share them, and no per-paper keywords
    # (keywords and rare topics can find a paper in OpenAlex; preflight Ap2, Aa1, Aa2)
    if not a.exact:
        # counted per level: a name used as a topic and as a subfield must reach 3 papers at each level
        nt = Counter(r[4][0] for r in papers if r[4])
        ns = Counter(r[7] for r in papers if r[7] is not None)
        nf = Counter(r[8] for r in papers if r[8] is not None)
        for r in papers:
            r[4] = [r[4][0]] if r[4] and nt[r[4][0]] >= 3 else []
            r[7] = r[7] if r[7] is not None and ns[r[7]] >= 3 else None
            r[8] = r[8] if r[8] is not None and nf[r[8]] >= 3 else None
    used_v = sorted({t for r in papers for t in r[4]} | {t for r in papers for t in (r[7], r[8]) if t is not None})
    vmap = {old: new for new, old in enumerate(used_v)}
    vocab = [vocab[i] for i in used_v]
    for r in papers:
        r[4] = [vmap[t] for t in r[4]]
        r[7] = vmap.get(r[7]) if r[7] is not None else None
        r[8] = vmap.get(r[8]) if r[8] is not None else None

    # areas: settlement composition (land and people) and the North-South lenses
    comp = {}
    with open(OUT_DIR / "derived-261108" / "area_settlement.csv") as f:
        for r in csv.DictReader(f):
            key = r["code"] if r["zone"] == "admin0" else "a1:" + r["code"]
            land = [int(r[k]) for k in ("urban", "town", "rural")]
            pop = [round(float(r.get(k) or 0)) for k in ("pop_urban", "pop_town", "pop_rural")]
            comp[key] = [round(x / max(1, sum(land)), 3) for x in land] + \
                        ([round(x / max(1, sum(pop)), 3) for x in pop] if sum(pop) else [None] * 3)
    lens = {iso: [int(m or 0), int(w or 0), int(b or 0)] for iso, m, w, b in con.execute(
        "SELECT iso, ns_m49, ns_wb, ns_brandt FROM countries").fetchall()}
    codes = sorted({p[4] for p in places if p[4]})
    areas = []
    for c in codes:
        nm = a1[c[3:]]["name"] if c.startswith("a1:") and c[3:] in a1 else country_name.get(c, c)
        lab = [float(a1[c[3:]]["longitude"]), float(a1[c[3:]]["latitude"])] if c.startswith("a1:") and c[3:] in a1 else None
        iso = a1.get(c[3:], {}).get("iso_a2", "") if c.startswith("a1:") else c
        areas.append([c, iso, nm, lab, lens.get(iso, [0, 0, 0]), comp.get(c)])
    isos = sorted({p[4] if not p[4].startswith("a1:") else a1.get(p[4][3:], {}).get("iso_a2") for p in places if p[4]} - {None, ""})
    files = admin1_outlines(set(isos))

    data = {"contract": "corpus-geography/0.1",
            "note": "One personal research library (Day 9, 30 Day Map Challenge 2026). " + (
                "Years in five-year bins; study places named by one paper merged into their province or country." if not a.exact else "Exact years and places."),
            "papers": {"cols": ["id", "year", "scope", "setting", "topics", "labels", "read", "subfield", "field"], "rows": papers},
            "places": {"cols": ["name", "kind", "lon", "lat", "code", "ur", "big", "fcode"],
                       "rows": [[n, k, round(lo, 3), round(la, 3), c, u, b, f] for n, k, lo, la, c, u, b, f in places]},
            "origins": {"cols": ["paper", "place", "w", "corr"], "rows": origins},
            "studies": {"cols": ["paper", "place", "w", "source"], "rows": studies},
            "areas": {"cols": ["code", "iso", "name", "label", "north", "composition"], "rows": areas,
                      "composition": "land urban, town, rural shares; then population urban, town, rural shares (GHS-SMOD and GHS-POP 2020)",
                      "north": "M49 former developed, World Bank high income, Brandt line"},
            "admin1": files, "vocab": vocab}
    APP.mkdir(exist_ok=True)
    (APP / "day09.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    kind = {i: p[1] for i, p in enumerate(places)}
    exp = {"papers": len(papers), "scopes": dict(Counter(p[2] for p in papers)),
           "settings": dict(Counter(p[3] for p in papers)),
           "located": len({o[0] for o in origins}), "placed": len({s[0] for s in studies}),
           "study_weight_by_kind": {k: round(sum(s[2] for s in studies if kind[s[1]] == k), 6)
                                    for k in ("area", "feature", "settlement")},
           "merged_single_paper_places": merged}
    (APP / "day09_expected.json").write_text(json.dumps(exp, indent=1))
    if a.private:
        (APP / "day09_private.json").write_text(json.dumps(private, ensure_ascii=False))
    print(json.dumps(exp, indent=1))
    print(f"{(APP / 'day09.json').stat().st_size // 1024} kB, {len(places)} places, {len(studies)} study links, "
          f"{len(origins)} origin links, {len(files)} admin-1 files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
