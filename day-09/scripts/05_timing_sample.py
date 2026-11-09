"""Day 9 slice S4: timing sample for the layer 2 (body) cost model (D106).

Draws a stratified sample of academic records (record type group by text
length quartile), and on each one times the three stages a body pass would
run:

1. gazetteer: candidate runs over the whole body and the gazetteer join;
2. gemma: the local role call (Ollama) on the study-area window;
3. haiku: the same role call through the Claude CLI.

The role call sends the title, the abstract and each candidate with a short
context window, and asks for a role per candidate and a scope class for the
paper. It chooses only among the candidates (D101). Outputs are kept: they
seed the gold set.

Timings go to their own file, `timing.duckdb` (table `timing_sample`, one
`run_id` per run). The main `day09.duckdb` is attached read-only only while
the sample and the gazetteer hits are prepared, then detached, so a long run
never holds the main database (D116).

Gemma calls run with thinking off, an output cap and a JSON schema that
allows only the listed candidate ids, the six roles and the six scopes
(D116: run 1 showed 4 of 11 calls running away to 6,000+ tokens).

Usage:
    python 05_timing_sample.py [--per-stratum 5] [--records id,id] [--skip-haiku] [--skip-gemma]
"""
import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import duckdb

from geoparse import common_words, keep_surface, subruns

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
LIBRARY = Path(os.environ.get("MC26_LIBRARY") or sys.exit("Set MC26_LIBRARY to the library's records folder (see README)."))
OLLAMA = os.environ.get("MC26_OLLAMA", "http://localhost:11434")
GEMMA = os.environ.get("MC26_GEMMA", "gemma4:26b-a4b-it-qat")
SEED = sum(map(ord, "day09-timing-sample"))
WINDOW = 8000      # characters of study-area text per record
CONTEXT = 120      # characters either side of a candidate
MAX_CANDS = 40
NUM_PREDICT = 1024  # output cap; normal calls in run 1 used 128 to 410 tokens

HEADING = re.compile(r"(?im)^\s*(?:\d+(?:\.\d+)*\.?\s*)?(study\s+(?:area|site|region|sites|areas)|"
                     r"site\s+description|materials?\s+and\s+methods|data\s+and\s+methods|methods?|data)\s*$")

ROLES = ["study_site", "data_extent", "comparison", "context", "author_affiliation", "not_a_place"]
SCOPES = ["site", "multi-site", "regional", "global", "local-implicit", "non-spatial"]

PROMPT = """You classify place names in a research paper. Use only the candidates listed.
Roles: study_site (where the work was done or the case studied), data_extent (the coverage of a dataset used),
comparison (named for contrast or from cited studies), context (mentioned only), author_affiliation
(part of an institution or address), not_a_place (the word is not a place here).
Scope of the paper, one of: site (1-3 study sites), multi-site (4 or more), regional (an area such as a basin,
province or country is the subject), global, local-implicit (empirical, no place named beyond the authors' own),
non-spatial (the object of study is an equation, method, model, algorithm, software or LLM; a review is spatial
only if the paper itself names its region or the places of the studies it reviews).

Title: {title}
Abstract: {abstract}

Candidates (id: name ... context):
{cands}

Answer with JSON only: {{"roles": {{"<id>": "<role>", ...}}, "scope": "<scope>", "reason": "<one sentence>"}}"""


def study_window(body):
    m = HEADING.search(body)
    if m:
        return body[m.start(): m.start() + WINDOW], "heading:" + m.group(1).lower()
    return body[:WINDOW], "none"


def gazetteer_pass(con, body, words):
    runs = list(subruns(body))
    if not runs:
        return [], 0
    con.execute("CREATE OR REPLACE TEMP TABLE t (surface VARCHAR, s INTEGER, e INTEGER)")
    con.executemany("INSERT INTO t VALUES (?,?,?)", runs)
    hits = con.execute("""SELECT t.surface, t.s, t.e, max(g.importance) imp, arg_max(g.fcode, g.importance) fc
                          FROM t JOIN m.gazetteer g ON g.key = rtrim(lower(t.surface), '.,;:’' || chr(39))
                          GROUP BY 1,2,3""").fetchall()
    kept = [h for h in hits if keep_surface(h[0], h[4], words)]
    return kept, len(runs)


def build_prompt(title, abstract, window, hits):
    seen, lines = set(), []
    for surface, s, e, *_ in sorted(hits, key=lambda h: h[1]):
        if surface.lower() in seen:
            continue
        seen.add(surface.lower())
        ctx = window[max(0, s - CONTEXT): e + CONTEXT].replace("\n", " ")
        lines.append(f"c{len(lines)}: {surface} ... {ctx}")
        if len(lines) >= MAX_CANDS:
            break
    return PROMPT.format(title=title, abstract=(abstract or "")[:2500],
                         cands="\n".join(lines) or "(none)"), len(lines)


def answer_schema(n_cands):
    """JSON schema for the role call: only the listed ids, roles and scopes."""
    ids = [f"c{i}" for i in range(n_cands)]
    return {"type": "object",
            "properties": {
                "roles": {"type": "object",
                          "properties": {i: {"type": "string", "enum": ROLES} for i in ids},
                          "required": ids, "additionalProperties": False},
                "scope": {"type": "string", "enum": SCOPES},
                "reason": {"type": "string", "maxLength": 300}},
            "required": ["roles", "scope", "reason"]}


