"""Day 9 slice S8: score the body-text probe (D123).

Reads `body_probe.duckdb` (after `12_body_probe.py --verify`), the layer 1
tables in `day09.duckdb` and `tests/gold_labels.json`. Reports:

- claim verification (quote found, name in quote, matched to the gazetteer);
- on the 60 gold records: places-of-study recall and precision for layer 1,
  the probe, and the two together; scope agreement for each;
- the setting class by layer 1 scope, and the labels used;
- for regional and multi-site papers, the setting next to the layer 1
  urban-rural class of their point places, where they have any.

Writes `body_probe_scores.json` beside the database and prints a summary.

Usage: python 13_probe_report.py
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
TESTS = Path(__file__).resolve().parent.parent / "tests"
STUDY = {"study_site", "data_extent"}


def match(a, b):
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a) and bool(b) and (a in b or b in a)


def r3(n, d):
    return round(n / d, 3) if d else None


def main():
    if not (TESTS / "gold_labels.json").exists():  # kept local, not in the repository (D129)
        print("tests/gold_labels.json is not here: the gold set is kept locally, not in the repository (D129). Nothing to score.")
        return 0
    gold = json.loads((TESTS / "gold_labels.json").read_text())["labels"]
    con = duckdb.connect(str(OUT_DIR / "body_probe.duckdb"), read_only=True)
    con.execute(f"ATTACH '{OUT_DIR / 'day09.duckdb'}' AS m (READ_ONLY)")
    out = {}
    out["claims"] = dict(zip(["claims", "quote_ok", "verified", "resolved"], con.execute("""
        SELECT count(*), sum(quote_ok::INT), sum((quote_ok AND name_in_quote)::INT), count(geonameid)
        FROM probe_places""").fetchone()))
    out["setting_quote_ok"] = con.execute("SELECT avg(quote_ok::INT) FROM probe_setting").fetchone()[0]
    out["cost_usd"] = con.execute("""SELECT sum(cost_usd) FROM probe_calls""").fetchone()[0]

    probe = defaultdict(list)
    for rid, name, g in con.execute("""SELECT record_id, name, g_name FROM probe_places
                                       WHERE quote_ok AND name_in_quote""").fetchall():
        probe[rid].append((name, g))
    l1 = defaultdict(list)
    for rid, surf, nm in con.execute("""SELECT r.record_id, r.surface, any_value(m.name) FROM m.roles r
        LEFT JOIN m.mentions_l1 m ON m.record_id = r.record_id AND m.surface = r.surface
        WHERE r.role IN ('study_site','data_extent') GROUP BY 1, 2""").fetchall():
        l1[rid].append((surf, nm))
    pscope = dict(con.execute("SELECT record_id, scope FROM probe_setting").fetchall())
    lscope = dict(con.execute("SELECT record_id, scope FROM m.scopes").fetchall())

    res = {k: Counter() for k in ("layer1", "probe", "union")}
    misses = []
    for rid, g in gold.items():
        if rid not in pscope:
            continue
        sets = {"layer1": l1[rid], "probe": probe[rid], "union": l1[rid] + probe[rid]}
        for k, cands in sets.items():
            for pl in g["study"]:
                res[k]["gold"] += 1
                res[k]["found"] += any(match(pl, a) or match(pl, b) for a, b in cands)
            for a, b in cands:
                ok = any(match(pl, a) or match(pl, b) for pl in g["study"])
                res[k]["tp" if ok else "fp"] += 1
        for pl in g["study"]:
            if not any(match(pl, a) or match(pl, b) for a, b in sets["union"]):
                misses.append(f"{rid}: {pl}")
        res["layer1"]["scope_ok"] += lscope.get(rid) in (g["scope"], g.get("alt_scope"))
        res["probe"]["scope_ok"] += pscope.get(rid) in (g["scope"], g.get("alt_scope"))
        res["layer1"]["n"] += 1
        res["probe"]["n"] += 1
    out["gold"] = {k: {"recall": r3(v["found"], v["gold"]), "precision": r3(v["tp"], v["tp"] + v["fp"]),
                       "scope_with_alt": r3(v["scope_ok"], v["n"]) if v["n"] else None, **v}
                   for k, v in res.items()}
    out["gold_misses_after_union"] = misses

    rows = con.execute("""SELECT coalesce(s.scope, 'unknown') l1, p.setting, count(*) FROM probe_setting p
        LEFT JOIN m.scopes s USING (record_id) GROUP BY ALL ORDER BY 1, 2""").fetchall()
    tab = defaultdict(dict)
    for a, b, n in rows:
        tab[a][b] = n
    out["setting_by_layer1_scope"] = tab
    out["setting_by_probe_scope"] = {a: dict(Counter(s for (r, s) in con.execute(
        "SELECT record_id, setting FROM probe_setting WHERE scope = ?", [a]).fetchall()))
        for a in ("site", "multi-site", "regional", "local-implicit", "global", "non-spatial")}
    labels = Counter()
    for (lj,) in con.execute("SELECT labels FROM probe_setting").fetchall():
        labels.update(json.loads(lj))
    out["labels"] = dict(labels.most_common())
    out["scope_shift"] = dict(Counter(f"{lscope.get(r)} -> {s}" for r, s in pscope.items()
                                      if lscope.get(r) != s).most_common())
    # Point places from layer 1 (urban or rural cells) beside the setting, for spatial papers.
    pts = con.execute("""SELECT p.record_id, p.setting, list(DISTINCT pl.ur) FROM probe_setting p
        JOIN m.arcs a USING (record_id) JOIN m.places pl ON pl.place_id = a.dest_id
        WHERE pl.ur IN ('urban','rural') GROUP BY 1, 2""").fetchall()
    out["setting_vs_point_cells"] = dict(Counter(f"{s} | cells {','.join(sorted(u))}" for _, s, u in pts))
    out["regional_settings_without_points"] = dict(Counter(s for (s,) in con.execute("""
        SELECT setting FROM probe_setting WHERE scope IN ('regional','multi-site')
          AND record_id NOT IN (SELECT a.record_id FROM m.arcs a JOIN m.places pl ON pl.place_id = a.dest_id
                                WHERE pl.ur IN ('urban','rural'))""").fetchall()))
    (OUT_DIR / "body_probe_scores.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if k != "gold_misses_after_union"}, indent=1, default=float))
    print("\ngold misses after union:", len(misses))
    for x in misses:
        print("  " + x)


if __name__ == "__main__":
    main()
