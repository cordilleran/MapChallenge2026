"""Day 9 slice S2: authorships and institution coordinates from OpenAlex.

For every academic record with a DOI, fetch the OpenAlex work (all
authorships, with each author's institutions and the corresponding-author
flag), then fetch each institution once for its coordinates and ROR id.

Polite pool: batched filters (50 DOIs or ids per call), a pause between
calls, and the contact address from MC26_CONTACT (OpenAlex's polite pool).
Only DOIs and OpenAlex ids are sent. Raw responses are kept, one file per
batch, in a dated folder that is never overwritten.

Usage:
    python 02_openalex.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
CONTACT = os.environ.get("MC26_CONTACT", "")
API = "https://api.openalex.org"
BATCH = 50
PAUSE = 0.5  # seconds between calls; OpenAlex allows far more


def get(path, params):
    if CONTACT:
        params["mailto"] = CONTACT
    url = f"{API}/{path}?" + urllib.parse.urlencode(params, safe=":|,/")
    req = urllib.request.Request(url, headers={"User-Agent": "mapchallenge2026-day09/0.1"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # network or HTTP error: back off and retry
            wait = 5 * (attempt + 1)
            print(f"  retry {attempt + 1} after {e!r}; waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def batches(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def main():
    raw = OUT_DIR / f"openalex-raw-{date.today():%y%m%d}"
    if raw.exists():
        sys.exit(f"{raw} exists; raw pulls are never overwritten. Move it or wait a day.")
    raw.mkdir(parents=True)
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    dois = [r[0] for r in con.execute(
        "SELECT DISTINCT doi FROM records WHERE academic AND doi IS NOT NULL ORDER BY doi").fetchall()]
    print(f"{len(dois)} DOIs")

    works, skipped = [], 0
    for i, b in enumerate(batches(dois, BATCH)):
        # Commas and pipes inside a DOI would break the filter; such DOIs are skipped and counted.
        ok = [d for d in b if "," not in d and "|" not in d]
        skipped += len(b) - len(ok)
        if not ok:
            continue
        js = get("works", {"filter": "doi:" + "|".join(ok), "per-page": "100",
                           "select": "id,doi,publication_year,language,authorships,corresponding_institution_ids,primary_topic"})
        (raw / f"works_{i:03d}.json").write_text(json.dumps(js))
        works += js.get("results", [])
        time.sleep(PAUSE)
    print(f"{len(works)} works returned; {skipped} DOIs skipped (comma or pipe)")

    inst_ids = sorted({i["id"].rsplit("/", 1)[-1]
                       for w in works for a in w.get("authorships", [])
                       for i in a.get("institutions", []) if i.get("id")})
    print(f"{len(inst_ids)} institutions")
    insts = []
    for i, b in enumerate(batches(inst_ids, BATCH)):
        js = get("institutions", {"filter": "openalex:" + "|".join(b), "per-page": "100",
                                  "select": "id,ror,display_name,type,country_code,geo"})
        (raw / f"institutions_{i:03d}.json").write_text(json.dumps(js))
        insts += js.get("results", [])
        time.sleep(PAUSE)

    # Tables. One row per (work, author position, institution); an author with no
    # institution keeps a row with a null institution so coverage can be counted.
    aff = []
    for w in works:
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        for pos, a in enumerate(w.get("authorships", [])):
            ins = a.get("institutions") or [{}]
            for i in ins:
                aff.append((doi, pos, len(w["authorships"]), bool(a.get("is_corresponding")),
                            a.get("author_position"), (a.get("author") or {}).get("display_name"),
                            (i.get("id") or "").rsplit("/", 1)[-1] or None,
                            "; ".join(a.get("raw_affiliation_strings") or [])))
    con.execute("""CREATE OR REPLACE TABLE oa_authorships (doi VARCHAR, author_idx INTEGER,
        n_authors INTEGER, is_corresponding BOOLEAN, author_position VARCHAR, author VARCHAR,
        inst_id VARCHAR, raw_affiliation VARCHAR)""")
    if aff:
        con.executemany("INSERT INTO oa_authorships VALUES (?,?,?,?,?,?,?,?)", aff)
    rows = []
    for i in insts:
        g = i.get("geo") or {}
        rows.append((i["id"].rsplit("/", 1)[-1], i.get("ror"), i.get("display_name"), i.get("type"),
                     i.get("country_code"), g.get("city"), g.get("region"),
                     g.get("latitude"), g.get("longitude")))
    con.execute("""CREATE OR REPLACE TABLE oa_institutions (inst_id VARCHAR PRIMARY KEY, ror VARCHAR,
        name VARCHAR, type VARCHAR, country VARCHAR, city VARCHAR, region VARCHAR,
        lat DOUBLE, lon DOUBLE)""")
    if rows:
        con.executemany("INSERT INTO oa_institutions VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.execute("""CREATE OR REPLACE TABLE oa_works AS SELECT * FROM (VALUES (NULL::VARCHAR, NULL::INTEGER, NULL::VARCHAR, NULL::VARCHAR)) t(doi, year, language, topic) WHERE false""")
    con.executemany("INSERT INTO oa_works VALUES (?,?,?,?)", [
        ((w.get("doi") or "").replace("https://doi.org/", "").lower(), w.get("publication_year"),
         w.get("language"), ((w.get("primary_topic") or {}).get("field") or {}).get("display_name"))
        for w in works])
    print(con.execute("""
        SELECT count(DISTINCT r.record_id) academic_with_doi,
               count(DISTINCT w.doi) matched_in_openalex,
               count(DISTINCT CASE WHEN i.lat IS NOT NULL THEN a.doi END) with_any_located_institution,
               count(DISTINCT CASE WHEN a.is_corresponding AND i.lat IS NOT NULL THEN a.doi END) with_located_corresponding
        FROM records r LEFT JOIN oa_works w ON w.doi = r.doi
        LEFT JOIN oa_authorships a ON a.doi = w.doi
        LEFT JOIN oa_institutions i ON i.inst_id = a.inst_id
        WHERE r.academic AND r.doi IS NOT NULL""").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
