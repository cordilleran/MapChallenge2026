"""Build the Day 10 learning-lab page: seven scenario runs of sim.py, packed into one offline HTML file.

Run:  .venv/bin/python build_page.py [--years N] [--bench DIR]   (4,000 years by default; the benchmark default is 2,000)
Writes app/index.html (template app/template.html with the data inlined) and app/lab-data.json.

Scenarios use the same flags the benchmark's checker uses, so each scenario on the page is a
run of the same code the checker scored. Grids are packed as base64 int16: the starting surface in cm and the
change since the start in mm (clipped at +/-32.767 m, counted in `clipped_cells`).
"""
import argparse
import base64
import json
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SCENARIOS = [
    ("base", "Baseline", {}),
    ("dry", "Rain ×0.5", {"rain_scale": 0.5}),
    ("wet", "Rain ×2", {"rain_scale": 2.0}),
    ("bare", "Cover ×0", {"veg_scale": 0.0}),
    ("dense", "Cover ×2", {"veg_scale": 2.0}),
    ("m05", "Wash m 0.5", {"m_sp": 0.5}),
    ("m10", "Wash m 1", {"m_sp": 1.0}),
]
# Benchmark entries shown in the vignette: folder under --bench -> label. Verdicts are read from each
# result_v2.json; by default from benchmark/entries/ in this folder, where every entry is published.
ENTRIES = [
    ("agy-argon4", "Antigravity, Gemini 4 Argon (round 1)", "agent"),
    ("cc-sonnet55", "Claude Code, Sonnet 5.5 (round 1)", "agent"),
    ("agy-sonnet55", "Antigravity, Sonnet 5.5 (round 1)", "agent"),
    ("cc-opus55", "Claude Code, Opus 5.5", "agent"),
    ("agy-opus55", "Antigravity, Opus 5.5", "agent"),
    ("agy-flash38", "Antigravity, Gemini 3.8 Flash", "agent"),
    ("agy-hydrogen4", "Antigravity, Gemini 4 Hydrogen", "agent"),
    ("landlab-ref", "Landlab build: first version", "landlab"),
    ("landlab-s2b", "Landlab build: shrubs soak up runon", "landlab"),
    ("landlab-gully", "Landlab build: this page (gullies)", "landlab"),
]


def pack(a, dtype=np.int16):
    return base64.b64encode(np.ascontiguousarray(a.astype(dtype)).tobytes()).decode()


def drainage_log10(z):
    from landlab import RasterModelGrid
    from landlab.components import FlowAccumulator
    import sim
    g = RasterModelGrid((sim.NY, sim.NX), xy_spacing=sim.DX)
    g.add_field("topographic__elevation", sim.to_ll(z), at="node")
    g.set_closed_boundaries_at_grid_edges(True, True, True, False)
    FlowAccumulator(g, flow_director="D8").run_one_step()
    return np.log10(np.maximum(sim.from_ll(g.at_node["drainage_area"]), sim.DX * sim.DX))


