"""Version 2 evaluation: the default runs plus the --z0 test runs, then every check.

Usage: evaluate_v2.py RUNS_DIR [CELL ...] [--jobs N]

For each RUNS_DIR/<cell>/work/sim.py, in RUNS_DIR/<cell>/eval2/:
  default: seed 42 twice (with maps) and seed 43 (--no-map)
  tests:   scarp (no rain, bare; and no rain, vegetated), ramp (bare), basin, hillslope
           (as is; bare; no rain; double rain; double vegetation; half time step)
All in the geo-bench container: no network, one CPU, 2 GB, non-root. A version 1 entry
(no --z0) gets the default runs and the array checks only. Writes result_v2.json.
"""
import argparse, json, shutil, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import checks_arrays, checks_runs, surfaces
from evaluate import IMAGE, NEEDED, _gid, _uid, agent_log, html_checks, screenshot, sha

V2_KEYS = ["seed", "grid_shape", "cell_size_m", "years_simulated", "timesteps", "dt_years", "storm_count",
           "mean_annual_rain_mm", "creep_diffusivity_m2_per_yr", "open_boundaries", "sediment_exported_m3",
           "uplift_or_baselevel_m3", "mass_balance_error_pct"]
LIMIT = {"map": 360, "nomap": 90, "nomap_dt": 180}   # 1.5x the prompt's 240 / 60 / 120 s

TESTS = [  # name, surface, extra arguments
    ("scarp_bare", "scarp", ["--rain-scale", "0", "--veg-scale", "0"]),
    ("scarp_veg", "scarp", ["--rain-scale", "0"]),
    ("ramp", "ramp", ["--veg-scale", "0"]),
    ("basin", "basin", []),
    ("basin_rain0", "basin", ["--rain-scale", "0"]),                          # C3: did rain do anything here
    ("hill", "hill", []),
    ("hill_veg0", "hill", ["--veg-scale", "0"]),
    ("hill_rain0", "hill", ["--rain-scale", "0", "--veg-scale", "0"]),      # C6: creep alone, bare ground
    ("hill_rain0_veg1", "hill", ["--rain-scale", "0"]),                      # C8: creep alone at each cover,
    ("hill_rain0_veg2", "hill", ["--rain-scale", "0", "--veg-scale", "2"]),  # to separate wash from creep
    ("hill_rain2", "hill", ["--rain-scale", "2"]),
    ("hill_veg2", "hill", ["--veg-scale", "2"]),
    ("hill_dt05", "hill", ["--dt-scale", "0.5"]),
]


RESCORE_MODE = False
RESCORE = {}   # tag -> earlier run record, filled by --rescore: reuse the saved outputs instead of running again


def run(ev, tag, args, limit):
    if tag in RESCORE and (ev / tag / "telemetry.json").exists():
        return RESCORE[tag]
    cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "2g",
           "-u", f"{_uid()}:{_gid()}", "-e", "HOME=/tmp", "-v", f"{ev}:/work", IMAGE,
           "timeout", str(limit), "python", "sim.py", *args, "--out", f"/work/{tag}"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    (ev / f"{tag}.log").write_text(r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-20000:])
    return {"tag": tag, "exit": r.returncode, "seconds": round(time.time() - t0, 1), "timed_out": r.returncode == 124,
            "last_error": (r.stderr.strip().splitlines() or [""])[-1][:300]}


def supports_v2(ev):
    src = (ev / "sim.py").read_text(errors="replace")
    return all(f in src for f in ("--z0", "--rain-scale", "--veg-scale", "--no-map"))


