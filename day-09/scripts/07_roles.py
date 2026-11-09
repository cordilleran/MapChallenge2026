"""Day 9 slice S5: role and scope calls for layer 1 (D101, D107, D116).

For every academic record, Haiku sees the title, the abstract (first 2,500
characters), the keywords and each text candidate from `mentions_l1` (title,
abstract and keyword fields) with a short context window, and returns a role
per candidate and one scope class for the paper. It chooses only among the
listed candidates and the fixed labels (D101). Ingest `Places:` and
`jurisdiction:` candidates are not shown: they are scored as their own method.

Calls go through `claude -p --model haiku` with a short system prompt that
replaces the default one (650 cached tokens instead of about 28,000), no
tools and no session persistence. Results go to their own file,
`roles.duckdb`, one row per call, so a run never holds the main database;
records already answered are skipped, so the run resumes. `--merge` copies
the latest valid answer per record into `day09.duckdb` as `roles` and
`scopes`.

Usage:
    python 07_roles.py [--limit N] [--workers 4] [--records id,id] [--changed]
    python 07_roles.py --merge
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
CONTEXT = 120
MAX_CANDS = 40
ROLES = ["study_site", "data_extent", "comparison", "context", "author_affiliation", "not_a_place"]
SCOPES = ["site", "multi-site", "regional", "global", "local-implicit", "non-spatial"]

SYSTEM = """You classify place names in research papers. You answer with one JSON object and nothing else.

For each candidate id, choose one role:
- study_site: where the work was done, or the case or area studied.
- data_extent: the coverage of a dataset used.
- comparison: named for contrast, or as the location of cited studies.
- context: mentioned only, as background.
- author_affiliation: part of an institution name or address.
- not_a_place: the word is not a place here (a person, an organisation, a method, an ordinary word).

Then choose one scope for the paper:
- site: 1 to 3 study sites.
- multi-site: 4 or more study sites.
- regional: an area such as a basin, province, country or continent is the subject.
- global: the whole world is the subject.
- local-implicit: empirical work on a place, but no place is named beyond the authors' own.
- non-spatial: the object of study is an equation, method, model, algorithm, software, theory or language model. A review is spatial only if it names its region or the places of the studies it reviews.

