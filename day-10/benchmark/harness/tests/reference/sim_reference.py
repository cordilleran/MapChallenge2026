"""Reference sim.py for the version 2 contract: a TEST FIXTURE, not a benchmark entry.

It exists to prove that each harness check can fail: `make_faults.py` writes seven copies
with one fault each (FAULT below), and every check must catch its fault while this file
passes them all. It is deliberately plain, not a model answer: one-step-per-period storm
runoff, D8 on a pit-filled surface, erosion-deposition with a deposition length that grows
with discharge (in the spirit of Davy and Lague 2009), linear creep, a fixed base-level row.

    python3 sim_reference.py --seed 42 --out OUT [--z0 F] [--rain-scale F] [--veg-scale F] [--dt-scale F] [--no-map]
"""
import argparse, base64, csv, heapq, io, json, os, time

import numpy as np

FAULT = None   # None, or one of F1..F7 (see make_faults.py)
VARIANT = None # None, or V1..V3: correct but different models that must pass every check (B11)

NY, NX, DX = 100, 100, 5.0
YEARS, DT = 2000.0, 10.0
STORMS_PER_YR, STORM_MEAN_MM, STORM_SHAPE = 6.0, 12.0, 0.8
INFIL_BARE_MM, INFIL_VEG_MM = 8.0, 20.0
KE = 1.0e-2            # erosion coefficient; set so wash moves about as much as creep (calibration, faults-v1)
ELL0 = 0.02            # deposition length per unit discharge (m per m^2)
KC = 0.01              # creep diffusivity on bare ground, m^2/yr
VEG_CREEP = 0.5        # cover raises creep by up to 50 % (bioturbation)
VEG_ERODE = 0.8        # cover cuts wash erosion by up to 80 %
WASH_THRESHOLD = 0.0   # wash acts only on sqrt(q)*S above this (detachment threshold)
if VARIANT == "V1":   # wash ten times stronger: wash dominates creep everywhere
    KE *= 10
if VARIANT == "V2":   # creep five times weaker
    KC *= 0.2
if VARIANT == "V3":   # a detachment threshold, with wash five times stronger above it
    KE *= 5; WASH_THRESHOLD = 0.3     # about the 30th percentile of sqrt(q)*S on the harness hillslope
NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]



def initial_surface(rng):
    y = np.arange(NY)[:, None] * DX
    z = 60.0 * (1 - y / ((NY - 1) * DX)) ** 1.3 + np.zeros((1, NX))
    return z + rng.normal(0, 0.05, (NY, NX))


def vegetation(rng):
    f = rng.normal(size=(NY, NX))
    for _ in range(6):                                    # smooth into patches
        f = (f + np.roll(f, 1, 0) + np.roll(f, -1, 0) + np.roll(f, 1, 1) + np.roll(f, -1, 1)) / 5
    f = (f - f.mean()) / f.std()
    return np.clip(0.5 + 0.6 * f, 0, 1)


def storms(rng):
    n = rng.poisson(STORMS_PER_YR * YEARS)
    t = np.sort(rng.uniform(0, YEARS, n))
    d = rng.gamma(STORM_SHAPE, STORM_MEAN_MM / STORM_SHAPE, n)
    if FAULT == "F4":                                     # steady rain: every storm the same, evenly spaced
        t = np.linspace(0, YEARS, n, endpoint=False); d = np.full(n, STORM_MEAN_MM)
    return t, d