def evaluate(cell_dir, jobs):
    work, ev = cell_dir / "work", cell_dir / "eval2"
    res = {"cell": cell_dir.name, **json.loads((cell_dir / "run.json").read_text()), **agent_log(cell_dir)}
    if not (work / "sim.py").exists():
        res["notes"] = ["no sim.py"]; return res
    RESCORE.clear()
    if RESCORE_MODE and (cell_dir / "result_v2.json").exists() and ev.exists():
        old = json.loads((cell_dir / "result_v2.json").read_text())
        RESCORE.update({**old.get("runs", {}), **old.get("test_runs", {})})
    elif ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(exist_ok=True); shutil.copy2(work / "sim.py", ev / "sim.py")
    res["sim_py_lines"] = sum(1 for _ in (ev / "sim.py").open())
    v2 = supports_v2(ev)
    res["contract"] = "v2" if v2 else "v1"
    nomap = ["--no-map"] if v2 else []
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        base = list(ex.map(lambda a: run(ev, *a), [
            ("d42a", ["--seed", "42"], LIMIT["map"]), ("d42b", ["--seed", "42"], LIMIT["map"]),
            ("d43", ["--seed", "43", *nomap], LIMIT["nomap"] if v2 else LIMIT["map"])]))
    res["runs"] = {b["tag"]: b for b in base}
    a = checks_runs.load(ev / "d42a")
    res["files_present"] = {f: (ev / "d42a" / f).exists() for f in NEEDED + (["vegetation.npy", "storms.csv"] if v2 else [])}
    if a is None:
        return res
    tel = a["tel"]; res["telemetry"] = tel
    res["telemetry_missing_keys"] = [k for k in V2_KEYS if k not in tel] if v2 else None
    b, c = checks_runs.load(ev / "d42b"), checks_runs.load(ev / "d43")
    res["deterministic"] = b is not None and sha(b["z1"]) == sha(a["z1"])
    res["seed_changes_result"] = c is not None and sha(c["z1"]) != sha(a["z1"])
    res["finite"] = bool(np.isfinite(a["z1"]).all())
    res["bookkeeping_self_consistent_pct"] = (abs(float((a["z1"] - a["z0"]).sum()) * tel["cell_size_m"] ** 2
                                              + float(tel.get("sediment_exported_m3") or 0) - float(tel.get("uplift_or_baselevel_m3") or 0))
                                              / max(checks_runs.gross(a), 1e-30) * 100)
    arr, sig = checks_arrays.run(a["z0"], a["z1"], tel)
    res["A_default"] = arr
    np.savez_compressed(ev / "signature_default.npz", **sig)
    if (ev / "d42a" / "map.html").exists():
        res["html"] = html_checks(ev / "d42a" / "map.html")
        res["screenshot"] = screenshot(ev / "d42a" / "map.html", ev / "map_html.png")
    res["B1_storms"] = checks_runs.b1_storms(ev / "d42a", ev / "d43", tel) if v2 else {"fail": None, "note": "v1 contract"}
    res["B2_vegetation"] = checks_runs.b2_vegetation(a) if v2 else {"fail": None, "note": "v1 contract"}
    if not v2:
        return res

    shape, dx = tuple(tel["grid_shape"]), float(tel["cell_size_m"])
    meta = {}
    for name, fn in surfaces.SURFACES.items():
        out = fn(shape, dx)
        z, extra = (out if isinstance(out, tuple) else (out, None))
        np.save(ev / f"surface_{name}.npy", z.astype(np.float64)); meta[name] = extra
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        tr = list(ex.map(lambda t: run(ev, t[0], ["--seed", "42", "--z0", f"/work/surface_{t[1]}.npy", *t[2], "--no-map"],
                                       LIMIT["nomap_dt"] if "--dt-scale" in t[2] else LIMIT["nomap"]), TESTS))
    res["test_runs"] = {t["tag"]: t for t in tr}
    L = {t[0]: checks_runs.load(ev / t[0]) for t in TESTS}
    res["C1_scarp"] = checks_runs.c1_scarp(L["scarp_bare"], L["scarp_veg"])
    res["C2_ramp"] = checks_runs.c2_ramp(L["ramp"], meta["ramp"])
    res["C3_basin"] = checks_runs.c3_basin(L["basin"], L["basin_rain0"])
    if L["hill"] is not None:
        res["C4_hill"], sig_h = checks_arrays.run(L["hill"]["z0"], L["hill"]["z1"], L["hill"]["tel"])
        np.savez_compressed(ev / "signature_hill.npz", **sig_h)
    res["C5_mirror"] = checks_runs.c5_mirror(L["hill_veg0"])
    res["C6_no_rain"] = checks_runs.c6_no_rain(L["hill_rain0"], res["C1_scarp"].get("bare", {}) and res["C1_scarp"]["bare"].get("K_recovered_m2_per_yr"))
    res["C7_rain"] = checks_runs.c7_rain(L["hill"], L["hill_rain2"])
    res["C8_vegetation"] = checks_runs.c8_vegetation(L["hill_veg0"], L["hill"], L["hill_veg2"],
                                                     L["hill_rain0"], L["hill_rain0_veg1"], L["hill_rain0_veg2"])
    res["C9_timestep"] = checks_runs.c9_timestep(L["hill"], L["hill_dt05"])
    res["C4_crest_balance"] = checks_runs.crest_balance(L["hill_veg0"], L["hill_rain0"])   # B11: a descriptor, never fails
    return res


def failures(res):
    """Every check that failed, by its short name."""
    out = [f"ran:{t}" for t, r in {**res.get("runs", {}), **res.get("test_runs", {})}.items() if r.get("exit") != 0]
    for k, v in res.items():
        if isinstance(v, dict) and v.get("fail") is True:
            out.append(k.split("_")[0])
        if k in ("A_default", "C4_hill") and isinstance(v, dict):
            out += [f"{k.split('_')[0]}:{kk.split('_')[0]}" for kk, vv in v.items() if isinstance(vv, dict) and vv.get("fail") is True]
    if res.get("deterministic") is False:
        out.append("repeat")
    if res.get("seed_changes_result") is False:
        out.append("seed")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("runs", type=Path); ap.add_argument("cells", nargs="*")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--rescore", action="store_true", help="re-run the checks on saved outputs; run only what is missing")
    a = ap.parse_args()
    RESCORE_MODE = a.rescore
    for cell_dir in sorted(p for p in a.runs.iterdir() if (p / "run.json").exists() and (not a.cells or p.name in a.cells)):
        r = evaluate(cell_dir, a.jobs)
        r["failed_checks"] = failures(r)
        (cell_dir / "result_v2.json").write_text(json.dumps(r, indent=1, default=str))
        print(cell_dir.name, r.get("contract"), "failed:", r["failed_checks"] or "none", flush=True)
