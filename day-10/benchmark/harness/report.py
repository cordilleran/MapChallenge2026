"""Turn RUNS_DIR/*/result_v2.json into the report's generated parts.

Usage: report.py RUNS_DIR REPORT_DIR [--fault-matrix FILE]

Writes REPORT_DIR/_gen/*.md and REPORT_DIR/figures/*.png, and the blind key (with the
random seed that drew it) to RUNS_DIR/blind_key.json, outside the report. Every number
comes from the result files; nothing is typed by hand.
"""
import argparse, json, secrets, shutil
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, TwoSlopeNorm

INK, MUTED = "#222222", "#6b6b6b"


def yes(v):
    return "yes" if v is True else ("no" if v is False else "–")


def fmt(v, nd=3):
    if v is None:
        return "–"
    if isinstance(v, bool):
        return yes(v)
    if isinstance(v, float):
        return f"{v:.{nd}g}"
    return str(v)


def mark(text, failed):
    return f"**{text} ✗**" if failed is True else text


def g(r, *path):
    for p in path:
        if not isinstance(r, dict):
            return None
        r = r.get(p)
    return r


def blind_labels(results, runs_dir):
    """A fresh random order per report, never the sorted one; the seed is kept with the key."""
    seed = secrets.randbits(32)
    rng = np.random.default_rng(seed)
    order = list(range(len(results)))
    while len(order) > 1 and order == sorted(order):
        order = list(rng.permutation(len(results)))
    key = {}
    for lab, idx in zip("ABCDEFGHIJ", order):
        results[idx]["label"] = f"Entry {lab}"; key[f"Entry {lab}"] = results[idx]["cell"]
    (runs_dir / "blind_key.json").write_text(json.dumps({"seed": seed, "key": key}, indent=1))


def common_figure(results, runs_dir, dest):
    """Row 1: hillshade. Row 2: change in mm/yr on ONE scale shared by all entries.
    Row 3: change in m, each entry on its own scale (shape, not size)."""
    ok = [r for r in results if (runs_dir / r["cell"] / "eval2" / "d42a" / "z_final.npy").exists()]
    if not ok:
        return False
    data = []
    for r in ok:
        d = runs_dir / r["cell"] / "eval2" / "d42a"
        z0, z1 = np.load(d / "z_initial.npy"), np.load(d / "z_final.npy")
        yrs = float(r["telemetry"]["years_simulated"])
        data.append((r, z0, z1, (z1 - z0) / yrs * 1000))
    shared = max(float(np.nanpercentile(np.abs(rate), 99.5)) for *_, rate in data) or 1e-6
    fig, axes = plt.subplots(3, len(ok), figsize=(3.4 * len(ok), 10), squeeze=False)
    for i, (r, z0, z1, rate) in enumerate(data):
        dx = float(r["telemetry"]["cell_size_m"])
        axes[0, i].imshow(LightSource(315, 40).hillshade(z1, dx=dx, dy=dx, vert_exag=2), cmap="gray")
        axes[0, i].set_title(r["label"], color=INK, fontsize=12)
        im = axes[1, i].imshow(rate, cmap="BrBG", norm=TwoSlopeNorm(0, -shared, shared))
        dz = z1 - z0; lim = float(np.nanpercentile(np.abs(dz), 99.5)) or 1e-6
        im2 = axes[2, i].imshow(dz, cmap="BrBG", norm=TwoSlopeNorm(0, -lim, lim))
        fig.colorbar(im2, ax=axes[2, i], fraction=0.046, pad=0.03).set_label("m", color=MUTED)
        for ax in axes[:, i]:
            ax.set_xticks([]); ax.set_yticks([])
        axes[0, i].set_xlabel(f"{z0.shape[0]}×{z0.shape[1]} cells of {dx:g} m, {r['telemetry']['years_simulated']:.0f} yr", color=MUTED, fontsize=8)
    fig.colorbar(im, ax=list(axes[1, :]), fraction=0.02, pad=0.01).set_label("mm per year, shared scale", color=MUTED)
    axes[0, 0].set_ylabel("final surface, hillshade", color=MUTED)
    axes[1, 0].set_ylabel("rate of change, shared scale", color=MUTED)
    axes[2, 0].set_ylabel("change, each entry's own scale", color=MUTED)
    fig.savefig(dest, dpi=110, bbox_inches="tight"); plt.close(fig)
    return True


