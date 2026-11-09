"""Day 9 slice S6: export the page data, `site/data/day09.js`.

Archived: this fed the first canvas page, which was held and never published (D122).
The published page is the app in `day-09/app/`, fed by `14_app_export.py`.

One compact file, no server (spec section 4):
- `countries`: Natural Earth 1:50m admin-0 outlines, simplified (0.2 degrees),
  rings under 0.3 square degrees dropped, as [iso, [[lon, lat], ...]] rounded
  to 0.05 degrees;
- `lens`: per ISO code, North under each lens (M49, World Bank, Brandt);
- `places`: [lon, lat, name, class, iso, kind] with kind 1 institution,
  2 continent or ocean (counted, not drawn: its point is a pole or a centroid), 0 other;
- `arcs`: aggregated by (origin, destination, scope): [o, d, scope, w_all, w_corr, n];
- `marks`: origin-only papers (global, local-implicit, non-spatial and placeless
  regional or site papers) by (origin, scope): [o, scope, w_all, w_corr, n];
- `topics`: per place index, [papers, topic ids, keyword ids] into `vocab`, the
  top OpenAlex topics and keywords of the papers that touch it (D112: about the reader's interests, not paper titles);
- `stats`: counts, the reader's priors against the results (D111), gold-set scores;
- `pairs`: the top 30 place pairs, for the table view.

Usage: python 11_export.py
"""
import json
import os
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
RAW = OUT_DIR / "raw-261108" / "ne"
SITE = Path(__file__).resolve().parents[2] / "site" / "data" / "day09.js"
SCOPES = ["site", "multi-site", "regional", "global", "local-implicit", "non-spatial"]
CLASS = {"area": 0, "feature": 1, "urban": 2, "rural": 3, "water": 4, "unknown": 4}


def rings(zipname, simplify, keep_iso=False, min_area=0.3):
    """Rings smaller than min_area square degrees (most islets) are dropped."""
    d = RAW / ("x_" + zipname.replace(".zip", ""))
    if not list(d.glob("*.shp")):  # also redo an interrupted extraction
        with zipfile.ZipFile(RAW / zipname) as z:
            z.extractall(d)
    shp = next(d.glob("*.shp"))
    args = ["ogr2ogr", "-f", "GeoJSON", "/vsistdout/", str(shp), "-simplify", str(simplify)]
    if keep_iso:
        args += ["-select", "ISO_A2_EH"]
    gj = json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)
    out = []
    for f in gj["features"]:
        g = f["geometry"]
        if not g:
            continue
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            ring = [[round(x * 20) / 20, round(y * 20) / 20] for x, y in poly[0]]
            dedup = [ring[0]] + [p for i, p in enumerate(ring[1:], 1) if p != ring[i - 1]]
            area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(dedup, dedup[1:]))) / 2
            if len(dedup) >= 4 and area >= min_area:
                out.append([f["properties"].get("ISO_A2_EH", ""), dedup] if keep_iso else dedup)
    return out