def call_gemma(prompt, n_cands):
    body = json.dumps({"model": GEMMA, "prompt": prompt, "stream": False, "think": False,
                       "format": answer_schema(n_cands), "keep_alive": "2m",
                       "options": {"temperature": 0, "num_ctx": 8192,
                                   "num_predict": NUM_PREDICT}}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        js = json.load(r)
    return {"wall_s": time.time() - t0, "in_tok": js.get("prompt_eval_count"),
            "out_tok": js.get("eval_count"), "load_s": (js.get("load_duration") or 0) / 1e9,
            "text": js.get("response", "")}


def call_haiku(prompt, n_cands=None):
    t0 = time.time()
    p = subprocess.run(["claude", "-p", "--model", "haiku", "--output-format", "json"],
                       input=prompt, capture_output=True, text=True, timeout=600)
    wall = time.time() - t0
    try:
        js = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"wall_s": wall, "in_tok": None, "out_tok": None, "text": p.stdout[-500:],
                "error": p.stderr[-500:]}
    u = js.get("usage") or {}
    return {"wall_s": wall, "api_ms": js.get("duration_api_ms"),
            "in_tok": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                      + (u.get("cache_creation_input_tokens") or 0),
            "out_tok": u.get("output_tokens"), "cost_usd": js.get("total_cost_usd"),
            "text": js.get("result", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-stratum", type=int, default=5)
    ap.add_argument("--skip-haiku", action="store_true")
    ap.add_argument("--skip-gemma", action="store_true")
    ap.add_argument("--records", help="comma-separated record ids to time instead of the stratified draw")
    args = ap.parse_args()
    os.nice(10)
    run_id = datetime.datetime.now().strftime("%y%m%d-%H%M%S")
    # In-memory working connection; the main database is attached read-only and
    # detached before any model call.
    con = duckdb.connect()
    con.execute(f"ATTACH '{OUT_DIR / 'day09.duckdb'}' AS m (READ_ONLY)")
    words = common_words()
    recs = con.execute("""SELECT record_id, title, abstract, itype, text_chars,
            ntile(4) OVER (ORDER BY text_chars) AS q
            FROM m.records WHERE academic AND text_chars > 0""").fetchall()
    strata = {}
    for r in recs:
        grp = "article" if r[3] == "article" else "other"
        strata.setdefault((grp, r[5]), []).append(r)
    rng = random.Random(SEED)
    sample = []
    if args.records:
        want = args.records.split(",")
        byid = {r[0]: (("article" if r[3] == "article" else "other", r[5]), r) for r in recs}
        sample = [byid[w] for w in want if w in byid]
        missing = [w for w in want if w not in byid]
        if missing:
            print("not found:", ", ".join(missing), flush=True)
    else:
        for k in sorted(strata):
            pool = strata[k]
            sample += [(k, r) for r in rng.sample(pool, min(args.per_stratum, len(pool)))]
    print(f"run {run_id}: {len(sample)} records", flush=True)

    # Stage 1 for every record before any model call, then release the main database.
    prepared = []
    for (grp, q), (rid, title, abstract, itype, nchar, _) in sample:
        body = (LIBRARY / rid / f"{rid}.source.md").read_text(errors="replace")
        body = re.sub(r"^---\n.*?\n---\n", "", body, count=1, flags=re.S)
        t0 = time.time()
        hits_all, n_runs = gazetteer_pass(con, body, words)
        gaz_s = time.time() - t0
        window, kind = study_window(body)
        whits, _ = gazetteer_pass(con, window, words)
        prompt, n_c = build_prompt(title, abstract, window, whits)
        prepared.append(((rid, f"{grp}-q{q}", nchar, n_runs, len(hits_all), gaz_s, kind, n_c,
                          len(prompt)), prompt, n_c))
    con.close()

    out = duckdb.connect(str(OUT_DIR / "timing.duckdb"))
    out.execute("""CREATE TABLE IF NOT EXISTS timing_sample (run_id VARCHAR, record_id VARCHAR,
        stratum VARCHAR, text_chars BIGINT, n_runs INTEGER, n_hits INTEGER, gaz_s DOUBLE,
        window_kind VARCHAR, n_cands INTEGER, prompt_chars INTEGER, stage VARCHAR, wall_s DOUBLE,
        in_tok INTEGER, out_tok INTEGER, cost_usd DOUBLE, output VARCHAR, ts TIMESTAMP DEFAULT now())""")
    out.close()
    for base, prompt, n_c in prepared:
        rid, stratum, nchar = base[0], base[1], base[2]
        stages = []
        if not args.skip_gemma:
            stages.append(("gemma", call_gemma))
        if not args.skip_haiku:
            stages.append(("haiku", call_haiku))
        if not stages:
            stages.append(("none", None))
        for name, fn in stages:
            res = fn(prompt, n_c) if fn else {"wall_s": None, "in_tok": None, "out_tok": None, "text": ""}
            # Open, write, close per row: the results file is never held between calls.
            out = duckdb.connect(str(OUT_DIR / "timing.duckdb"))
            out.execute("INSERT INTO timing_sample VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,now())",
                        [run_id, *base, name, res.get("wall_s"), res.get("in_tok"),
                         res.get("out_tok"), res.get("cost_usd"), res.get("text")])
            out.close()
            print(f"{rid[:30]:30s} {stratum} chars={nchar} cands={n_c} {name} "
                  f"wall={res.get('wall_s') or 0:.1f}s out_tok={res.get('out_tok')}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
