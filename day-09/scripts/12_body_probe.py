"""Day 9 slice S8: a body-text probe for the urban-rural question (D122, D123).

A sample run, not the full layer 2 pass. For about 200 academic records (the
60 gold records plus a sample stratified by the layer 1 scope class), Haiku
reads the title, the abstract and two windows of the body text (the opening,
and the study-area or methods section), and returns:

- the scope class, re-judged with the body in view;
- up to 8 places of study, each with a verbatim quote from the text shown
  (D101 as amended in D123: the model may make a verified claim);
- the setting of the study: urban, rural, mixed, not_applicable or unclear,
  with labels from a fixed list and a verbatim quote (design note S7.4: a
  regional study of ungauged headwater basins reads as rural).

Verification is mechanical: a claim counts only when its quote appears in the
text shown (whitespace and case folded) and the place name appears in its
quote. Verified names are then matched to the gazetteer (country hint first,
then importance). Failed claims are kept, flagged, for the audit.

Results go to their own file, `body_probe.duckdb`, one row per call, so the
run never holds the main database and resumes where it stopped. Body text is
sent to the model for the sample records only (D107 amended, D123).

Usage:
    python 12_body_probe.py [--workers 4] [--limit N]
    python 12_body_probe.py --all        # the full body pass (D127): every academic record with body text
    python 12_body_probe.py --verify     # (re)score claims into probe_places / probe_setting
"""
import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
LIBRARY = Path(os.environ.get("MC26_LIBRARY") or sys.exit("Set MC26_LIBRARY to the library's records folder (see README)."))
TESTS = Path(__file__).resolve().parent.parent / "tests"
PROBE = OUT_DIR / "body_probe.duckdb"
SEED = sum(map(ord, "day09-body-probe"))
OPENING = 2500     # characters from the start of the body
WINDOW = 6000      # characters from the study-area or methods heading
STRATA = {"regional": 45, "multi-site": 20, "site": 25, "local-implicit": 15,
          "non-spatial": 25, "global": 10}
SCOPES = ["site", "multi-site", "regional", "global", "local-implicit", "non-spatial"]
SETTING = ["urban", "rural", "mixed", "not_applicable", "unclear"]
LABELS = ["city", "suburban", "peri-urban", "small-town", "rural-community", "indigenous-community",
          "agricultural", "rangeland", "forest", "mountain", "headwater", "glacier-snow", "arid",
          "wetland", "river-floodplain", "lake", "coastal", "marine", "polar", "remote", "ungauged",
          "industrial-mining", "protected-area", "whole-basin", "whole-country", "laboratory", "none"]
KINDS = ["settlement", "area", "feature", "site"]

# Section headings in priority order: a study-area section beats methods, which beats data.
_H = r"(?im)^[#*\s]*(?:\d+(?:\.\d+)*\.?\s*|[IVX]+\.\s*)?({})\b[^\n]{{0,60}}$"
HEADINGS = [re.compile(_H.format(k)) for k in (
    r"study\s+(?:area|site|region|sites|areas|domain|catchments?|basins?)|site\s+descriptions?|"
    r"description\s+of\s+the\s+study\s+(?:area|site)s?",
    r"materials?\s+and\s+methods?|data\s+and\s+methods?|methods?\s+and\s+data|methods?|methodology",
    r"data(?:\s+sources)?")]

SYSTEM = f"""You read research papers and report where and in what kind of setting the study was done. You answer with one JSON object and nothing else.

1. scope, one of: site (1 to 3 study sites), multi-site (4 or more), regional (an area such as a basin, province, country or continent is the subject), global (the whole world), local-implicit (empirical work, but no place is named beyond the authors' own), non-spatial (the object of study is an equation, method, model, algorithm, software, theory or language model; a method demonstrated on a named place is still spatial if the place's data are analysed).

2. study_places: up to 8 places where the work was done or whose data were analysed, most important first. Not places only mentioned as background, comparisons, cited studies or author addresses. For each: name (as written), kind ({"|".join(KINDS)}), country (ISO 3166 two-letter code, or ""), within (the province, state or region it lies in, or ""), and quote: a phrase of 5 to 25 words copied exactly from the text shown, that contains the name. Never invent a place or a quote. If the text names no place of study, return [].

3. setting: class, one of urban (the study's own setting is cities or built-up land), rural (farmland, forest, mountains, headwaters, small towns, remote communities, open water away from cities), mixed (the study explicitly covers both urban and rural settings), not_applicable (non-spatial, global, or the atmosphere or open ocean as a whole), unclear (the text does not say). Judge the setting from the study's purpose and words, not only from the place names: a regional study of ungauged headwater basins is rural even if the region contains cities. labels: 1 to 4 from {", ".join(LABELS)}. quote: a phrase of 5 to 25 words copied exactly from the text that shows the setting, or "" for not_applicable.

Format: {{"scope": "...", "study_places": [{{"name": "...", "kind": "...", "country": "..", "within": "...", "quote": "..."}}], "setting": {{"class": "...", "labels": ["..."], "quote": "..."}}, "reason": "<one short sentence>"}}"""

