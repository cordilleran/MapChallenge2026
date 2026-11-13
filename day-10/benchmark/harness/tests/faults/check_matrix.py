"""Read the fixture results, write the fault matrix, and fail if a check stopped working.

Usage: check_matrix.py RUNS_DIR OUT.md
Rules: the reference and every correct variant fail nothing; every fault is caught by at least one check.
"""
import json, sys
from pathlib import Path

from make_faults import FAULTS, VARIANTS

runs, out = Path(sys.argv[1]), Path(sys.argv[2])
rows, problems = [], []
for f, (what, target) in FAULTS.items():
    p = runs / f"fixture-{f}" / "result_v2.json"
    failed = json.loads(p.read_text())["failed_checks"] if p.exists() else ["no result"]
    caught_by_target = target is not None and any(t.split("/")[0] in " ".join(failed) or t in " ".join(failed) for t in target.split("/"))
    rows.append(f"| {f} | {what} | {target or '–'} | {', '.join(failed) or 'none'} | "
                f"{'–' if f == 'ref' else ('yes' if caught_by_target else 'no')} |")
    if f == "ref" and failed:
        problems.append(f"reference fails {failed}")
    if f != "ref" and not failed:
        problems.append(f"{f} ({what}) is caught by nothing")
for v, what in VARIANTS.items():
    p = runs / f"fixture-{v}" / "result_v2.json"
    failed = json.loads(p.read_text())["failed_checks"] if p.exists() else ["no result"]
    rows.append(f"| {v} | correct variant: {what} | must pass | {', '.join(failed) or 'none'} | {'yes' if not failed else 'NO'} |")
    if failed:
        problems.append(f"correct variant {v} ({what}) fails {failed}")
out.write_text("| Fixture | What it does | Meant to be caught by | Checks that failed | As intended |\n"
               "| :--- | :--- | :--- | :--- | :---: |\n" + "\n".join(rows) + "\n")
print(out.read_text())
if problems:
    sys.exit("MATRIX BROKEN: " + "; ".join(problems))
print("matrix holds: reference and variants pass, every fault is caught")
