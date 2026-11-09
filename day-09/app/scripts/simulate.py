"""Corpus geography web app, W1: a simulated corpus in the data contract (D124, D125).

The app is built and tested on this before it sees real data. Margins are
taken loosely from the Day 9 run (scope shares, the share of studies that are
areas, features or settlements, the countries authors write from and study),
smoothed with a pseudo-count over every country so the simulation is not a
copy of the library. Places are real public places (GeoNames cities of
100,000 or more for institutions, other GeoNames places for settlements and
features); papers, links and weights are invented.

Writes `app/data/sim.json` (the contract) and `app/data/sim_expected.json`
(totals the app must reproduce: the W1 and W2 check).

Usage: python simulate.py [--n 1800] [--seed-name corpus-sim-a] [--home CA]
"""
import argparse
import json
import os
import sys
import random
from collections import Counter
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
APP = Path(__file__).resolve().parents[1] / "data"
SCOPES = {"non-spatial": 816, "regional": 515, "site": 257, "global": 143, "multi-site": 45,
          "local-implicit": 39}
SETTING = {  # P(setting | scope), invented for the simulation
    "site": {"rural": .55, "urban": .2, "mixed": .05, "unclear": .2},
    "multi-site": {"rural": .45, "urban": .15, "mixed": .25, "unclear": .15},
    "regional": {"rural": .35, "urban": .1, "mixed": .25, "unclear": .3},
    "local-implicit": {"rural": .3, "urban": .3, "unclear": .4},
    "global": {"not_applicable": .9, "unclear": .1},
    "non-spatial": {"not_applicable": 1.0},
}
DEST_KIND = {"area": .81, "feature": .11, "settlement": .08}
TOPICS = ["Hydrology and floods", "Climate change impacts", "Snow and glaciers", "Water governance",
          "Bayesian statistics", "Flood risk management", "Geomorphology", "Ecosystem services",
          "Adaptation planning", "Remote sensing", "Machine learning", "Urban planning",
          "Groundwater", "Forest ecology", "Indigenous knowledge", "Infrastructure asset management"]


def share(n, k):
    """Weight of member k of n, rounded, with the last taking the remainder so they sum to 1."""
    w = round(1 / n, 4)
    return round(1 - w * (n - 1), 4) if k == n - 1 else w