def fill_and_route(z):
    """Priority flood from the bottom row, then D8 receivers on the filled surface."""
    f = z.copy(); done = np.zeros(z.shape, bool)
    pq = [(f[NY - 1, j], NY - 1, j) for j in range(NX)]; heapq.heapify(pq); done[NY - 1, :] = True
    while pq:
        h, i, j = heapq.heappop(pq)
        for di, dj in NB:
            a, b = i + di, j + dj
            if 0 <= a < NY and 0 <= b < NX and not done[a, b]:
                done[a, b] = True
                if f[a, b] <= h + 1e-6:
                    f[a, b] = h + 1e-6
                heapq.heappush(pq, (f[a, b], a, b))
    idx = np.arange(NY * NX).reshape(NY, NX); fp = np.pad(f, 1, constant_values=np.inf)
    best = np.zeros((NY, NX)); score = np.zeros((NY, NX)); rec = -np.ones((NY, NX), int)
    for di, dj in NB:
        sl = (f - fp[1 + di:1 + di + NY, 1 + dj:1 + dj + NX]) / (DX * np.hypot(di, dj))
        sc = sl * (1.3 if FAULT == "F7" and dj == -1 else 1.0)    # F7: routing that favours one side
        better = sc > score
        score = np.where(better, sc, score); best = np.where(better, sl, best)
        rec = np.where(better, np.roll(np.roll(idx, -di, 0), -dj, 1), rec)
    rec[NY - 1, :] = -1; best[NY - 1, :] = 0.0
    S = best
    return f, rec, np.maximum(S, 0)


def wash(z, cover, runoff_m, rng, frac=1.0):
    """Erosion and deposition for `frac` of one period: the same discharge for a shorter time.
    Returns new z and the volume that left."""
    f, rec, S = fill_and_route(z)
    order = np.argsort(-f.ravel(), kind="stable")
    A = np.full(z.size, DX * DX)
    for c in order:
        r = rec.flat[c]
        if r >= 0:
            A[r] += A[c]
    q = A * runoff_m.ravel() / DX                         # m^2 per period
    pit = (f - z).ravel() > 1e-5
    erode_k = KE * (1 - (0 if FAULT == "F3" else VEG_ERODE) * cover.ravel())
    E = erode_k * np.maximum(np.sqrt(q) * S.ravel() - WASH_THRESHOLD, 0.0) * frac   # m in this part of the period
    E[pit] = 0.0
    E[(NY - 1) * NX:] = 0.0                               # base-level row is fixed
    Qs = np.zeros(z.size); dv = np.zeros(z.size); out = 0.0
    for c in order:
        r = rec.flat[c]
        if c >= (NY - 1) * NX:                            # outlet row: everything arriving leaves
            out += Qs[c]; continue
        load = Qs[c] + E[c] * DX * DX
        if FAULT == "F1":                                 # sediment deleted: nothing carried, nothing dropped
            dv[c] -= E[c] * DX * DX; continue
        if pit[c]:
            dep = load
        else:
            ell = max(ELL0 * q[c], 1e-9)
            dep = load * (1 - 1 / (1 + DX / ell))
        dv[c] += dep - E[c] * DX * DX
        if r >= 0:
            Qs[r] += load - dep
    if FAULT == "F5":                                     # deposits placed at random: same volumes, shuffled cells
        d = np.clip(dv, 0, None); e = np.clip(dv, None, 0)
        dv = e + rng.permutation(d)
    return z + (dv / (DX * DX)).reshape(z.shape), out


def creep(z, cover, dt):
    k = (0.0 if FAULT == "F2" else KC) * (1 + (0 if FAULT == "F3" else VEG_CREEP) * cover)
    if k.max() == 0:
        return z, 0.0
    n = int(np.ceil(dt / (0.9 * DX * DX / (4 * k.max())))); h = dt / n; out = 0.0
    for _ in range(n):
        kx = 0.5 * (k[:, 1:] + k[:, :-1]); ky = 0.5 * (k[1:, :] + k[:-1, :])
        fx = -kx * np.diff(z, axis=1) / DX; fy = -ky * np.diff(z, axis=0) / DX     # m^2/yr
        div = np.zeros_like(z)
        div[:, :-1] += fx; div[:, 1:] -= fx; div[:-1, :] += fy; div[1:, :] -= fy
        dz = -h * div / DX
        out += dz[-1, :].sum() * DX * DX                  # what reached the fixed row leaves
        dz[-1, :] = 0.0
        z = z + dz
    return z, out


