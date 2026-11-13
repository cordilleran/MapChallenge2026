"""Bring a hand-run submission (Cowork, the agy app, the Claude app) into a runs folder.

Usage:
  ingest_manual.py SUBMISSION.zip RUNS_DIR CELL --harness cowork --model "Claude Opus 5.5" \
      [--effort medium] [--wall-min 12] [--reply reply.md] [--notes "..."]

Unpacks into RUNS_DIR/CELL/work/ (refusing any path that would land outside it),
keeps homework/ beside it, and writes run.json so evaluate.py treats the run like
any other. The zip is untrusted: nothing in it is executed here.
"""
import argparse, json, re, shutil, zipfile
from datetime import datetime, timezone
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("zip", type=Path); ap.add_argument("runs", type=Path); ap.add_argument("cell")
ap.add_argument("--harness", required=True); ap.add_argument("--model", required=True)
ap.add_argument("--effort", default=""); ap.add_argument("--wall-min", type=float)
ap.add_argument("--reply", type=Path, help="the agent's chat reply, saved as text")
ap.add_argument("--notes", default="")
a = ap.parse_args()

cell = a.runs / a.cell
if cell.exists():
    raise SystemExit(f"{cell} exists; pick a new cell name")
raw = cell / "unpacked"
raw.mkdir(parents=True)
with zipfile.ZipFile(a.zip) as z:
    for m in z.infolist():
        dest = (raw / m.filename).resolve()
        if not dest.is_relative_to(raw.resolve()):
            raise SystemExit(f"refused path in zip: {m.filename}")
        if m.is_dir():
            dest.mkdir(parents=True, exist_ok=True); continue
        if m.file_size > 200 * 2**20:
            raise SystemExit(f"refused file over 200 MB: {m.filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(m) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)

root = next((p.parent for p in raw.rglob("sim.py") if "versions" not in p.parts), None)
if root is None:
    raise SystemExit("no sim.py in the zip")
shutil.copytree(root, cell / "work")
if (root / "homework").exists():
    shutil.copytree(root / "homework", cell / "homework")

log = cell / "homework" / "commands.log"
n_cmds = len(re.findall(r"(?im)^\s*(?:\$|>|command:)", log.read_text(errors="replace"))) if log.exists() else None
attempts = len(list((cell / "homework" / "versions").glob("*.py"))) if (cell / "homework" / "versions").exists() else None
(cell / "stream.ndjson").write_text("")
if a.reply and a.reply.exists():
    shutil.copy2(a.reply, cell / "final_reply.md")
meta = {"cell": a.cell, "harness": a.harness, "model": a.model, "effort": a.effort, "manual": True,
        "started": datetime.now(timezone.utc).isoformat(), "wall_s": a.wall_min * 60 if a.wall_min else None,
        "exit": 0, "tool_calls_from_log": n_cmds, "earlier_versions": attempts, "notes": a.notes,
        "source_zip": a.zip.name}
(cell / "run.json").write_text(json.dumps(meta, indent=1))
print("ingested", a.cell, "| homework files:", sorted(p.name for p in (cell / "homework").glob("*")) if (cell / "homework").exists() else "none")