ROWS = [  # (section, label, getter, fail getter)
    ("Runs", "Ran, seed 42 (exit 0)", lambda r: yes(g(r, "runs", "d42a", "exit") == 0), lambda r: g(r, "runs", "d42a", "exit") not in (0, None)),
    ("Runs", "Run time in container (s)", lambda r: fmt(g(r, "runs", "d42a", "seconds")), None),
    ("Runs", "Prompt contract", lambda r: r.get("contract", "–"), None),
    ("Runs", "Same seed, same result", lambda r: yes(r.get("deterministic")), lambda r: r.get("deterministic") is False),
    ("Runs", "Other seed, other result", lambda r: yes(r.get("seed_changes_result")), lambda r: r.get("seed_changes_result") is False),
    ("Runs", "No NaN or infinity", lambda r: yes(r.get("finite")), lambda r: r.get("finite") is False),
    ("Runs", "Bookkeeping agrees with itself (%)", lambda r: fmt(r.get("bookkeeping_self_consistent_pct")), None),
    ("Surface", "Grid and cell size", lambda r: f"{'×'.join(map(str, g(r, 'telemetry', 'grid_shape') or []))} × {fmt(g(r, 'telemetry', 'cell_size_m'))} m", None),
    ("Surface", "Initial relief (m)", lambda r: fmt(g(r, "A_default", "A1_rates", "initial_relief_m")), None),
    ("Surface", "Years simulated", lambda r: fmt(g(r, "A_default", "A1_rates", "years")), None),
    ("A1 rates", "Mean lowering (mm/yr)", lambda r: fmt(g(r, "A_default", "A1_rates", "mean_lowering_mm_per_yr")), None),
    ("A1 rates", "Peak erosion (mm/yr)", lambda r: fmt(g(r, "A_default", "A1_rates", "peak_erosion_mm_per_yr")), None),
    ("A1 rates", "Peak erosion ÷ initial relief", lambda r: fmt(g(r, "A_default", "A1_rates", "peak_erosion_share_of_relief")), lambda r: g(r, "A_default", "A1_rates", "flag_deep")),
    ("A2", "Deposits start lower than erosion (m)", lambda r: fmt(g(r, "A_default", "A2_downslope", "drop_m")), lambda r: g(r, "A_default", "A2_downslope", "fail")),
    ("A3", "Implied flux running uphill (share)", lambda r: fmt(g(r, "A_default", "A3_implied_flux", "uphill_share")), None),
    ("A4", "Erosion vs area × slope, main flow lines (ρ)", lambda r: fmt(g(r, "A_default", "A4_slope_area", "rho_erosion_vs_AS_high_area")), lambda r: g(r, "A_default", "A4_slope_area", "fail")),
    ("A4", "Change vs curvature near divides (ρ)", lambda r: fmt(g(r, "A_default", "A4_slope_area", "rho_change_vs_curvature_low_area")), None),
    ("A5", "Capacity fall predicts deposition (AUC)", lambda r: fmt(g(r, "A_default", "A5_capacity_fall", "best_auc")), lambda r: g(r, "A_default", "A5_capacity_fall", "fail")),
    ("A6", "Two-cell 'checkerboard' share", lambda r: fmt(g(r, "A_default", "A6_artefacts", "two_cell_power_share")), None),
    ("A6", "Across-slope banding share", lambda r: fmt(g(r, "A_default", "A6_artefacts", "column_mean_share")), None),
    ("A6", "Closed pits at the end (cells)", lambda r: fmt(g(r, "A_default", "A6_artefacts", "pit_cells_final")), None),
    ("Map", "No web addresses in the page", lambda r: yes(not r["html"]["external_refs"]) if r.get("html") else "–", lambda r: bool(r.get("html") and r["html"]["external_refs"])),
    ("Map", "Page size (KB)", lambda r: fmt(g(r, "html", "html_kb")), None),
]
V2_ROWS = [
    ("C1", "Creep coefficient: recovered ÷ claimed", lambda r: fmt(None if not g(r, "C1_scarp", "K_claimed_m2_per_yr") or g(r, "C1_scarp", "bare", "K_recovered_m2_per_yr") is None else g(r, "C1_scarp", "bare", "K_recovered_m2_per_yr") / g(r, "C1_scarp", "K_claimed_m2_per_yr")), lambda r: g(r, "C1_scarp", "fail")),
    ("C2", "Ramp: deposition peak, rows after the break", lambda r: fmt(g(r, "C2_ramp", "peak_rows_after_break")), lambda r: g(r, "C2_ramp", "fail")),
    ("C3", "Closed bowl: net change ÷ moved", lambda r: fmt(g(r, "C3_basin", "net_share_of_gross")) + ("" if g(r, "C3_basin", "informative_for_wash") else " (rain did nothing)"), lambda r: g(r, "C3_basin", "fail")),
    ("C5", "Mirror asymmetry", lambda r: fmt(g(r, "C5_mirror", "asymmetry")), lambda r: g(r, "C5_mirror", "fail")),
    ("C6", "No rain: matches creep (r)", lambda r: fmt(g(r, "C6_no_rain", "corr_with_K_t_laplacian")), lambda r: g(r, "C6_no_rain", "fail")),
    ("C7", "Rain elasticity", lambda r: fmt(g(r, "C7_rain", "elasticity")), lambda r: g(r, "C7_rain", "fail")),
    ("C8", "Wash falls as cover rises", lambda r: yes(g(r, "C8_vegetation", "monotonic_falling")), lambda r: g(r, "C8_vegetation", "fail")),
    ("C9", "Half step: export change", lambda r: fmt(g(r, "C9_timestep", "export_rel_change")), lambda r: g(r, "C9_timestep", "fail")),
    ("B1", "Storms per year; depth CV", lambda r: f"{fmt(g(r, 'B1_storms', 'storms_per_year'))}; {fmt(g(r, 'B1_storms', 'depth_cv'))}", lambda r: g(r, "B1_storms", "fail")),
    ("B2", "Cover vs erosion (median ρ)", lambda r: fmt(g(r, "B2_vegetation", "median_rho")), lambda r: g(r, "B2_vegetation", "fail")),
]


