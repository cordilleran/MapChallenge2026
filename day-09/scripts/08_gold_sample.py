"""Day 9 slice S5: draw the 60-record gold set and write a labelling packet.

Strata: record type (article, other) by jurisdiction group (BC or Canada,
another named place, unspecified). Allocation: articles 12 / 16 / 16, other
types 5 / 5 / 6. Records already seen in a role-call pilot (`--exclude-run`)
and the positive-test records are left out, so the labeller is blind to the
model's answers.

The packet shows, per record: title, abstract, keywords, the layer 1
candidates with their gazetteer match, and an 1,200-character window from
the body's study-area section. Labels go in `tests/gold_labels.json`.

Usage: python 08_gold_sample.py --exclude-run 261108-192244,261108-192249
"""
import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
LIBRARY = Path(os.environ.get("MC26_LIBRARY") or sys.exit("Set MC26_LIBRARY to the library's records folder (see README)."))
TESTS = Path(__file__).resolve().parent.parent / "tests"
SEED = sum(map(ord, "day09-gold-set"))
ALLOC = {("article", "bc-ca"): 12, ("article", "named"): 16, ("article", "none"): 16,
         ("other", "bc-ca"): 5, ("other", "named"): 5, ("other", "none"): 6}
HEADING = re.compile(r"(?im)^\s*#*\s*(?:\d+(?:\.\d+)*\.?\s*)?(study\s+(?:area|site|region|sites|areas)|"
                     r"site\s+description|materials?\s+and\s+methods|data\s+and\s+methods|methods?|data)\s*$")


def jgroup(j):
    j = (j or "").lower()
    if not j.strip() or "unspecified" in j:
        return "none"
    if re.search(r"british columbia|\bbc\b|canada", j):
        return "bc-ca"
    return "named"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude-run", default="")
    args = ap.parse_args()
    con = duckdb.connect()
    con.execute(f"ATTACH '{OUT_DIR / 'day09.duckdb'}' AS m (READ_ONLY)")
    excl = {c["record_id"] for c in json.loads((TESTS / "positive_cases.json").read_text())["cases"]}
    if args.exclude_run:
        con.execute(f"ATTACH '{OUT_DIR / 'roles.duckdb'}' AS r (READ_ONLY)")
        runs = args.exclude_run.split(",")
        excl |= {x[0] for x in con.execute(
            f"SELECT DISTINCT record_id FROM r.role_calls WHERE run_id IN ({','.join('?' * len(runs))})",
            runs).fetchall()}
    recs = con.execute("""SELECT record_id, itype, jurisdiction, title, abstract, keywords
                          FROM m.records WHERE academic AND text_chars > 0 ORDER BY record_id""").fetchall()
    strata = {}
    for r in recs:
        if r[0] in excl:
            continue
        strata.setdefault(("article" if r[1] == "article" else "other", jgroup(r[2])), []).append(r)
    rng = random.Random(SEED)
    gold = []
    for k in sorted(ALLOC):
        gold += [(k, r) for r in rng.sample(strata[k], min(ALLOC[k], len(strata[k])))]
    out = []
    for (grp, jg), (rid, itype, jur, title, abstract, kw) in gold:
        cands = con.execute("""SELECT DISTINCT surface, name, country, fcode FROM m.mentions_l1
                               WHERE record_id = ? AND field IN ('title','abstract','keywords')""",
                            [rid]).fetchall()
        body = (LIBRARY / rid / f"{rid}.source.md").read_text(errors="replace")
        body = re.sub(r"^---\n.*?\n---\n", "", body, count=1, flags=re.S)
        m = HEADING.search(body)
        win = body[m.start(): m.start() + 1200] if m else body[:1200]
        out.append(f"### {rid}\n- stratum: {grp}/{jg}; type {itype}; jurisdiction: {jur}\n"
                   f"- title: {title}\n- keywords: {kw or ''}\n- abstract: {(abstract or '')[:1500]}\n"
                   f"- candidates: " + "; ".join(f"{s} [{n}, {c}, {f}]" for s, n, c, f in cands)
                   + f"\n- body window ({'heading' if m else 'start'}): "
                   + re.sub(r"\s+", " ", win) + "\n")
    (TESTS / "gold_ids.json").write_text(json.dumps(
        [{"record_id": r[0], "stratum": f"{g}/{j}"} for (g, j), r in gold], indent=1))
    pk = OUT_DIR / "gold_packet.md"
    pk.write_text("\n".join(out))
    print(f"{len(gold)} gold records; packet {pk} ({pk.stat().st_size // 1000} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