def write_maps(o, z0, z):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, TwoSlopeNorm
    dz = z - z0; lim = float(np.abs(dz).max()) or 1e-6
    fig, ax = plt.subplots(1, 2, figsize=(9, 4.2))
    ax[0].imshow(LightSource(315, 40).hillshade(z, dx=DX, dy=DX), cmap="gray"); ax[0].set_title("Final surface")
    ax[1].imshow(dz, cmap="BrBG", norm=TwoSlopeNorm(0, -lim, lim)); ax[1].set_title("Change (m)")
    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    fig.savefig(o / "map.png", dpi=90); buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=90); plt.close(fig)
    img = base64.b64encode(buf.getvalue()).decode()
    (o / "map.html").write_text(f"<!doctype html><meta charset=utf-8><title>Reference</title><p>Reference fixture, not a teaching map.</p>"
                                f"<label>Show <input type=range min=0 max=1 value=1 data-bench=layer oninput=\"i.style.opacity=this.value\"></label>"
                                f"<img id=i src='data:image/png;base64,{img}'>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--z0"); ap.add_argument("--rain-scale", type=float, default=1.0)
    ap.add_argument("--veg-scale", type=float, default=1.0); ap.add_argument("--dt-scale", type=float, default=1.0)
    ap.add_argument("--no-map", action="store_true")
    a = ap.parse_args(); t0 = time.time()
    o = __import__("pathlib").Path(a.out); o.mkdir(parents=True, exist_ok=True)
    s_rough, s_veg, s_storm, s_fault = np.random.SeedSequence(a.seed).spawn(4)
    z = np.load(a.z0).astype(float) if a.z0 else initial_surface(np.random.default_rng(s_rough))
    assert z.shape == (NY, NX), f"--z0 must be {NY}x{NX}"
    cover = np.clip(vegetation(np.random.default_rng(s_veg)) * a.veg_scale, 0, 1)
    st, sd = storms(np.random.default_rng(s_storm))
    frng = np.random.default_rng(s_fault)
    z0 = z.copy(); exported = 0.0
    nsub = max(1, int(round(1 / a.dt_scale)))
    edges = np.arange(0, YEARS + DT / 2, DT)
    infil = INFIL_BARE_MM + INFIL_VEG_MM * (0 * cover if FAULT == "F3" else cover)
    for k in range(len(edges) - 1):
        sel = (st >= edges[k]) & (st < edges[k + 1])
        depths = sd[sel] * a.rain_scale
        runoff = np.maximum(depths[:, None, None] - infil[None], 0).sum(axis=0) / 1000.0   # m this period
        for _ in range(nsub):
            if runoff.max() > 0:
                if FAULT == "F6":                         # step-dependent storms: the step's runoff is lumped,
                    z, out = wash(z, cover, runoff / nsub, frng)   # so a shorter step means weaker flow
                else:
                    z, out = wash(z, cover, runoff, frng, 1.0 / nsub)
                exported += out
            z, out = creep(z, cover, DT / nsub); exported += out
    if FAULT == "F1":
        exported = -float((z - z0).sum() * DX * DX)       # the remainder, so the books "balance"
    dV = float((z - z0).sum() * DX * DX)
    gross = float(np.abs(z - z0).sum() * DX * DX / 2) or 1e-12
    np.save(o / "z_initial.npy", z0); np.save(o / "z_final.npy", z); np.save(o / "vegetation.npy", cover)
    with open(o / "storms.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["year", "depth_mm"]); w.writerows(zip(np.round(st, 4), np.round(sd, 3)))
    tel = {"seed": a.seed, "grid_shape": [NY, NX], "cell_size_m": DX, "years_simulated": YEARS,
           "timesteps": (len(edges) - 1) * nsub, "dt_years": DT / nsub, "storm_count": int(len(st)),
           "mean_annual_rain_mm": float(sd.sum() / YEARS), "creep_diffusivity_m2_per_yr": 0.0 if FAULT == "F2" else KC,
           "open_boundaries": ["bottom"], "sediment_exported_m3": float(exported), "uplift_or_baselevel_m3": 0.0,
           "mass_balance_error_pct": abs(dV + exported) / gross * 100, "fault": FAULT, "seconds": round(time.time() - t0, 1)}
    (o / "telemetry.json").write_text(json.dumps(tel, indent=1))
    if not a.no_map:
        write_maps(o, z0, z)


if __name__ == "__main__":
    main()
