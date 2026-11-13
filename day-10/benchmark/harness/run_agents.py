"""Run the Python prompt through each coding agent, one empty folder per run.

Usage: run_agents.py RUNS_DIR CELL [CELL ...]    (cells are keys of CELLS below)
       BENCH_PROMPT=python_prompt.md run_agents.py ...   to rerun version 1

Each run gets: an empty work folder, the clean venv first on PATH (numpy, scipy,
matplotlib only), the prompt as its only input, and its full event stream saved.
Claude Code runs with a fresh config folder (login only: no user settings, skills,
memory or hooks). agy runs with its normal login; its own settings are a known
confound. The agents run on the host; their sim.py is evaluated later in a container.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Version 1 runs (2026-11-11, runs-1111) used python_prompt.md; version 2 is the default from then on.
PROMPT_FILE = os.environ.get("BENCH_PROMPT", "python_prompt_v2.md")
PROMPT = (HERE.parent / "prompts" / PROMPT_FILE).read_text()
RT = Path(os.environ.get("BENCH_RT", Path(__file__).resolve().parents[1] / "runs"))   # runs/ beside harness/ unless BENCH_RT is set
VENV_BIN = RT / "venv" / "bin"
CC_CONFIG = RT / "cc-config"            # holds only .credentials.json
TIMEOUT_S = 45 * 60

CELLS = {
    "cc-sonnet55":   {"harness": "claude-code", "model": "claude-sonnet-5-5", "effort": "medium"},
    "cc-opus55":     {"harness": "claude-code", "model": "claude-opus-5-5", "effort": "medium"},
    "agy-sonnet55":  {"harness": "agy", "model": "claude-sonnet-5-5-medium"},
    "agy-opus55":    {"harness": "agy", "model": "claude-opus-5-5-medium"},
    "agy-argon4":    {"harness": "agy", "model": "gemini-4-argon-medium"},
    "agy-flash38":   {"harness": "agy", "model": "gemini-3.8-flash-high"},
    "agy-hydrogen4": {"harness": "agy", "model": "gemini-4-hydrogen-high"},   # round 3 (11-12): Flash 3.8's successor, same tier
    "agy-gptoss":    {"harness": "agy", "model": "gpt-oss-120b-medium"},
}

CC_TOOLS = ["Read", "Write", "Edit", "Bash(python3:*)", "Bash(python:*)", "Bash(ls:*)",
            "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(mkdir:*)", "Bash(wc:*)"]


def command(cell):
    c = CELLS[cell]
    if c["harness"] == "claude-code":
        return ["claude", "-p", PROMPT, "--model", c["model"], "--effort", c["effort"],
                "--permission-mode", "acceptEdits", "--allowedTools", *CC_TOOLS,
                "--output-format", "stream-json", "--verbose", "--no-session-persistence"], None
    msg = {"event": "user", "message": {"role": "user", "content": [{"type": "text", "text": PROMPT}]}}
    return ["agy", f"--model={c['model']}", "--dangerously-skip-permissions",
            "--input-format=stream-json", "--output-format=stream-json"], json.dumps(msg) + "\n"


def run(runs_dir, cell):
    d = runs_dir / cell
    work = d / "work"
    work.mkdir(parents=True, exist_ok=False)          # never reuse a folder
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX")}
    env["PATH"] = f"{VENV_BIN}:/usr/local/bin:/usr/bin:/bin:{Path.home() / '.local/bin'}"
    if CELLS[cell]["harness"] == "claude-code":
        env["CLAUDE_CONFIG_DIR"] = str(CC_CONFIG)
    cmd, stdin = command(cell)
    t0 = time.time(); started = datetime.now(timezone.utc).isoformat()
    try:
        r = subprocess.run(["nice", "-n", "10", *cmd], input=stdin, capture_output=True, text=True,
                           cwd=work, env=env, timeout=TIMEOUT_S)
        out, err, code = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, err, code = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout", -1
    (d / "stream.ndjson").write_text(out); (d / "stderr.txt").write_text(err or "")
    meta = {"cell": cell, **CELLS[cell], "prompt": PROMPT_FILE, "started": started, "wall_s": round(time.time() - t0, 1),
            "exit": code, "prompt_chars": len(PROMPT)}
    (d / "run.json").write_text(json.dumps(meta, indent=1))
    print(cell, "exit", code, f"{meta['wall_s']} s", flush=True)


if __name__ == "__main__":
    runs_dir = Path(sys.argv[1]); runs_dir.mkdir(parents=True, exist_ok=True)
    for cell in sys.argv[2:]:
        run(runs_dir, cell)
