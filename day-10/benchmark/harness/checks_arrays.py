"""Group A checks (Fable review, section 2A): computed from z_initial, z_final and telemetry only.

Each check returns values, and `fail` (True/False) where the review defines a failure.
Thresholds are provisional until the reference script and its faulty copies set them
(tests/faults/). The harness routes flow itself (routing.py) on z_initial.

Usage as a script: checks_arrays.py OUTDIR  (prints the JSON)
"""
import json, sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

import routing

# Exponent pairs (m, n) for the capacity proxy T = A^m S^n in A5. A choice, not a standard.
# Only the ratio m/n changes the ranking (T^k ranks like T), so the pairs differ in ratio.
CAPACITY_PAIRS = [(0.5, 1.0), (1.0, 1.0), (1.5, 1.0)]


def _auc(score, label):
    """Area under the ROC curve from ranks (Mann-Whitney); 0.5 is no skill."""
    label = label.astype(bool)
    n1, n0 = label.sum(), (~label).sum()
    if n1 == 0 or n0 == 0:
        return None
    r = rankdata(score)
    return float((r[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _spearman(a, b):
    if len(a) < 10 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return float(spearmanr(a, b).statistic)


def laplacian(z, dx):
    p = np.pad(z, 1, mode="edge")
    return (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] - 4 * z) / dx ** 2


def run(z0, z1, tel, years=None):
    dx = float(tel["cell_size_m"]); cell = dx * dx
    years = float(years or tel["years_simulated"])
    dz = z1 - z0
    gross = float(np.abs(dz).sum() * cell / 2)
    r = routing.route(z0, tel.get("open_boundaries") or [], dx)
    A, S = r["area"], np.maximum(r["slope"], 1e-6)
    interior = ~r["outlets"]
    out = {}

    # A1 rates
    relief = float(z0.max() - z0.min())
    exported = float(tel.get("sediment_exported_m3") or 0.0)
    out["A1_rates"] = {
        "years": years,
        "mean_lowering_mm_per_yr": exported / (z0.size * cell) / years * 1000,
        "mean_surface_change_mm_per_yr": float(dz.mean()) / years * 1000,
        "peak_erosion_mm_per_yr": float(max(-dz.min(), 0)) / years * 1000,
        "peak_erosion_share_of_relief": float(max(-dz.min(), 0)) / relief if relief > 0 else None,
        "initial_relief_m": relief,
    }
    out["A1_rates"]["flag_deep"] = bool((out["A1_rates"]["peak_erosion_share_of_relief"] or 0) > 0.25)

    # A2 downslope transfer: where did eroded material start, where did deposits land
    ero, dep = np.clip(-dz, 0, None), np.clip(dz, 0, None)
    ze = float((z0 * ero).sum() / ero.sum()) if ero.sum() > 0 else None
    zd = float((z0 * dep).sum() / dep.sum()) if dep.sum() > 0 else None
    out["A2_downslope"] = {"mean_z0_of_erosion_m": ze, "mean_z0_of_deposition_m": zd,
                           "drop_m": None if ze is None or zd is None else ze - zd,
                           "fail": None if ze is None or zd is None else zd >= ze}

    # A3 implied flux: volume lost minus volume gained upstream of each cell (D8 on z_initial)
    qs = routing.accumulate_d8(r["rec"], r["filled"], -dz * cell)
    neg = float(np.clip(-qs, 0, None).sum()); tot = float(np.abs(qs).sum())
    out["A3_implied_flux"] = {"uphill_share": neg / tot if tot > 0 else None,
                              "min_flux_share_of_gross": float(qs.min()) / gross if gross > 0 else None}

    # A4 slope-area signature
    hi = interior & (A >= np.quantile(A[interior], 0.9))
    lo = interior & (A <= np.quantile(A[interior], 0.3))
    curv = laplacian(z0, dx)
    rho_hi = _spearman((A * S)[hi], ero[hi])
    rho_lo = _spearman(curv[lo], dz[lo])
    # B11: only the high-area half can fail. The low-area half is a descriptor: its sign says whether
    # creep (positive) or wash (negative) shapes the low-area cells, a modelling choice, not an error
    # (review 261112-c4-a4-check-review: every entry's creep alone gives +0.96, its wash alone -0.5 to -0.66).
    out["A4_slope_area"] = {"rho_erosion_vs_AS_high_area": rho_hi,
                            "rho_change_vs_curvature_low_area": rho_lo,
                            "low_area_shaped_by": None if rho_lo is None else ("creep" if rho_lo > 0 else "wash"),
                            "fail": rho_hi is not None and rho_hi <= 0}

    # A5 deposition where capacity falls: drop in A^m S^n from the largest donor to the cell
    rec = r["rec"]; ny, nx = z0.shape
    has_donor = np.zeros(z0.size, bool); np.put(has_donor, rec[rec >= 0], True)
    aucs = {}
    for m, n in CAPACITY_PAIRS:
        T = (A ** m * S ** n).ravel()
        tmax = np.full(z0.size, -np.inf)
        donors = np.nonzero(rec >= 0)[0]
        np.maximum.at(tmax, rec[donors], T[donors])
        keep = has_donor & interior.ravel()
        fall = np.log10(np.maximum(tmax[keep], 1e-30)) - np.log10(np.maximum(T[keep], 1e-30))
        aucs[f"{m:g},{n:g}"] = _auc(fall, (dz.ravel() > 1e-3)[keep])
    vals = [v for v in aucs.values() if v is not None]
    out["A5_capacity_fall"] = {"auc_by_exponents": aucs, "best_auc": max(vals) if vals else None,
                               "fail": bool(vals) and max(vals) <= 0.5}

    # A6 numerical artefacts
    d = dz - dz.mean()
    P = np.abs(np.fft.fft2(d)) ** 2
    fy, fx = np.meshgrid(np.fft.fftfreq(ny), np.fft.fftfreq(nx), indexing="ij")
    var = float((d ** 2).sum()) or 1.0
    pits0 = routing.fill(z0, routing.outlet_mask(z0.shape, tel.get("open_boundaries")), eps=0)[0] - z0
    pits1 = routing.fill(z1, routing.outlet_mask(z1.shape, tel.get("open_boundaries")), eps=0)[0] - z1
    out["A6_artefacts"] = {
        "two_cell_power_share": float(P[np.maximum(abs(fy), abs(fx)) >= 0.4].sum() / P.sum()) if P.sum() > 0 else None,
        "row_mean_share": float(ny * nx * d.mean(axis=1).var() / var),
        "column_mean_share": float(ny * nx * d.mean(axis=0).var() / var),
        "pit_cells_initial": int((pits0 > 1e-6).sum()), "pit_cells_final": int((pits1 > 1e-6).sum()),
        "pit_volume_final_m3": float(pits1.sum() * cell),
    }
    sig = {"logA": np.log10(A[interior]).astype(np.float32), "logS": np.log10(S[interior]).astype(np.float32),
           "dz": dz[interior].astype(np.float32), "curv": curv[interior].astype(np.float32)}
    return out, sig


def run_dir(outdir):
    d = Path(outdir)
    tel = json.loads((d / "telemetry.json").read_text())
    return run(np.load(d / "z_initial.npy"), np.load(d / "z_final.npy"), tel)


if __name__ == "__main__":
    res, _ = run_dir(sys.argv[1])
    print(json.dumps(res, indent=1, default=float))
