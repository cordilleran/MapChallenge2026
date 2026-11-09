"""Day 9 slice S3b: place candidates from titles, abstracts and keywords.

For each academic record, find capitalized word runs ("Gulf of St. Lawrence",
"British Columbia"), look every sub-run up in the gazetteer, and keep the
matches with their character offsets in the field they came from. The
record's ingest `Places:` line is matched too, tagged `ingest`, so its
accuracy can be scored on its own.

Homonyms are ranked, not removed: the best guess uses feature importance,
the countries of the paper's OpenAlex institutions and its jurisdiction
field, and other places named in the same paper (a "Victoria" beside
"British Columbia"). The top three stay in the table for the role call
(D101: the agent chooses among these, it never adds a place).

Usage:
    python 04_candidates.py [--fields title,abstract,keywords,ingest]
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))

from geoparse import CONTEXT_ONLY, EXEMPT, NEVER_SINGLE, common_words, keep_surface, subruns


# "Indus, Ganges and Brahmaputra river basins": a lone river or lake name passes the
# context gate when a water word follows within 40 characters (D120).
WATER_CUE = re.compile(r"^[^.;]{0,40}?\b(rivers?|basins?|creek|lakes?|watersheds?|catchments?|delta|glacier)\b", re.I)
PRIOR_SCALE = float(os.environ.get("MC26_PRIOR_SCALE", "1.0"))  # D120: 1.5 put the Rhine and the Middle East in the US


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fields", default="title,abstract,keywords,ingest")
    args = ap.parse_args()
    fields = args.fields.split(",")
    t0 = time.time()
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    words = common_words()

    recs = con.execute("""SELECT record_id, title, abstract, keywords, ingest_places, jurisdiction, doi
                          FROM records WHERE academic""").fetchall()
    ctx = {}  # record_id -> set of context country codes
    for rid, cc in con.execute("""SELECT DISTINCT r.record_id, i.country FROM records r
            JOIN oa_authorships a ON a.doi = r.doi JOIN oa_institutions i ON i.inst_id = a.inst_id
            WHERE r.academic AND i.country IS NOT NULL""").fetchall():
        ctx.setdefault(rid, set()).add(cc)

    cand = []
    field_text = {}
    for rid, title, abstract, keywords, ingest, jur, _ in recs:
        texts = {"title": title or "", "abstract": abstract or "", "keywords": keywords or ""}
        for f, t in texts.items():
            field_text[(rid, f)] = t
        for f in ("title", "abstract", "keywords"):
            if f in fields:
                for surface, s, e in subruns(texts[f]):
                    cand.append((rid, f, "gazetteer", surface, s, e))
        if "ingest" in fields and ingest:
            pos = 0
            for part in ingest.split(","):
                p = part.strip()
                if p:
                    s = ingest.find(p, pos)
                    cand.append((rid, "ingest", "ingest", p, s, s + len(p)))
                    pos = s + len(p)
        # The jurisdiction field gives context countries even when OpenAlex has none.
        for m in re.finditer(r"[^|,;]+", jur or ""):
            tok = m.group().strip()
            if tok:
                s0 = m.start() + m.group().index(tok)
                cand.append((rid, "jurisdiction", "ingest", tok, s0, s0 + len(tok)))

    con.execute("""CREATE OR REPLACE TEMP TABLE cand (record_id VARCHAR, field VARCHAR,
                   method VARCHAR, surface VARCHAR, cstart INTEGER, cend INTEGER)""")
    con.executemany("INSERT INTO cand VALUES (?,?,?,?,?,?)", cand)

    # Join every candidate to every gazetteer entry with the same key.
    hits = con.execute("""
        SELECT c.*, g.geonameid, g.name, g.fcode, g.country, g.admin1, g.lat, g.lon, g.importance
        FROM cand c JOIN gazetteer g ON g.key = rtrim(lower(c.surface), '.,;:’' || chr(39))""").fetchall()

    # Context per record: countries from OpenAlex, plus countries and admin1
    # areas that appear unambiguously (as a country or admin1 match) in its text.
    # Only unambiguous names count: a surface whose country-level or admin1
    # matches all sit in one country (otherwise "Victoria" would vote for Malta).
    admin_ctx, groups = {}, {}
    for h in hits:
        if h[8] in EXEMPT and h[9] is not None:  # continents and oceans have no country (finding 5)
            groups.setdefault((h[0], h[3].lower()), set()).add((h[9], h[10] if h[8] == "ADM1" else None))
    for (rid, _), opts in groups.items():
        countries = {cc for cc, _ in opts}
        if len(countries) == 1:
            ctx.setdefault(rid, set()).add(next(iter(countries)))
            a1s = {a1 for _, a1 in opts if a1 is not None}
            if len(a1s) == 1:  # deterministic: one admin1 or none (finding 6)
                admin_ctx.setdefault(rid, set()).add((next(iter(countries)), next(iter(a1s))))

    # Corpus prior: a homonym in a country the library's authors often work from
    # is more likely (PRIOR_SCALE x log10 of 1 + institution count; at 1.0, Canada ~ +3.1, Malta 0).
    import math
    prior = {cc: PRIOR_SCALE * math.log10(1 + n) for cc, n in con.execute(
        """SELECT i.country, count(*) FROM oa_authorships a JOIN oa_institutions i USING (inst_id)
           WHERE i.country IS NOT NULL GROUP BY 1""").fetchall()}

    best = {}
    for h in hits:
        rid, field, method, surface, s, e, gid, name, fcode, cc, a1, lat, lon, imp = h
        if not keep_surface(surface, fcode, words):
            continue  # a common word, direction or demonym that also names a place
        single = method == "gazetteer" and " " not in surface.strip() and imp < 25  # curated aliases pass (D120)
        if single and fcode in NEVER_SINGLE:
            continue
        water_cue = fcode in ("STM", "LK", "RSV", "GLCR") and WATER_CUE.match(
            field_text.get((rid, field), "")[e:e + 40])
        if single and fcode in CONTEXT_ONLY and cc not in ctx.get(rid, ()) and not water_cue:
            continue  # a lone "Carlo" or "James" needs its country in context (D117)
        score = imp + prior.get(cc, 0.0)
        if cc in ctx.get(rid, ()):
            score += 6
        if (cc, a1) in admin_ctx.get(rid, ()):
            score += 4
        k = (rid, field, s, e, surface)
        cur = best.setdefault(k, {})
        if gid not in cur or cur[gid][0] < score:  # one entry per place (finding 4)
            cur[gid] = (score, gid, name, fcode, cc, a1, lat, lon)

    # Keep the longest match where runs overlap: "British Columbia" beats "Columbia".
    rows = []
    by_field = {}
    for k, v in best.items():
        by_field.setdefault(k[:2], []).append((k, list(v.values())))
    for _, items in by_field.items():
        items.sort(key=lambda kv: (-(kv[0][3] - kv[0][2]), kv[0][2]))  # longest first (finding 3)
        taken = []
        for (rid, field, s, e, surface), v in items:
            if s >= 0 and any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            v.sort(reverse=True)
            top = v[0]
            alts = ";".join(str(x[1]) for x in v[1:3])
            meth = "ingest" if field in ("ingest", "jurisdiction") else "gazetteer"
            rows.append((rid, field, meth, surface, s, e, len(v), top[1], top[2], top[3],
                         top[4], top[5], top[6], top[7], round(top[0], 2), alts))

    con.execute("""CREATE OR REPLACE TABLE mentions_l1 (record_id VARCHAR, field VARCHAR,
        method VARCHAR, surface VARCHAR, cstart INTEGER, cend INTEGER, n_homonyms INTEGER,
        geonameid BIGINT, name VARCHAR, fcode VARCHAR, country VARCHAR, admin1 VARCHAR,
        lat DOUBLE, lon DOUBLE, score DOUBLE, alt_geonameids VARCHAR)""")
    con.executemany("INSERT INTO mentions_l1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    print(f"{len(cand)} candidate runs, {len(hits)} gazetteer hits, {len(rows)} mentions kept "
          f"in {time.time() - t0:.1f}s")
    print(con.execute("""SELECT field, count(*) mentions, count(DISTINCT record_id) records
                         FROM mentions_l1 GROUP BY field ORDER BY mentions DESC""").df().to_string(index=False))
    print(con.execute("""SELECT count(DISTINCT r.record_id) academic,
        count(DISTINCT CASE WHEN m.field IN ('title','abstract','keywords') THEN r.record_id END) with_text_place
        FROM records r LEFT JOIN mentions_l1 m USING (record_id) WHERE r.academic""").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
