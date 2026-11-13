"""Check each agent's sim.py in the container, recompute its numbers, and read its run log.

Usage: evaluate.py RUNS_DIR

For each RUNS_DIR/<cell>/work/sim.py: copy it to RUNS_DIR/<cell>/eval/, run it three
times in the geo-bench image (no network, 1 CPU, 2 GB, non-root): seed 42 twice and
seed 43 once. Every check is computed here from the saved arrays; the script's own
telemetry is compared against it, never trusted. Writes RUNS_DIR/<cell>/eval/result.json.
"""
import hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

import numpy as np

IMAGE = os.environ.get("BENCH_IMAGE", "geo-bench:py314")  # geo-bench:landlab for the Day 10 Landlab build
LIMIT_S = 180                      # the prompt asks for 120 s; 1.5x before calling it a timeout
SNAP_SHOTS = Path.home() / "snap/chromium/common"   # the only place snap Chromium can write
NEEDED = ["z_initial.npy", "z_final.npy", "telemetry.json", "map.png", "map.html"]
KEYS = ["seed", "grid_shape", "cell_size_m", "years_simulated", "timesteps", "open_boundaries",
        "sediment_exported_m3", "uplift_or_baselevel_m3", "max_erosion_m", "max_deposition_m",
        "mass_balance_error_pct"]


def run_once(ev, seed, tag):
    out = f"out{tag}"
    cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "2g",
           "-u", f"{_uid()}:{_gid()}", "-e", "HOME=/tmp", "-v", f"{ev}:/work", IMAGE,
           "timeout", str(LIMIT_S), "python", "sim.py", "--seed", str(seed), "--out", f"/work/{out}"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    (ev / f"{out}.log").write_text(r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-20000:])
    return {"exit": r.returncode, "seconds": round(time.time() - t0, 1), "timed_out": r.returncode == 124,
            "dir": ev / out, "last_error": (r.stderr.strip().splitlines() or [""])[-1][:300]}


def _uid():
    import os; return os.getuid()


def _gid():
    import os; return os.getgid()


def sha(a):
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes()).hexdigest()


def physics(d, tel):
    z0, z1 = np.load(d / "z_initial.npy"), np.load(d / "z_final.npy")
    dz = z1 - z0
    dx = float(tel.get("cell_size_m") or np.nan)
    vol = dx * dx
    net = float(dz.sum() * vol)
    gross = float(np.abs(dz).sum() * vol / 2)          # material moved, counted once
    exported = float(tel.get("sediment_exported_m3") or 0.0)
    added = float(tel.get("uplift_or_baselevel_m3") or 0.0)
    # every cubic metre accounted: change on the grid + what left = what was added
    imbalance = abs(net + exported - added) / gross * 100 if gross > 0 else None
    return {
        "shape": list(z1.shape), "finite": bool(np.isfinite(z1).all()),
        "relief_initial_m": round(float(np.nanmax(z0) - np.nanmin(z0)), 3),
        "max_erosion_m": round(float(-dz.min()), 4), "max_deposition_m": round(float(dz.max()), 4),
        "cells_eroded_gt_1mm_pct": round(float((dz < -1e-3).mean() * 100), 2),
        "cells_deposited_gt_1mm_pct": round(float((dz > 1e-3).mean() * 100), 2),
        "net_volume_change_m3": round(net, 3), "gross_moved_m3": round(gross, 3),
        "mass_imbalance_pct_recomputed": None if imbalance is None else round(imbalance, 3),
        "sha_z_final": sha(z1),
    }


def html_checks(path):
    t = path.read_text(errors="replace")
    urls = sorted(set(re.findall(r"""(?:src|href)\s*=\s*["'](https?://[^"']+)""", t)))
    imports = sorted(set(re.findall(r"""@import\s+url\(["']?(https?://[^)"']+)""", t)))
    return {"html_kb": round(len(t.encode()) / 1024, 1), "external_refs": urls + imports,
            "has_input_controls": bool(re.search(r"<input|<select|<button", t, re.I))}


def screenshot(html, dest):
    SNAP_SHOTS.mkdir(parents=True, exist_ok=True)
    tmp = SNAP_SHOTS / f"bench_{dest.parent.parent.name}.png"
    tmp.unlink(missing_ok=True)
    subprocess.run(["chromium-browser", "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--window-size=1400,1000", "--virtual-time-budget=20000",
                    f"--screenshot={tmp}", f"file://{html}"], capture_output=True, timeout=120)
    if tmp.exists():
        shutil.move(tmp, dest); return True
    return False


