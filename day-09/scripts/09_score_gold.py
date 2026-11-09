"""Day 9 slice S5: score layer 1 against the gold set.

Reads `tests/gold_labels.json` and the merged `roles` and `scopes` tables
(07_roles.py --merge), plus `mentions_l1` for the ingest method. Reports:

- scope: exact agreement, agreement allowing the labelled alternative, and
  the confusion table;
- place of study (study_site or data_extent), per method:
  - gazetteer + role call: precision over candidates the model called a place
    of study, recall over the gold study places;
  - ingest `Places:` line: precision and recall the same way, no role call;
- candidate roles: agreement on every labelled candidate;
- wrong resolutions: candidates whose gazetteer match is the wrong place.

A gold study place counts as found when a candidate's surface or matched name
contains it or is contained in it (case-insensitive).

Writes `gold_scores.json` beside the database and prints a summary.

Usage: python 09_score_gold.py
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
TESTS = Path(__file__).resolve().parent.parent / "tests"
STUDY = {"study_site", "data_extent"}


def match(a, b):
    a, b = a.lower(), b.lower()
    return a in b or b in a


def ratio(n, d):
    return round(n / d, 3) if d else None


def main():
    if not (TESTS / "gold_labels.json").exists():  # kept local, not in the repository (D129)
        print("tests/gold_labels.json is not here: the gold set is kept locally, not in the repository (D129). Nothing to score.")
        return 0
    gold = json.loads((TESTS / "gold_labels.json").read_text())["labels"]
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"), read_only=True)
    scopes = dict(con.execute("SELECT record_id, scope FROM scopes").fetchall())
    roles = {}
    for rid, surf, role in con.execute("SELECT record_id, surface, role FROM roles").fetchall():
        roles.setdefault(rid, {})[surf] = role
    names = {}
    for rid, surf, name in con.execute(
            "SELECT record_id, surface, name FROM mentions_l1 WHERE field IN ('title','abstract','keywords')").fetchall():
        names.setdefault(rid, {})[surf] = name
    ingest = {}
    for rid, surf, name in con.execute(
            "SELECT record_id, surface, name FROM mentions_l1 WHERE field = 'ingest'").fetchall():
        ingest.setdefault(rid, []).append((surf, name))

    exact = alt = 0
    conf = Counter()
    tp = fp = 0
    found = total_study = 0
    role_ok = role_n = 0
    itp = ifp = ifound = 0
    misses, false_pos, scope_miss = [], [], []
    for rid, g in gold.items():
        got = scopes.get(rid)
        conf[(g["scope"], got)] += 1
        exact += got == g["scope"]
        ok_alt = got in (g["scope"], g.get("alt_scope"))
        alt += ok_alt
        if not ok_alt:
            scope_miss.append(f"{rid}: gold {g['scope']} (alt {g.get('alt_scope')}), model {got}")
        r = roles.get(rid, {})
        nm = names.get(rid, {})
        for surf, role in r.items():
            if role in STUDY:
                # A candidate labelled in the gold set is scored by its label; one that
                # appeared after labelling (D119 fixes) by its match to a gold study place.
                if surf in g["roles"]:
                    ok = g["roles"][surf] in STUDY
                else:
                    ok = any(match(pl, surf) or match(pl, nm.get(surf) or "") for pl in g["study"])
                if ok and surf not in g.get("wrong_place", []):
                    tp += 1
                else:
                    fp += 1
                    false_pos.append(f"{rid}: {surf} -> {role} (gold {g['roles'].get(surf)})")
        for surf, grole in g["roles"].items():
            if surf in r:
                role_n += 1
                role_ok += r[surf] == grole
        for place in g["study"]:
            total_study += 1
            hit = any(match(place, s) or match(place, nm.get(s, "")) for s, ro in r.items() if ro in STUDY)
            found += hit
            if not hit:
                misses.append(f"{rid}: {place}")
            ifound += any(match(place, s) or match(place, n or "") for s, n in ingest.get(rid, []))
        for s, n in ingest.get(rid, []):
            if any(match(p, s) or match(p, n or "") for p in g["study"]):
                itp += 1
            else:
                ifp += 1

    out = {
        "n_records": len(gold),
        "scope_exact": ratio(exact, len(gold)),
        "scope_with_alt": ratio(alt, len(gold)),
        "scope_confusion": {f"{a} -> {b}": n for (a, b), n in sorted(conf.items(), key=str)},
        "gazetteer_role_call": {"precision": ratio(tp, tp + fp), "recall": ratio(found, total_study),
                                "tp": tp, "fp": fp, "found": found, "gold_study_places": total_study},
        "ingest_places": {"precision": ratio(itp, itp + ifp), "recall": ratio(ifound, total_study),
                          "tp": itp, "fp": ifp, "found": ifound},
        "candidate_role_agreement": {"agree": role_ok, "n": role_n, "rate": ratio(role_ok, role_n)},
        "wrong_resolutions": [f"{rid}: {w}" for rid, g in gold.items() for w in g.get("wrong_place", [])],
        "scope_disagreements": scope_miss,
        "study_place_misses": misses,
        "false_places_of_study": false_pos,
    }
    (OUT_DIR / "gold_scores.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if not isinstance(v, list)}, indent=1))
    for k in ("scope_disagreements", "study_place_misses", "false_places_of_study", "wrong_resolutions"):
        print(f"\n{k} ({len(out[k])}):")
        for x in out[k]:
            print("  " + x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