def run_scenario(key, label, flags, years):
    import sim
    years_default, m_default = sim.YEARS, sim.M_SP
    sim.YEARS = years
    sim.M_SP = flags.get("m_sp", m_default)

    class A:
        seed, z0, dt_scale, no_map, out = 42, None, 1.0, True, ""
        rain_scale = flags.get("rain_scale", 1.0)
        veg_scale = flags.get("veg_scale", 1.0)

    t = time.time()
    try:
        z_init, z_final, cover, storms, tel, frames = sim.run(A)
    finally:
        sim.YEARS, sim.M_SP = years_default, m_default
    tel["mean_annual_rain_mm"] = round(tel["mean_annual_rain_mm"] * A.rain_scale, 2)   # sim reports the unscaled series
    budget = np.array(tel.pop("budget"))                      # year, exported, gross cut, gross fill
    keep = np.unique(np.r_[np.arange(0, len(budget), max(1, len(budget) // 160)), len(budget) - 1])
    print(f"{key}: {time.time() - t:.1f} s, export {tel['sediment_exported_m3']:.0f} m3", flush=True)
    dz = [np.zeros_like(z_init)] + [f - z_init for _, f in frames]
    if frames[-1][0] < years:            # make sure the last frame is the end of the run
        dz.append(z_final - z_init); frames.append((years, z_final))
    dz_mm = np.stack(dz) * 1000.0
    clipped = int((np.abs(dz_mm) > 32767).sum())
    rain_by_year = np.zeros(int(years))
    for y, d, _ in storms:
        rain_by_year[min(int(y), int(years) - 1)] += d * A.rain_scale
    return {
        "key": key, "label": label, "flags": {"rain_scale": A.rain_scale, "veg_scale": A.veg_scale,
                                               "m_sp": flags.get("m_sp", m_default)},
        "budget": {"year": [round(v, 1) for v in budget[keep, 0]], "exported_m3": [round(v) for v in budget[keep, 1]],
                   "cut_m3": [round(v) for v in budget[keep, 2]], "fill_m3": [round(v) for v in budget[keep, 3]]},
        "years": [0.0] + [round(t_, 1) for t_, _ in frames],
        "dz_mm": pack(np.clip(np.round(dz_mm), -32767, 32767)), "clipped_cells": clipped,
        "cover_pct": pack(np.round(cover * 100), np.uint8),
        "logA": pack(np.round(drainage_log10(z_final) * 1000)),
        "rain_mm_by_year": [round(v, 1) for v in rain_by_year],
        "telemetry": tel, "z_init_cm": pack(np.round(z_init * 100)),
    }


def bench_entries(bench):
    out = []
    for folder, label, kind in ENTRIES:
        f = bench / folder / "result_v2.json"
        if not f.exists():
            out.append({"cell": Path(folder).name, "label": label, "kind": kind, "status": "pending"}); continue
        d = json.loads(f.read_text())
        tel = d.get("telemetry") or {}
        c8 = d.get("C8_vegetation") or {}
        out.append({
            "cell": Path(folder).name, "label": label, "kind": kind,
            "status": "scored" if d.get("contract") != "v1" else "a_only",   # round 1: only the default-run (A) checks apply
            "failed": d.get("failed_checks", []),
            "lines": d.get("sim_py_lines"), "model": d.get("model"),
            "export_m3": tel.get("sediment_exported_m3"),
            "years": tel.get("years_simulated"),
            "c8_loss_m3": c8.get("upper_slope_wash_loss_by_veg_scale_0_1_2_m3"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=4000.0)
    ap.add_argument("--bench", type=Path, default=HERE / "benchmark/entries", help="folder holding one sub-folder per entry")
    ap.add_argument("--root", default="../../site/", help="path from the page to the site root (fonts, favicon); ../ for the site copy")
    ap.add_argument("--repack", action="store_true", help="rebuild the page from app/lab-data.json without rerunning")
    ap.add_argument("--out", type=Path, default=HERE / "app/index.html", help="where to write the page (the site copy: ../site/day10/index.html with --root ../)")
    a = ap.parse_args()
    app = HERE / "app"
    if a.repack:
        data = json.loads((app / "lab-data.json").read_text())
        data["bench"] = bench_entries(a.bench)              # verdicts are reread on every repack
        blob = json.dumps(data, separators=(",", ":"))
        (app / "lab-data.json").write_text(blob)
        write_page(app, blob, a.root, a.out); return
    import sim
    data = {
        "built": time.strftime("%Y-%m-%d"), "grid": [sim.NY, sim.NX], "dx": sim.DX, "seed": 42,
        "params": {k: getattr(sim, k) for k in ["STORMS_PER_YEAR", "STORM_MEAN_DEPTH_MM", "STORM_MEAN_DURATION_H",
                   "INFIL_BARE_M", "INFIL_SHRUB_M", "K_REF", "Q_REF", "M_SP", "K_SHRUB_FACTOR", "V_S", "V_S_SHRUB_GAIN", "D_BARE",
                   "D_SHRUB_GAIN", "VEG_COVER_MEAN", "DT_STEP"]},
        "scenarios": [run_scenario(k, l, f, a.years) for k, l, f in SCENARIOS],
        "bench": bench_entries(a.bench),
    }
    blob = json.dumps(data, separators=(",", ":"))
    (app / "lab-data.json").write_text(blob)
    write_page(app, blob, a.root, a.out)


def write_page(app, blob, root, out):
    page = (app / "template.html").read_text().replace("{{ROOT}}", root).replace("/*LAB_DATA*/null", blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"{out} {len(page) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