def agent_log(cell_dir):
    """Turns, tool calls, tokens and the final reply from the saved event stream."""
    s = (cell_dir / "stream.ndjson").read_text() if (cell_dir / "stream.ndjson").exists() else ""
    ev = [json.loads(l) for l in s.splitlines() if l.strip().startswith("{")]
    tools, final, usage, cost = 0, "", {}, None
    for e in ev:
        if e.get("type") == "assistant":                       # Claude Code
            for c in e.get("message", {}).get("content", []):
                tools += c.get("type") == "tool_use"
        if e.get("type") == "result":
            final, usage, cost = e.get("result", ""), e.get("usage", {}), e.get("total_cost_usd")
        if e.get("event") == "result":                         # agy
            final = e.get("result", {}).get("response", "")
            usage = e.get("result", {}).get("usage", {}) or usage
    if not tools:
        tools = sum(1 for l in s.splitlines() if '"tool_name"' in l)
    reply = cell_dir / "final_reply.md"
    if final or not reply.exists():          # a hand-run reply saved at ingest is kept
        reply.write_text(final or "")
    else:
        final = reply.read_text()
    if not s:                                # hand run: count commands from its own log
        tools = json.loads((cell_dir / "run.json").read_text()).get("tool_calls_from_log")
    return {"tool_calls": tools, "reply_chars": len(final or ""), "usage": usage, "cost_usd_api_equiv": cost}


def evaluate(cell_dir):
    work, ev = cell_dir / "work", cell_dir / "eval"
    res = {"cell": cell_dir.name, **json.loads((cell_dir / "run.json").read_text()), **agent_log(cell_dir)}
    if not (work / "sim.py").exists():
        res["verdict_notes"] = ["no sim.py written"]; return res
    if ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(); shutil.copy2(work / "sim.py", ev / "sim.py")
    res["sim_py_lines"] = sum(1 for _ in (ev / "sim.py").open())
    runs = {"a": run_once(ev, 42, "42a"), "b": run_once(ev, 42, "42b"), "c": run_once(ev, 43, "43")}
    res["runs"] = {k: {kk: vv for kk, vv in v.items() if kk != "dir"} for k, v in runs.items()}
    a = runs["a"]["dir"]
    res["files_present"] = {f: (a / f).exists() for f in NEEDED}
    tel = {}
    if (a / "telemetry.json").exists():
        try:
            tel = json.loads((a / "telemetry.json").read_text())
        except json.JSONDecodeError as e:
            res["telemetry_error"] = str(e)
    res["telemetry"] = tel
    res["telemetry_missing_keys"] = [k for k in KEYS if k not in tel]
    if (a / "z_initial.npy").exists() and (a / "z_final.npy").exists():
        res["physics"] = phys = physics(a, tel)
        b, c = runs["b"]["dir"], runs["c"]["dir"]
        res["deterministic"] = (b / "z_final.npy").exists() and sha(np.load(b / "z_final.npy")) == phys["sha_z_final"]
        res["seed_changes_result"] = (c / "z_final.npy").exists() and sha(np.load(c / "z_final.npy")) != phys["sha_z_final"]
        claimed = {k: tel.get(k) for k in ("max_erosion_m", "max_deposition_m", "mass_balance_error_pct")}
        res["claimed_vs_recomputed"] = {
            "max_erosion_m": [claimed["max_erosion_m"], phys["max_erosion_m"]],
            "max_deposition_m": [claimed["max_deposition_m"], phys["max_deposition_m"]],
            "mass_balance_error_pct": [claimed["mass_balance_error_pct"], phys["mass_imbalance_pct_recomputed"]],
        }
    if (a / "map.html").exists():
        res["html"] = html_checks(a / "map.html")
        res["screenshot"] = screenshot(a / "map.html", ev / "map_html.png")
    return res


if __name__ == "__main__":
    runs_dir = Path(sys.argv[1])
    for cell_dir in sorted(p for p in runs_dir.iterdir() if (p / "run.json").exists()):
        r = evaluate(cell_dir)
        (cell_dir / "result.json").write_text(json.dumps(r, indent=1, default=str))
        print(cell_dir.name, "deterministic", r.get("deterministic"), "imbalance",
              r.get("physics", {}).get("mass_imbalance_pct_recomputed"), flush=True)