lock = threading.Lock()


def fold(s):
    return re.sub(r"\s+", " ", re.sub(r"[‐-―−]", "-", s or "")).strip().lower()


def body_text(rid):
    p = LIBRARY / rid / f"{rid}.source.md"
    if not p.exists():
        return ""
    t = p.read_text(errors="replace")
    return re.sub(r"^---\n.*?\n---\n", "", t, count=1, flags=re.S)


def windows(body):
    opening = body[:OPENING]
    for h in HEADINGS:
        m = h.search(body, OPENING // 2)
        if m:
            return opening, body[m.start(): m.start() + WINDOW], "heading:" + m.group(1).lower()
    return opening, body[OPENING: OPENING + WINDOW], "none"


def record_prompt(title, abstract, keywords, opening, window):
    return (f"Title: {title}\nAbstract: {(abstract or '')[:2500]}\nKeywords: {keywords or ''}\n\n"
            f"Body, opening:\n{opening}\n\nBody, study area or methods section:\n{window}")


def everything(con):
    """The full pass: every academic record with at least 3,000 characters of text, any language."""
    return [(rid, "all:" + sc) for rid, sc in con.execute("""SELECT r.record_id, coalesce(s.scope, 'none')
        FROM m.records r LEFT JOIN m.scopes s USING (record_id)
        WHERE r.academic AND r.text_chars >= 3000 ORDER BY hash(r.record_id)""").fetchall()]


def sample(con):
    if not (TESTS / "gold_labels.json").exists():
        sys.exit("The probe sample is drawn around the local gold set (tests/gold_labels.json, not in the repository); use --all")
    gold = list(json.loads((TESTS / "gold_labels.json").read_text())["labels"])
    rows = con.execute("""SELECT r.record_id, s.scope FROM m.records r JOIN m.scopes s USING (record_id)
                          WHERE r.academic AND r.lang = 'en' AND r.text_chars > 8000
                          ORDER BY r.record_id""").fetchall()
    rng = random.Random(SEED)
    by = {}
    for rid, sc in rows:
        if rid not in gold:
            by.setdefault(sc, []).append(rid)
    picked = [(rid, "gold") for rid in gold]
    for sc, n in STRATA.items():
        pool = by.get(sc, [])
        picked += [(rid, sc) for rid in rng.sample(pool, min(n, len(pool)))]
    return picked


def parse(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    js = json.loads(t)
    st = js.get("setting") or {}
    if js.get("scope") not in SCOPES or st.get("class") not in SETTING:
        raise ValueError(f"invalid scope {js.get('scope')!r} or setting {st.get('class')!r}")
    if not isinstance(js.get("study_places"), list):
        raise ValueError("study_places is not a list")
    return js


def call(prompt):
    t0 = time.time()
    p = subprocess.run(["claude", "-p", "--model", "haiku", "--output-format", "json",
                        "--system-prompt", SYSTEM, "--tools", "", "--no-session-persistence",
                        "--strict-mcp-config"],
                       input=prompt, capture_output=True, text=True, timeout=300, cwd=OUT_DIR)
    js = json.loads(p.stdout)
    return time.time() - t0, js.get("result", ""), js.get("total_cost_usd")


def work(job, run_id):
    rid, stratum, prompt, wtag = job
    err, js, res = None, None, (None, "", None)
    for _ in range(2):
        try:
            res = call(prompt)
            js = parse(res[1])
            err = None
            break
        except Exception as e:  # bad JSON, invalid label, CLI failure: retry once
            err = f"{type(e).__name__}: {e}"[:300]
    with lock:
        out = duckdb.connect(str(PROBE))
        out.execute("INSERT INTO probe_calls VALUES (?,?,?,?,?,?,?,?,?,?,now())",
                    [run_id, rid, stratum, wtag, prompt, res[1], json.dumps(js) if js else None,
                     err, res[0], res[2]])
        out.close()
    return rid, err, res[2]


def verify():
    """Check every claim against the text it was given; match verified names to the gazetteer."""
    con = duckdb.connect(str(PROBE))
    con.execute(f"ATTACH '{OUT_DIR / 'day09.duckdb'}' AS m (READ_ONLY)")
    last = con.execute("""SELECT record_id, stratum, prompt, answer FROM probe_calls WHERE answer IS NOT NULL
                          QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY ts DESC) = 1""").fetchall()
    places, settings = [], []
    for rid, stratum, prompt, ans in last:
        js, text = json.loads(ans), fold(prompt)
        for i, p in enumerate(js["study_places"][:8]):
            name, quote = (p.get("name") or "").strip(), fold(p.get("quote"))
            q_ok = bool(quote) and quote in text
            n_ok = bool(name) and fold(name) in quote
            key = re.sub(r"^the\s+", "", name.lower()).rstrip(".,;:")
            cc = (p.get("country") or "").upper()[:2]
            g = con.execute("""SELECT geonameid, name, fcode, country, admin1, lat, lon FROM m.gazetteer
                               WHERE key = ? ORDER BY (country = ?) DESC, importance DESC LIMIT 1""",
                            [key, cc]).fetchone() if q_ok and n_ok else None
            places.append([rid, stratum, i, name, p.get("kind"), cc, p.get("within"), p.get("quote"),
                           q_ok, n_ok, *(g or [None] * 7)])
        st = js["setting"]
        sq = fold(st.get("quote"))
        settings.append([rid, stratum, js["scope"], st["class"], json.dumps(st.get("labels") or []),
                         st.get("quote"), (not sq and st["class"] == "not_applicable") or (bool(sq) and sq in text),
                         js.get("reason")])
    con.execute("""CREATE OR REPLACE TABLE probe_places (record_id VARCHAR, stratum VARCHAR, i INTEGER,
        name VARCHAR, kind VARCHAR, country_claim VARCHAR, within VARCHAR, quote VARCHAR,
        quote_ok BOOLEAN, name_in_quote BOOLEAN, geonameid BIGINT, g_name VARCHAR, fcode VARCHAR,
        country VARCHAR, admin1 VARCHAR, lat DOUBLE, lon DOUBLE)""")
    con.executemany("INSERT INTO probe_places VALUES (" + ",".join("?" * 17) + ")", places)
    con.execute("""CREATE OR REPLACE TABLE probe_setting (record_id VARCHAR, stratum VARCHAR, scope VARCHAR,
        setting VARCHAR, labels VARCHAR, quote VARCHAR, quote_ok BOOLEAN, reason VARCHAR)""")
    con.executemany("INSERT INTO probe_setting VALUES (?,?,?,?,?,?,?,?)", settings)
    print(con.execute("""SELECT count(*) claims, sum(quote_ok::INT) quote_ok,
        sum((quote_ok AND name_in_quote)::INT) verified, count(geonameid) resolved FROM probe_places""").df())
    print(con.execute("""SELECT setting, count(*) n, sum(quote_ok::INT) quote_ok FROM probe_setting
                         GROUP BY 1 ORDER BY 2 DESC""").df().to_string(index=False))
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--all", action="store_true", help="the full body pass, not the sample")
    args = ap.parse_args()
    if args.verify:
        return verify()
    os.nice(10)
    run_id = datetime.datetime.now().strftime("%y%m%d-%H%M%S")
    out = duckdb.connect(str(PROBE))
    out.execute("""CREATE TABLE IF NOT EXISTS probe_calls (run_id VARCHAR, record_id VARCHAR,
        stratum VARCHAR, window_tag VARCHAR, prompt VARCHAR, raw VARCHAR, answer VARCHAR, error VARCHAR,
        wall_s DOUBLE, cost_usd DOUBLE, ts TIMESTAMP)""")
    done = {r[0] for r in out.execute(
        "SELECT DISTINCT record_id FROM probe_calls WHERE answer IS NOT NULL").fetchall()}
    out.close()

    con = duckdb.connect()
    con.execute(f"ATTACH '{OUT_DIR / 'day09.duckdb'}' AS m (READ_ONLY)")
    picked = everything(con) if args.all else sample(con)
    meta = {r[0]: r[1:] for r in con.execute(
        "SELECT record_id, title, abstract, keywords FROM m.records WHERE academic").fetchall()}
    con.close()
    jobs = []
    for rid, stratum in picked:
        if rid in done or rid not in meta:
            continue
        body = body_text(rid)
        if not body:
            continue
        opening, window, wtag = windows(body)
        jobs.append((rid, stratum, record_prompt(*meta[rid], opening, window), wtag))
    if args.limit:
        jobs = jobs[:args.limit]
    print(f"run {run_id}: {len(jobs)} records ({len(done)} already answered; sample {len(picked)})", flush=True)
    t0, cost, errs = time.time(), 0.0, 0
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(work, j, run_id) for j in jobs]
        for k, f in enumerate(as_completed(futs), 1):
            rid, err, c = f.result()
            cost += c or 0
            errs += bool(err)
            if err or k % 25 == 0 or k == len(jobs):
                print(f"{k}/{len(jobs)} {time.time() - t0:.0f}s ${cost:.3f} errors={errs}"
                      + (f"  {rid}: {err}" if err else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