def main():
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"), read_only=True)
    places = con.execute("""SELECT place_id, lon, lat, name, ur, country, fcode FROM places
                            ORDER BY place_id""").fetchall()
    idx = {p[0]: i for i, p in enumerate(places)}
    P = [[round(p[1], 3), round(p[2], 3), p[3], CLASS.get(p[4], 4), p[5] or "",
          1 if p[0].startswith("i") else 2 if p[6] in ("CONT", "OCN") else 0] for p in places]

    arcs = con.execute("""
        SELECT a.origin_id, a.dest_id, s.scope, sum(a.w_all), sum(coalesce(a.w_corr, 0)),
               count(DISTINCT a.record_id)
        FROM arcs a JOIN scopes s USING (record_id) GROUP BY ALL""").fetchall()
    A = [[idx[o], idx[d], SCOPES.index(s), round(wa, 4), round(wc, 4), n]
         for o, d, s, wa, wc, n in arcs if s in SCOPES]

    marks = con.execute("""
        SELECT 'i' || o.inst_id, s.scope, sum(o.w_all), sum(CASE WHEN o.corr_view THEN o.w_corr ELSE 0 END),
               count(DISTINCT o.record_id)
        FROM origins o JOIN scopes s USING (record_id)
        WHERE o.record_id NOT IN (SELECT record_id FROM arcs) GROUP BY ALL""").fetchall()
    M = [[idx[o], SCOPES.index(s), round(wa, 4), round(wc, 4), n] for o, s, wa, wc, n in marks if s in SCOPES]

    # Topic bundles per place: every paper that touches it as origin or destination.
    touch = con.execute("""
        SELECT 'i' || inst_id AS pid, record_id FROM origins
        UNION SELECT dest_id, record_id FROM arcs""").fetchall()
    rec_topic = dict(con.execute("SELECT record_id, topic FROM papers WHERE topic IS NOT NULL").fetchall())
    rec_kw = {r: (k or "").split("; ") for r, k in con.execute(
        "SELECT record_id, keywords FROM papers WHERE keywords IS NOT NULL").fetchall()}
    by_place = defaultdict(set)
    for pid, rid in touch:
        by_place[pid].add(rid)
    T, vocab, vix = {}, [], {}

    def v(term):  # dictionary-encode repeated topic and keyword strings
        if term not in vix:
            vix[term] = len(vocab)
            vocab.append(term)
        return vix[term]

    for pid, recs in by_place.items():
        if pid not in idx:
            continue
        tc = Counter(rec_topic[r] for r in recs if r in rec_topic)
        kc = Counter(k for r in recs for k in rec_kw.get(r, []) if k)
        T[idx[pid]] = [len(recs), [v(t) for t, _ in tc.most_common(3)], [v(k) for k, _ in kc.most_common(4)]]

    lens = {iso: [int(a), int(b), int(c)] for iso, a, b, c in con.execute(
        "SELECT iso, ns_m49, ns_wb, ns_brandt FROM countries").fetchall()}

    st = {}
    st["academic"], st["located"], st["placed"], st["nonspatial"] = con.execute("""
        SELECT count(*), sum(has_origin::INT), sum(has_study_place::INT),
               sum((scope = 'non-spatial')::INT) FROM papers""").fetchone()
    st["scopes"] = dict(con.execute("SELECT scope, count(*) FROM papers GROUP BY 1").fetchall())
    st["bc"], st["canada"], st["placed_records"] = con.execute("""
        WITH sp AS (SELECT DISTINCT r.record_id, m.country, m.admin1 FROM roles r JOIN mentions_l1 m
             ON m.record_id = r.record_id AND m.surface = r.surface
            AND m.field IN ('title','abstract','keywords','jurisdiction')
            WHERE r.role IN ('study_site','data_extent'))
        SELECT count(DISTINCT record_id) FILTER (WHERE country = 'CA' AND admin1 = '02'),
               count(DISTINCT record_id) FILTER (WHERE country = 'CA'), count(DISTINCT record_id) FROM sp""").fetchone()
    st["arc_classes"] = {f"{o}>{d}": round(w, 2) for o, d, w in con.execute("""
        SELECT o.ur, d.ur, sum(a.w_all) FROM arcs a JOIN places o ON o.place_id = a.origin_id
        JOIN places d ON d.place_id = a.dest_id GROUP BY ALL""").fetchall()}
    st["origins_urban"] = con.execute("""SELECT avg((ur = 'urban')::INT) FROM places
                                         WHERE place_id LIKE 'i%'""").fetchone()[0]
    gp = OUT_DIR / "gold_scores.json"  # written by 09_score_gold.py; optional (S5 review 3.2)
    gold = json.loads(gp.read_text()) if gp.exists() else {}
    gr, gi = gold.get("gazetteer_role_call", {}), gold.get("ingest_places", {})
    st["gold"] = {"n": gold.get("n_records"), "scope_exact": gold.get("scope_exact"),
                  "scope_with_alt": gold.get("scope_with_alt"), "precision": gr.get("precision"),
                  "recall": gr.get("recall"), "ingest_precision": gi.get("precision"),
                  "ingest_recall": gi.get("recall")}

    pairs = con.execute("""
        SELECT o.name, o.country, d.name, d.country, d.ur, count(DISTINCT a.record_id) n, round(sum(a.w_all), 2) w
        FROM arcs a JOIN places o ON o.place_id = a.origin_id JOIN places d ON d.place_id = a.dest_id
        GROUP BY ALL ORDER BY w DESC LIMIT 30""").fetchall()

    data = {"note": "Day 9 corpus geography. Generated by day-09/scripts/11_export.py; do not edit. "
                    "Places: GeoNames (CC BY 4.0) and OpenAlex (CC0); urban-rural: GHS-SMOD 2020 (JRC, CC BY 4.0); "
                    "outlines: Natural Earth (public domain).",
            "scopes": SCOPES,
            "countries": rings("ne_50m_admin_0_countries.zip", 0.2, keep_iso=True),
            "lens": lens, "vocab": vocab, "places": P, "arcs": A, "marks": M, "topics": T, "stats": st,
            "pairs": [list(p) for p in pairs]}
    js = "/* Day 9 data. Generated by day-09/scripts/11_export.py; do not edit. */\nwindow.D9 = " + \
         json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n"
    SITE.write_text(js)
    print(f"{SITE} {len(js) // 1024} kB: {len(P)} places, {len(A)} arcs, {len(M)} marks, "
          f"{len(data['countries'])} country rings")
    print(json.dumps(st, indent=1, default=float)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
