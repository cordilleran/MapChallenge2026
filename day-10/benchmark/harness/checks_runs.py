"""Checks that need reruns of an entry (Fable review, sections 2B and 2C).

Each function takes the output folders of the relevant runs and returns values plus `fail`
(True, False, or None when it could not be computed). Thresholds are provisional until the
reference script and its faulty copies set them (tests/faults/run_fault_matrix.py).
"""
import csv, json
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

import checks_arrays
import routing

TOL = {  # provisional thresholds, each named in the review; revisited after the fault matrix
    "C1_K_rel": 0.10, "C3_share": 0.01, "C5_asym": 0.01, "C6_corr": 0.95,
    "C9_export_rel": 0.10, "C9_corr": 0.90, "B2_rho": -0.05,
}


def load(d):
    d = Path(d)
    if not (d / "z_final.npy").exists():
        return None
    tel = json.loads((d / "telemetry.json").read_text()) if (d / "telemetry.json").exists() else {}
    return {"z0": np.load(d / "z_initial.npy"), "z1": np.load(d / "z_final.npy"), "tel": tel, "dir": d}


def gross(r):
    return float(np.abs(r["z1"] - r["z0"]).sum() * r["tel"]["cell_size_m"] ** 2 / 2)


def _sigma2(z, dx):
    """Second moment of the downslope gradient profile in the centre half of the columns."""
    nx = z.shape[1]
    prof = z[:, nx // 4: 3 * nx // 4].mean(axis=1)
    g = np.clip(-np.diff(prof) / dx, 0, None)
    y = (np.arange(len(g)) + 0.5) * dx
    if g.sum() == 0:
        return None
    m = (g * y).sum() / g.sum()
    return float((g * (y - m) ** 2).sum() / g.sum())


def c1_scarp(bare, veg):
    out = {}
    for name, r in (("bare", bare), ("vegetated", veg)):
        if r is None:
            out[name] = None; continue
        dx, t = r["tel"]["cell_size_m"], float(r["tel"]["years_simulated"])
        s0, s1 = _sigma2(r["z0"], dx), _sigma2(r["z1"], dx)
        K = None if s0 is None or s1 is None else (s1 - s0) / (2 * t)
        dz = r["z1"] - r["z0"]
        out[name] = {"K_recovered_m2_per_yr": K, "net_over_gross": float(abs(dz.sum())) / max(float(np.abs(dz).sum()) / 2, 1e-30),
                     "changed": bool(np.abs(dz).max() > 1e-9)}
    claim = (bare or {}).get("tel", {}).get("creep_diffusivity_m2_per_yr")
    Kb = (out.get("bare") or {}).get("K_recovered_m2_per_yr")
    rel = None if not claim or Kb is None else abs(Kb / claim - 1)
    out["K_claimed_m2_per_yr"] = claim
    out["K_relative_error"] = rel
    out["vegetation_effect_on_creep"] = None if not out.get("vegetated") or Kb in (None, 0) or out["vegetated"]["K_recovered_m2_per_yr"] is None \
        else out["vegetated"]["K_recovered_m2_per_yr"] / Kb
    out["flag_K_outside_1e-4_1e-1"] = None if Kb is None else not (1e-4 <= Kb <= 1e-1)
    nochange = bare is not None and not out["bare"]["changed"]
    out["fail"] = None if bare is None else bool(nochange or (Kb is not None and Kb <= 0) or (rel is not None and rel > TOL["C1_K_rel"]))
    return out


def c2_ramp(r, break_row):
    if r is None:
        return {"fail": None}
    rows = (r["z1"] - r["z0"]).mean(axis=1)
    ny = len(rows)
    apron = rows[break_row + 1:-1]
    peak = int(np.argmax(apron)) + break_row + 1 if len(apron) else None
    first_third = break_row + 1 + (ny - break_row - 1) // 3
    ramp_net = float(rows[1:break_row].mean())
    fail = bool(apron.max() <= 0 or peak > first_third or ramp_net > 0)
    return {"row_mean_change_m": rows.round(6).tolist(), "break_row": break_row, "deposition_peak_row": peak,
            "peak_rows_after_break": None if peak is None else peak - break_row, "ramp_mean_change_m": ramp_net, "fail": fail}


def c3_basin(r, dry=None):
    """Nothing can leave a closed bowl, so the net change must be zero whatever the entry reports.
    Informative only if rain did something in the bowl: an entry that fills pits before routing
    treats the bowl as a lake, and then only creep acts."""
    if r is None:
        return {"fail": None}
    cell = r["tel"]["cell_size_m"] ** 2
    dz = r["z1"] - r["z0"]
    g = gross(r)
    net = float(dz.sum() * cell)
    exp = float(r["tel"].get("sediment_exported_m3") or 0.0)
    if g == 0:
        return {"gross_moved_m3": 0.0, "net_m3": net, "reported_export_m3": exp, "fail": None, "note": "nothing moved"}
    rain_effect = None if dry is None else float(np.abs((r["z1"] - r["z0"]) - (dry["z1"] - dry["z0"])).sum() * cell / 2) / g
    return {"gross_moved_m3": g, "net_m3": net, "net_share_of_gross": abs(net) / g, "reported_export_m3": exp,
            "rain_share_of_change": rain_effect, "informative_for_wash": None if rain_effect is None else rain_effect > 0.1,
            "export_share_of_gross": abs(exp) / g,
            "fail": bool(abs(net) / g > TOL["C3_share"] or abs(exp) / g > TOL["C3_share"])}


def c5_mirror(r):
    if r is None:
        return {"fail": None}
    dz = r["z1"] - r["z0"]
    n = float(np.linalg.norm(dz))
    a = float(np.linalg.norm(dz - dz[:, ::-1])) / n if n > 0 else None
    return {"asymmetry": a, "exact": None if a is None else a < 1e-6, "fail": None if a is None else a > TOL["C5_asym"]}


def c6_no_rain(r, K):
    if r is None:
        return {"fail": None}
    dx = r["tel"]["cell_size_m"]; t = float(r["tel"]["years_simulated"])
    dz = r["z1"] - r["z0"]
    pred = (K or 1.0) * t * checks_arrays.laplacian(r["z0"], dx)
    s = (slice(2, -2), slice(2, -2))
    a, b = dz[s].ravel(), pred[s].ravel()
    corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None
    linear = r["tel"].get("creep_diffusivity_m2_per_yr") is not None
    return {"corr_with_K_t_laplacian": corr, "claims_linear_creep": linear,
            "fail": None if corr is None else bool(linear and corr < TOL["C6_corr"])}


def c7_rain(base, rain2):
    if base is None or rain2 is None:
        return {"fail": None}
    g1, g2 = gross(base), gross(rain2)
    e = float(np.log(g2 / g1) / np.log(2)) if g1 > 0 and g2 > 0 else None
    return {"gross_rain1_m3": g1, "gross_rain2_m3": g2, "elasticity": e, "threshold_like": None if e is None else e > 1,
            "fail": None if e is None else e <= 0}


def c8_vegetation(veg0, veg1, veg2, dry0=None, dry1=None, dry2=None):
    """Wash must carry less off the slope as cover rises. Wash is separated from creep by
    subtracting the no-rain run at the same cover (dry*)."""
    if None in (veg0, veg1, veg2):
        return {"fail": None}
    def wash(r, d):
        # Net loss from the upper half of the slope that rain added: sediment carried away.
        # (Gross erosion is the wrong measure: patchy cover makes many small erosion and
        # deposition pairs, so gross reworking can rise with cover while yield falls.)
        dz = (r["z1"] - r["z0"]) - ((d["z1"] - d["z0"]) if d is not None else 0)
        up = dz[: dz.shape[0] // 2]
        return float(-up.sum() * r["tel"]["cell_size_m"] ** 2)
    g = [wash(veg0, dry0), wash(veg1, dry1), wash(veg2, dry2)]
    tot = [gross(veg0), gross(veg1), gross(veg2)]
    return {"upper_slope_wash_loss_by_veg_scale_0_1_2_m3": g, "total_moved_by_veg_scale_0_1_2_m3": tot,
            "separated_from_creep": dry0 is not None, "monotonic_falling": g[0] > g[1] > g[2],
            "fail": not (g[0] > g[1] > g[2])}


def c9_timestep(base, half):
    if base is None or half is None:
        return {"fail": None}
    e1 = float(base["tel"].get("sediment_exported_m3") or 0.0); e2 = float(half["tel"].get("sediment_exported_m3") or 0.0)
    d1, d2 = base["z1"] - base["z0"], half["z1"] - half["z0"]
    rel = abs(e2 - e1) / abs(e1) if e1 else None
    pk = abs((-d2.min()) - (-d1.min())) / max(-d1.min(), 1e-30)
    corr = float(np.corrcoef(d1.ravel(), d2.ravel())[0, 1]) if d1.std() > 0 and d2.std() > 0 else None
    return {"export_rel_change": rel, "peak_erosion_rel_change": float(pk), "dz_corr": corr,
            "dt_years": [base["tel"].get("dt_years"), half["tel"].get("dt_years")],
            "fail": bool((rel is not None and rel > TOL["C9_export_rel"]) or (corr is not None and corr < TOL["C9_corr"]))}


def b1_storms(d42, d43, tel):
    def read(d):
        p = Path(d) / "storms.csv"
        if not p.exists():
            return None
        rows = list(csv.DictReader(open(p)))
        return np.array([float(r["year"]) for r in rows]), np.array([float(r["depth_mm"]) for r in rows])
    a, b = read(d42), read(d43)
    if a is None:
        return {"fail": None, "note": "no storms.csv"}
    yrs, dep = a; span = float(tel.get("years_simulated") or (yrs.max() - yrs.min()) or 1)
    top = np.sort(dep)[::-1][: max(1, len(dep) // 10)].sum() / dep.sum() if dep.sum() > 0 else None
    cv = float(dep.std() / dep.mean()) if dep.mean() > 0 else None
    same = b is not None and len(b[1]) == len(dep) and np.array_equal(b[1], dep)
    return {"storms": len(dep), "storms_per_year": len(dep) / span, "mean_annual_rain_mm": float(dep.sum() / span),
            "depth_cv": cv, "top_tenth_share_of_rain": top, "same_for_seeds_42_43": same,
            "claimed_storm_count": tel.get("storm_count"), "claimed_mean_annual_rain_mm": tel.get("mean_annual_rain_mm"),
            "fail": bool(cv is None or cv < 1e-6 or same)}


def b2_vegetation(r):
    if r is None or not (r["dir"] / "vegetation.npy").exists():
        return {"fail": None, "note": "no vegetation.npy"}
    cover = np.load(r["dir"] / "vegetation.npy")
    dx = r["tel"]["cell_size_m"]
    ro = routing.route(r["z0"], r["tel"].get("open_boundaries") or [], dx)
    AS = np.log10(ro["area"] * np.maximum(ro["slope"], 1e-6))
    ero = np.clip(r["z0"] - r["z1"], 0, None)
    m = ~ro["outlets"]
    edges = np.quantile(AS[m], np.linspace(0, 1, 11))
    rhos = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        k = m & (AS >= lo) & (AS <= hi)
        if k.sum() > 30 and np.ptp(cover[k]) > 0 and np.ptp(ero[k]) > 0:
            rhos.append(float(spearmanr(cover[k], ero[k]).statistic))
    med = float(np.median(rhos)) if rhos else None
    return {"rho_by_AS_bin": rhos, "median_rho": med, "cover_mean": float(cover.mean()),
            "cover_share_over_half": float((cover > 0.5).mean()),
            "fail": None if med is None else med > TOL["B2_rho"]}


def crest_balance(bare, dry):
    """B11 descriptor for C4: on the low-area cells of the hillslope, how much wash moved against creep,
    and the curvature signature of each alone. Never fails."""
    if bare is None or dry is None:
        return {"fail": None}
    z0, dx = bare["z0"], bare["tel"]["cell_size_m"]
    r = routing.route(z0, bare["tel"].get("open_boundaries") or [], dx)
    inter = ~r["outlets"]; A = r["area"]
    lo = inter & (A <= np.quantile(A[inter], 0.3))
    curv = checks_arrays.laplacian(z0, dx)
    creep = dry["z1"] - dry["z0"]
    wash = (bare["z1"] - bare["z0"]) - creep
    def rho(x):
        return None if np.ptp(x[lo]) == 0 else float(spearmanr(curv[lo], x[lo]).statistic)
    mc, mw = float(np.abs(creep[lo]).mean()), float(np.abs(wash[lo]).mean())
    return {"rho_creep_alone": rho(creep), "rho_wash_alone": rho(wash), "mean_abs_creep_m": mc, "mean_abs_wash_m": mw,
            "wash_to_creep": mw / mc if mc > 0 else None}
