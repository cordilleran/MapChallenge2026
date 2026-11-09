"""Day 9: OpenAlex topics and keywords for the topic labels (D112).

For every academic DOI, fetch the work's `topics` (up to three, each with its
subfield, field and domain, and a score) and `keywords` (OpenAlex's scored
keyword list). These feed the hover labels: "topic + top keywords", about
the reader's interests, not paper titles.

Same polite-pool rules as 02_openalex.py (whose `get` and `batches` this
reuses): 50 DOIs a call, a pause, MC26_CONTACT as mailto. Raw responses go to
a dated `openalex-topics-raw-YYMMDD` folder that is never overwritten.

Usage: python 02b_openalex_topics.py
"""
import importlib.util
import json
import sys
import time
from datetime import date
from pathlib import Path

import duckdb

_spec = importlib.util.spec_from_file_location("oa", Path(__file__).with_name("02_openalex.py"))
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)


def main():
    raw = oa.OUT_DIR / f"openalex-topics-raw-{date.today():%y%m%d}"
    if raw.exists():
        sys.exit(f"{raw} exists; raw pulls are never overwritten.")
    raw.mkdir(parents=True)
    con = duckdb.connect(str(oa.OUT_DIR / "day09.duckdb"))
    dois = [r[0] for r in con.execute(
        "SELECT DISTINCT doi FROM records WHERE academic AND doi IS NOT NULL ORDER BY doi").fetchall()]
    works = []
    for i, b in enumerate(oa.batches(dois, oa.BATCH)):
        ok = [d for d in b if "," not in d and "|" not in d]
        js = oa.get("works", {"filter": "doi:" + "|".join(ok), "per-page": "100",
                              "select": "id,doi,topics,keywords"})
        (raw / f"topics_{i:03d}.json").write_text(json.dumps(js))
        works += js.get("results", [])
        time.sleep(oa.PAUSE)
    topics, kws = [], []
    for w in works:
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        for rank, t in enumerate(w.get("topics") or []):
            topics.append((doi, rank, t.get("display_name"), (t.get("subfield") or {}).get("display_name"),
                           (t.get("field") or {}).get("display_name"),
                           (t.get("domain") or {}).get("display_name"), t.get("score")))
        for k in w.get("keywords") or []:
            kws.append((doi, k.get("display_name"), k.get("score")))
    con.execute("""CREATE OR REPLACE TABLE oa_topics (doi VARCHAR, rank INTEGER, topic VARCHAR,
                   subfield VARCHAR, field VARCHAR, domain VARCHAR, score DOUBLE)""")
    con.execute("CREATE OR REPLACE TABLE oa_keywords (doi VARCHAR, keyword VARCHAR, score DOUBLE)")
    if topics:
        con.executemany("INSERT INTO oa_topics VALUES (?,?,?,?,?,?,?)", topics)
    if kws:
        con.executemany("INSERT INTO oa_keywords VALUES (?,?,?)", kws)
    print(f"{len(dois)} DOIs, {len(works)} works, {len(topics)} topic rows, {len(kws)} keyword rows")
    print(con.execute("""SELECT field, count(DISTINCT doi) n FROM oa_topics WHERE rank = 0
                         GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
