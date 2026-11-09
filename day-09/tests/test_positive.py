"""Day 9 positive tests against the hand-set cases in positive_cases.json.

Layer 1 checks (run after 04): the expected study site appears among the
record's candidates, and the corresponding-view origin country (06_origins.py)
matches. Scope is checked after the role calls
(S5) when the `roles` table exists; until then it is reported as pending.

Usage: python tests/test_positive.py   (exit 1 on any failure)
"""
import json
import os
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("MC26_DAY09_DIR", "MC26_DAY09_DIR-not-set")) / "day09.duckdb"


def main():
    cases = json.loads((HERE / "positive_cases.json").read_text())["cases"]
    if not DB.exists():
        print(f"SKIP: {DB} not found (run the pipeline first, or set MC26_DAY09_DIR)")
        return 0
    con = duckdb.connect(str(DB), read_only=True)
    has_roles = bool(con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'roles'").fetchone()[0])
    fails = 0
    for c in cases:
        rid = c["record_id"]
        surf = {r[0].lower() for r in con.execute(
            "SELECT surface FROM mentions_l1 WHERE record_id = ?", [rid]).fetchall()}
        origin = con.execute("""SELECT country FROM origins WHERE record_id = ? AND corr_view
                                ORDER BY w_corr DESC LIMIT 1""", [rid]).fetchone()
        checks = []
        for want in c["expect_study_site_contains"]:
            checks.append((f"candidate '{want}'", any(want.lower() in s for s in surf)))
        checks.append((f"origin {c['expect_origin_country']}",
                       bool(origin) and origin[0] == c["expect_origin_country"]))
        if has_roles:
            got = con.execute("SELECT scope FROM scopes WHERE record_id = ?", [rid]).fetchone()
            checks.append((f"scope {c['expect_scope']}", bool(got) and got[0] == c["expect_scope"]))
        for name, ok in checks:
            fails += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {rid[:40]:40s} {name}")
        if not has_roles:
            print(f"PEND  {rid[:40]:40s} scope {c['expect_scope']} (after S5)")
        print(f"      candidates: {sorted(surf)[:12]} origin: {origin[0] if origin else None}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