def check_table(results, names):
    any_v2 = any(r.get("contract") == "v2" for r in results)
    rows = ROWS + (V2_ROWS if any_v2 else [])
    L = ["| Group | Check | " + " | ".join(names(r) for r in results) + " |", "| :--- | :--- |" + " ---: |" * len(results)]
    for sec, name, f, fail in rows:
        L.append(f"| {sec} | {name} | " + " | ".join(mark(f(r), fail(r) if fail else None) for r in results) + " |")
    return "\n".join(L) + "\n"


def main(runs_dir, rep, fault_matrix=None):
    results = [json.loads(p.read_text()) for p in sorted(runs_dir.glob("*/result_v2.json"))]
    gen, figs = rep / "_gen", rep / "figures"
    for d in (gen, figs, rep / "maps"):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    blind_labels(results, runs_dir)
    by_label = sorted(results, key=lambda r: r["label"])

    for r in results:
        ev = runs_dir / r["cell"] / "eval2"
        lab = r["label"][-1]
        for src, name in ((ev / "d42a" / "map.png", "map"), (ev / "map_html.png", "html")):
            if src.exists():
                shutil.copy2(src, figs / f"{r['cell']}_{name}.png"); shutil.copy2(src, figs / f"blind_{lab}_{name}.png")
        if (ev / "d42a" / "map.html").exists():
            shutil.copy2(ev / "d42a" / "map.html", rep / "maps" / f"{r['cell']}.html")
            shutil.copy2(ev / "d42a" / "map.html", rep / "maps" / f"blind_{lab}.html")

    L = ["| Run | Tool | Model | Prompt | Wall time (min) | Tool calls | sim.py lines |", "| :--- | :--- | :--- | :--- | ---: | ---: | ---: |"]
    for r in results:
        L.append(f"| {r['cell']} | {r.get('harness')} | {r.get('model')} | {r.get('prompt', 'python_prompt.md')} | "
                 f"{(r.get('wall_s') or 0) / 60:.1f} | {fmt(r.get('tool_calls'))} | {fmt(r.get('sim_py_lines'))} |")
    (gen / "runs.md").write_text("\n".join(L) + "\n")
    (gen / "checks.md").write_text(check_table(results, lambda r: r["cell"]))

    L = []
    for r in results:
        p = runs_dir / r["cell"] / "final_reply.md"; txt = p.read_text() if p.exists() else ""
        L += [f"### {r['cell']}", "", "::: {.callout-note collapse=\"true\"}", f"## The agent's reply ({len(txt)} characters)", "",
              txt.replace("\n#", "\n####") or "_No reply captured._", ":::", ""]
    (gen / "replies.md").write_text("\n".join(L) + "\n")

    common_figure(by_label, runs_dir, figs / "blind_common.png")
    L = []
    for r in by_label:
        lab = r["label"][-1]
        L += [f"## {r['label']}", "", f"[Open the interactive map](maps/blind_{lab}.html){{target=\"_blank\"}}", ""]
        if (figs / f"blind_{lab}_html.png").exists():
            L += [f"![{r['label']}: the interactive map as it first loads](figures/blind_{lab}_html.png)", ""]
        if (figs / f"blind_{lab}_map.png").exists():
            L += [f"![{r['label']}: the static map it saved](figures/blind_{lab}_map.png)", ""]
    (gen / "blind.md").write_text("\n".join(L) + "\n")
    L = ["| Entry | Landforms plausible (0-5) | Dryland processes shown (0-5) | Cartography (0-5) | Teaching value (0-5) | Note |",
         "| :--- | :---: | :---: | :---: | :---: | :--- |"] + [f"| {r['label']} |  |  |  |  |  |" for r in by_label]
    (gen / "score_sheet.md").write_text("\n".join(L) + "\n")
    if fault_matrix and Path(fault_matrix).exists():
        shutil.copy2(fault_matrix, gen / "fault_matrix.md")
    print("report parts written for", len(results), "runs")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("runs", type=Path); ap.add_argument("report", type=Path)
    ap.add_argument("--fault-matrix")
    a = ap.parse_args()
    main(a.runs, a.report, a.fault_matrix)