Use only the candidate ids given. Every id gets a role.
Format: {"roles": {"c0": "<role>", ...}, "scope": "<scope>", "reason": "<one short sentence>"}"""

lock = threading.Lock()


def record_prompt(title, abstract, keywords, cands):
    lines = [f"c{i}: {surf}  [{name}, {cc or '-'}, {fc}]  ... {ctx}"
             for i, (surf, name, cc, fc, ctx) in enumerate(cands)]
    return (f"Title: {title}\nAbstract: {(abstract or '')[:2500]}\nKeywords: {keywords or ''}\n\n"
            f"Candidates (id: text [gazetteer match, country, feature code] ... context):\n"
            + ("\n".join(lines) if lines else "(none)"))


def candidates(con, rid, texts):
    # A record with no usable abstract (under 200 characters) also shows its
    # library jurisdiction field, so a BC book chapter is not left placeless (D119).
    fields = ["title", "abstract", "keywords"]
    if len(texts["abstract"]) < 200:
        fields.append("jurisdiction")
    rows = con.execute(f"""SELECT field, surface, cstart, cend, name, country, fcode FROM m.mentions_l1
                          WHERE record_id = ? AND field IN ({','.join('?' * len(fields))})
                          ORDER BY CASE field WHEN 'title' THEN 0 WHEN 'abstract' THEN 1
                                   WHEN 'keywords' THEN 2 ELSE 3 END, cstart""", [rid, *fields]).fetchall()
    seen, out = set(), []
    for field, surf, s, e, name, cc, fc in rows:
        if surf.lower() in seen:
            continue
        seen.add(surf.lower())
        t = texts[field]
        ctx = t[max(0, s - CONTEXT): e + CONTEXT].replace("\n", " ")
        if field == "jurisdiction":
            ctx = "(from the library record's jurisdiction field: " + t + ")"
        out.append((surf, name, cc, fc, ctx))
        if len(out) >= MAX_CANDS:
            break
    return out


def parse(text, n):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    js = json.loads(t)
    roles = js.get("roles") or {}
    ids = [f"c{i}" for i in range(n)]
    bad = [k for k in ids if roles.get(k) not in ROLES]
    if bad or js.get("scope") not in SCOPES:
        raise ValueError(f"invalid roles {bad[:3]} or scope {js.get('scope')!r}")
    return js


def call(prompt):
    t0 = time.time()
    p = subprocess.run(["claude", "-p", "--model", "haiku", "--output-format", "json",
                        "--system-prompt", SYSTEM, "--tools", "", "--no-session-persistence",
                        "--strict-mcp-config"],
                       input=prompt, capture_output=True, text=True, timeout=300,
                       cwd=OUT_DIR)
    js = json.loads(p.stdout)
    u = js.get("usage") or {}
    return (time.time() - t0, js.get("result", ""), js.get("total_cost_usd"),
            (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
            + (u.get("cache_creation_input_tokens") or 0), u.get("output_tokens"))


def work(job, run_id):
    rid, prompt, n, cand_json = job
    err, js, res = None, None, (None, "", None, None, None)
    for attempt in range(2):
        try:
            res = call(prompt)
            js = parse(res[1], n)
            err = None
            break
        except Exception as e:  # bad JSON, invalid label, CLI failure: retry once
            err = f"{type(e).__name__}: {e}"[:300]
    with lock:
        out = duckdb.connect(str(OUT_DIR / "roles.duckdb"))
        out.execute("INSERT INTO role_calls VALUES (?,?,?,?,?,?,?,?,?,?,now())",
                    [run_id, rid, n, cand_json, res[1], json.dumps(js) if js else None,
                     err, res[0], res[2], res[4]])
        out.close()
    return rid, err, res[0], res[2]


def merge():
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    con.execute(f"ATTACH '{OUT_DIR / 'roles.duckdb'}' AS r (READ_ONLY)")
    con.execute("""CREATE OR REPLACE TABLE scopes AS
        SELECT record_id, json_extract_string(answer, '$.scope') AS scope,
               json_extract_string(answer, '$.reason') AS reason, run_id
        FROM r.role_calls WHERE answer IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY ts DESC) = 1""")
    con.execute("""CREATE OR REPLACE TABLE roles AS
        WITH last AS (SELECT * FROM r.role_calls WHERE answer IS NOT NULL
                      QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY ts DESC) = 1),
        c AS (SELECT record_id, answer, unnest(from_json(cands, '["VARCHAR"]')) AS surface,
                     generate_subscripts(from_json(cands, '["VARCHAR"]'), 1) - 1 AS i FROM last)
        SELECT record_id, i AS cand_idx, surface,
               json_extract_string(answer, '$.roles.c' || i) AS role FROM c""")
    print(con.execute("SELECT scope, count(*) n FROM scopes GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
    print(con.execute("SELECT role, count(*) n FROM roles GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--records")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--changed", action="store_true",
                    help="re-ask only records whose candidate list differs from the last answer")
    args = ap.parse_args()
    if args.merge:
        return merge()
    os.nice(10)
    run_id = datetime.datetime.now().strftime("%y%m%d-%H%M%S")
    out = duckdb.connect(str(OUT_DIR / "roles.duckdb"))
    out.execute("""CREATE TABLE IF NOT EXISTS role_calls (run_id VARCHAR, record_id VARCHAR,
        n_cands INTEGER, cands VARCHAR, raw VARCHAR, answer VARCHAR, error VARCHAR, wall_s DOUBLE,
        cost_usd DOUBLE, out_tok INTEGER, ts TIMESTAMP)""")
    done = {r[0] for r in out.execute(
        "SELECT DISTINCT record_id FROM role_calls WHERE answer IS NOT NULL").fetchall()}
    last = dict(out.execute("""SELECT record_id, cands FROM role_calls WHERE answer IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY ts DESC) = 1""").fetchall())
    out.close()

    con = duckdb.connect()
    con.execute(f"ATTACH '{OUT_DIR / 'day09.duckdb'}' AS m (READ_ONLY)")
    recs = con.execute("""SELECT record_id, title, abstract, keywords, jurisdiction FROM m.records
                          WHERE academic ORDER BY hash(record_id)""").fetchall()
    if args.records:
        want = set(args.records.split(","))
        recs = [r for r in recs if r[0] in want]
    elif not args.changed:
        recs = [r for r in recs if r[0] not in done]
    jobs = []
    for rid, title, abstract, keywords, jur in recs:
        texts = {"title": title or "", "abstract": abstract or "", "keywords": keywords or "",
                 "jurisdiction": jur or ""}
        cands = candidates(con, rid, texts)
        cj = json.dumps([c[0] for c in cands])
        if args.changed and last.get(rid) == cj:
            continue  # candidate list unchanged since the last answer
        jobs.append((rid, record_prompt(title, abstract, keywords, cands), len(cands), cj))
    con.close()
    if args.limit:
        jobs = jobs[:args.limit]
    print(f"run {run_id}: {len(jobs)} records ({len(done)} already answered)", flush=True)

    t0, cost, errs = time.time(), 0.0, 0
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(work, j, run_id) for j in jobs]
        for k, f in enumerate(as_completed(futs), 1):
            rid, err, wall, c = f.result()
            cost += c or 0
            errs += bool(err)
            if err or k % 50 == 0 or k == len(jobs):
                print(f"{k}/{len(jobs)} {time.time() - t0:.0f}s ${cost:.3f} errors={errs}"
                      + (f"  {rid}: {err}" if err else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