def pick(rng, d):
    r, acc = rng.random() * sum(d.values()), 0.0
    for k, v in d.items():
        acc += v
        if r <= acc:
            return k
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1800)
    ap.add_argument("--seed-name", default="corpus-sim-a")
    ap.add_argument("--home", default="CA", help="country the reader works in (home bias)")
    ap.add_argument("--out", default="sim")
    a = ap.parse_args()
    rng = random.Random(sum(map(ord, a.seed_name)))
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"), read_only=True)
    origin_w = dict(con.execute("""SELECT p.country, sum(o.w_all) FROM origins o
        JOIN places p ON p.place_id = 'i' || o.inst_id WHERE p.country IS NOT NULL GROUP BY 1""").fetchall())
    study_w = dict(con.execute("""SELECT d.country, sum(a.w_all) FROM arcs a JOIN places d ON d.place_id = a.dest_id
        WHERE d.country IS NOT NULL GROUP BY 1""").fetchall())
    cities = con.execute("""SELECT geonameid, name, country, lon, lat, population FROM gazetteer
        WHERE fcode IN ('PPLC','PPLA','PPLA2','PPL') AND population >= 100000""").fetchall()
    small = con.execute("""SELECT geonameid, name, country, lon, lat, fcode FROM gazetteer
        WHERE (fcode LIKE 'PPL%' AND population BETWEEN 1000 AND 30000)
           OR fcode IN ('STM','LK','GLCR','MT','ISL','BAY') ORDER BY hash(geonameid) LIMIT 60000""").fetchall()
    countries = con.execute("""SELECT iso, name FROM countries""").fetchall()
    con.close()
    names = dict(countries)
    for iso in names:  # pseudo-count so every country can appear
        origin_w[iso] = origin_w.get(iso, 0) + 0.3
        study_w[iso] = study_w.get(iso, 0) + 0.3
    by_cc, small_cc = {}, {}
    for c in cities:
        by_cc.setdefault(c[2], []).append(c)
    for s in small:
        small_cc.setdefault(s[2], []).append(s)

    places, pid = {}, {}

    def place(key, name, kind, lon, lat, code, ur):
        if key not in pid:
            pid[key] = len(places)
            places[key] = [name, kind, round(lon, 3), round(lat, 3), code, ur]
        return pid[key]

    papers, origins, studies = [], [], []
    for i in range(a.n):
        scope = pick(rng, SCOPES)
        setting = pick(rng, SETTING[scope])
        topic = rng.sample(range(len(TOPICS)), 2)
        papers.append([i, rng.randint(1995, 2026), scope, setting, topic])
        located = rng.random() < 0.71
        if located:
            na = rng.choice([1, 1, 2, 2, 3, 4])
            for _ in range(na):
                cc = pick(rng, {k: v for k, v in origin_w.items() if k in by_cc})
                g = rng.choice(sorted(by_cc[cc], key=lambda c: -c[5])[:6])
                o = place(f"i{g[0]}", f"University of {g[1]}", "institution", g[3], g[4], cc,
                          "urban" if rng.random() < .98 else "rural")
                origins.append([i, o, share(na, _), int(_ == 0)])
        if scope in ("non-spatial", "global", "local-implicit"):
            continue
        nd = {"site": rng.choice([1, 1, 2, 3]), "multi-site": rng.randint(4, 8),
              "regional": rng.choice([1, 1, 2])}[scope]
        home_cc = a.home if rng.random() < 0.3 else pick(rng, study_w)
        for _ in range(nd):
            kind = "area" if scope == "regional" else pick(rng, DEST_KIND)
            cc = home_cc if rng.random() < 0.7 else pick(rng, study_w)
            if kind == "area" or not small_cc.get(cc):
                d = place(f"a{cc}", names.get(cc, cc), "area", 0, 0, cc, None)
            else:
                g = rng.choice(small_cc[cc])
                k = "settlement" if g[5].startswith("PPL") else "feature"
                d = place(f"g{g[0]}", g[1], k, g[3], g[4], cc,
                          (rng.choice(["rural", "rural", "urban"]) if k == "settlement" else None))
            studies.append([i, d, share(nd, _), "site" if rng.random() < .8 else "data_extent"])

    P = [[k, *v] for k, v in sorted(places.items(), key=lambda kv: pid[kv[0]])]
    data = {"contract": "corpus-geography/0.1", "note": f"SIMULATED corpus ({a.seed_name}); not real papers.",
            "papers": {"cols": ["id", "year", "scope", "setting", "topics"], "rows": papers},
            "places": {"cols": ["key", "name", "kind", "lon", "lat", "code", "ur"], "rows": P},
            "origins": {"cols": ["paper", "place", "w", "corr"], "rows": origins},
            "studies": {"cols": ["paper", "place", "w", "role"], "rows": studies},
            "vocab": TOPICS, "areas": {"cols": ["code", "name"], "rows": sorted(names.items())}}
    exp = {"papers": len(papers), "scopes": dict(Counter(p[2] for p in papers)),
           "settings": dict(Counter(p[3] for p in papers)),
           "located": len({o[0] for o in origins}),
           "placed": len({s[0] for s in studies}),
           "study_weight_by_kind": {k: round(sum(s[2] for s in studies if P[s[1]][2] == k), 6)
                                    for k in ("area", "feature", "settlement")}}
    APP.mkdir(exist_ok=True)
    (APP / f"{a.out}.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    (APP / f"{a.out}_expected.json").write_text(json.dumps(exp, indent=1))
    print(json.dumps(exp, indent=1))


if __name__ == "__main__":
    main()
