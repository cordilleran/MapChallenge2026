"""Day 14, step 2: a thin-film (lubrication) model of the last of the mud draining, on a patch of the tub floor.

Why: at 1:1 the photo shows flat slabs of mud with a lace of thin lanes between them, 1-5 mm across. Landlab's
stream-power channels cannot make that; the mud's yield stress and surface tension do (Fable 5.2, second consult).

Model (one fluid: wet mud slurry of thickness h over the enamel bed b; Bingham rheology):
    dh/dt + div q = 0
    p   = rho g (h + b) - gamma lap(h) - Pi(h)                  hydrostatic + capillary + disjoining pressure
    G   = grad p                                                driving gradient (gravity enters through b)
    Y   = max(h - tau_y / |G|, 0)                               yielded depth (above Y the mud moves as a plug)
    q   = -[Y^2 (3h - Y) / (6 mu)] G                            Bingham lubrication flux (Newtonian when tau_y = 0)
    Pi  = kappa [(h*/h)^3 - (h*/h)^2],  kappa = 2 gamma (1 - cos theta) / h*
The disjoining pressure keeps a precursor film h* (20 um) on "bare" enamel and sets a contact angle theta. At a
0.25 mm grid this is a numerical device, not resolved molecular physics.

Numerics: fluxes on cell faces (explicit), stabilised by implicit constant-coefficient terms A lap^2 (capillary) and
B lap (gravity, disjoining), solved by a Neumann cosine transform (a stabilised semi-implicit scheme: it damps the
grid scale, and the steady patterns are unchanged). Time step limited by the speed of the mud (CFL on dx). Edges: no
flux on the upslope sides; on the downslope sides the film flows out freely (the flux leaving equals the flux
through the last interior face), as if the shoreline were just beyond the patch. Start: the mud Landlab left after the pool drained (H0 - eroded,
2 mm, enlarged cubically) plus a film of water, as one slurry, with small seeded noise.

Run: python -I thinfilm.py RUN_DIR OUT_DIR --patch X0 Y0 W H (mm) [--dx 0.25] [--tau 0.02] [--mu 0.05] ...
Writes OUT_DIR/thinfilm.npz (h0, h, b, x0, y0, dx, params) and meta.json.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy import fft
from scipy.ndimage import gaussian_filter, zoom

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I drops the script folder
import sim  # noqa: E402

RHO, G = 1000.0, 9.80665


def lap(a, dx):
    p = np.pad(a, 1, mode="edge")
    return (p[1:-1, 2:] + p[1:-1, :-2] + p[2:, 1:-1] + p[:-2, 1:-1] - 4 * a) / dx ** 2


def step_flux(h, b, P):
    dx = P["dx"]
    hs = P["hstar"]
    hc = np.maximum(h, 0.2 * hs)
    r = hs / hc
    Pi = P["kappa"] * (r ** 3 - r ** 2)
    p = RHO * G * (h + b) - P["gamma"] * lap(h, dx) - Pi
    pp = np.pad(p, 1, mode="edge")
    gyc = (pp[2:, 1:-1] - pp[:-2, 1:-1]) / (2 * dx)          # central gradients at nodes, for |G| on faces
    gxc = (pp[1:-1, 2:] - pp[1:-1, :-2]) / (2 * dx)
    # x faces (between columns j and j+1)
    gx = (p[:, 1:] - p[:, :-1]) / dx
    gy = 0.5 * (gyc[:, 1:] + gyc[:, :-1])
    hf = np.where(gx > 0, h[:, 1:], h[:, :-1])              # upstream thickness: keeps h positive
    gm = np.hypot(gx, gy) + 1e-12
    Y = np.clip(hf - P["tau"] / gm, 0, None)
    Mx = Y ** 2 * (3 * hf - Y) / (6 * P["mu"])
    qx = -Mx * gx
    # y faces (between rows i and i+1)
    gy2 = (p[1:, :] - p[:-1, :]) / dx
    gx2 = 0.5 * (gxc[1:, :] + gxc[:-1, :])
    hf2 = np.where(gy2 > 0, h[1:, :], h[:-1, :])
    gm2 = np.hypot(gx2, gy2) + 1e-12
    Y2 = np.clip(hf2 - P["tau"] / gm2, 0, None)
    My = Y2 ** 2 * (3 * hf2 - Y2) / (6 * P["mu"])
    qy = -My * gy2
    div = np.zeros_like(h)
    div[:, :-1] += qx / dx
    div[:, 1:] -= qx / dx
    div[:-1, :] += qy / dx
    div[1:, :] -= qy / dx
    # open downslope edges: the flux leaving equals the flux through the last interior face, if it points outward
    out = 0.0
    for side in P["sinks"]:
        if side == "left":
            f = np.clip(-qx[:, 0], 0, None); div[:, 0] += f / dx
        elif side == "right":
            f = np.clip(qx[:, -1], 0, None); div[:, -1] += f / dx
        elif side == "top":
            f = np.clip(-qy[0, :], 0, None); div[0, :] += f / dx
        else:
            f = np.clip(qy[-1, :], 0, None); div[-1, :] += f / dx
        out += f.sum() * dx
    mmax = max(Mx.max(), My.max())
    # explicit second-order part: gravity and disjoining pressure act like diffusion with D = M (rho g + |Pi'|)
    dPi = P["kappa"] * (3 * r ** 3 - 2 * r ** 2) / hc
    D = max((Mx * (RHO * G + 0.5 * (dPi[:, 1:] + dPi[:, :-1]))).max(), (My * (RHO * G + 0.5 * (dPi[1:, :] + dPi[:-1, :]))).max())
    # speed driven by gravity alone (the capillary part is held by the implicit stabiliser), for the step limit
    sb = np.hypot(*np.gradient(h + b, dx))
    umax = float((RHO * G * sb * np.maximum(h, 0) ** 2 / (3 * P["mu"])).max())
    return -div, mmax, D, umax, out


def run(a):
    dx = a.dx * 1e-3
    x0, y0, w, hgt = a.patch
    nx, ny = int(round(w / a.dx)), int(round(hgt / a.dx))
    # bed: the tub geometry from sim.py, evaluated on the fine patch grid
    X = (x0 + (np.arange(nx) + 0.5) * a.dx) * 1e-3
    Yy = (y0 + (np.arange(ny) + 0.5) * a.dx) * 1e-3
    gx_, gy_ = np.meshgrid(X, Yy)
    b = bed_at(gx_, gy_)
    # start: the mud Landlab left after the pool drained (H0 - eroded), enlarged from the run's cell
    d = np.load(Path(a.run) / "fields.npz")
    mud = np.clip(d["H0"].astype("f8") - d["eroded"].astype("f8"), 0, None)
    cell = 1280 / mud.shape[1]
    i0, j0 = int(y0 / cell) - 2, int(x0 / cell) - 2
    sub = mud[max(i0, 0):int((y0 + hgt) / cell) + 3, max(j0, 0):int((x0 + w) / cell) + 3]
    up = zoom(sub, cell / a.dx, order=3).clip(0)
    oy, ox = int(round((y0 - max(i0, 0) * cell) / a.dx)), int(round((x0 - max(j0, 0) * cell) / a.dx))
    m0 = up[oy:oy + ny, ox:ox + nx]
    rng = np.random.default_rng(a.seed)
    noise = gaussian_filter(rng.standard_normal((ny, nx)), a.noise_corr / a.dx)
    noise /= noise.std() + 1e-12
    h = (m0 + a.film * 1e-3) * (1 + a.noise * noise)
    hstar = a.hstar * 1e-6
    h = np.maximum(h, hstar)
    h0 = h.copy()
    P = dict(dx=dx, mu=a.mu, tau=a.tau, gamma=a.gamma, hstar=hstar,
             kappa=2 * a.gamma * (1 - np.cos(np.radians(a.theta))) / hstar)
    # downslope edges absorb: decided from the mean bed slope across the patch
    sx = np.mean(b[:, -1] - b[:, 0]); sy = np.mean(b[-1, :] - b[0, :])
    P["sinks"] = ([("left" if sx > 0 else "right")] if abs(sx) > 0 else []) + ([("top" if sy > 0 else "bottom")] if abs(sy) > 0 else [])
    # Neumann cosine-transform eigenvalues of -lap
    kx = (2 - 2 * np.cos(np.pi * np.arange(nx) / nx)) / dx ** 2
    ky = (2 - 2 * np.cos(np.pi * np.arange(ny) / ny)) / dx ** 2
    K2 = ky[:, None] + kx[None, :]
    K4 = K2 ** 2
    t, n, t0 = 0.0, 0, time.time()
    mass0 = h.sum()
    out_vol, clip_add = 0.0, 0.0
    log = []
    snaps = {}
    snap_t = [float(s) for s in a.snaps.split(",")] if a.snaps else []
    while t < a.t_end:
        rate, mmax, D, umax, outflow = step_flux(h, b, P)
        A = a.stab * P["gamma"] * max(mmax, 1e-30)           # implicit stabiliser for the capillary term
        B = a.stab_b * D                                       # and for gravity and disjoining pressure
        dt = min(a.dt_max, a.cfl * dx / max(umax, 1e-30), a.t_end - t)
        rhs = h + dt * rate
        hh = fft.dctn(rhs, type=2, norm="ortho", workers=a.workers)
        hn = fft.dctn(h, type=2, norm="ortho", workers=a.workers)
        L = dt * (A * K4 + B * K2)
        hh = (hh + L * hn) / (1 + L)
        h = fft.idctn(hh, type=2, norm="ortho", workers=a.workers)
        clip_add += float(np.clip(hstar - h, 0, None).sum()) * dx * dx
        h = np.maximum(h, hstar)
        out_vol += outflow * dt
        t += dt
        n += 1
        if n % 500 == 0 or t >= a.t_end:
            log.append({"t": round(t, 4), "steps": n, "dt": dt, "mean_h_um": round(h.mean() * 1e6, 2),
                        "max_h_um": round(h.max() * 1e6, 1), "wall_s": round(time.time() - t0, 1)})
            if a.verbose:
                print(log[-1], flush=True)
        while snap_t and t >= snap_t[0]:
            snaps[f"h_t{snap_t[0]:g}"] = h.astype("f4")
            snap_t.pop(0)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "thinfilm.npz", h0=h0.astype("f4"), h=h.astype("f4"), b=b.astype("f4"), **snaps)
    meta = {"patch_mm": a.patch, "dx_mm": a.dx, "t_end_s": a.t_end, "steps": n, "wall_s": round(time.time() - t0, 1),
            "tau_y_Pa": a.tau, "mu_Pas": a.mu, "gamma_N_m": a.gamma, "theta_deg": a.theta, "hstar_um": a.hstar,
            "film_mm": a.film, "noise": a.noise, "noise_corr_mm": a.noise_corr, "seed": a.seed, "stab": a.stab,
            "sinks": P["sinks"], "mass_left_frac": round(float(h.sum() / mass0), 4),
            "outflow_frac": round(out_vol / (mass0 * dx * dx), 4), "clip_added_frac": round(clip_add / (mass0 * dx * dx), 5),
            "balance_error_frac": round(float((h.sum() - mass0) * dx * dx + out_vol - clip_add) / (mass0 * dx * dx), 6),
            "yield_depth_mm_at_mean_slope": round(a.tau / (RHO * G * max(np.hypot(*np.gradient(b, dx)).mean(), 1e-9)) * 1e3, 3),
            "run": str(Path(a.run).name), "log": log}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def bed_at(Xm, Ym):
    """sim.geometry's bed formula, at arbitrary points (metres)."""
    LX, LY, FALL, DISH, DRAIN = sim.LX, sim.LY, sim.FALL, sim.DISH, sim.DRAIN
    xc, yc = LX / 2, LY / 2
    u = np.abs(Xm - xc) / xc
    v = np.abs(Ym - yc) / yc
    r = (u ** 6 + v ** 6) ** (1 / 6)
    r0 = 0.88 - 0.10 * np.clip((Xm - 0.6 * LX) / (0.4 * LX), 0, 1) ** 2
    wall = 0.06 * np.clip((r - r0) / (1 - r0), 0, None) ** 2
    bed = FALL * (Xm - DRAIN[0]).clip(0) + DISH * ((Ym - yc) / yc) ** 2 + wall
    dd = np.hypot(Xm - DRAIN[0], Ym - DRAIN[1])
    return np.where(dd < 0.03, bed - 0.004 * (1 - dd / 0.03), bed)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("out")
    p.add_argument("--patch", type=float, nargs=4, default=[300, 30, 160, 120], metavar=("X0", "Y0", "W", "H"))
    p.add_argument("--dx", type=float, default=0.25, help="grid, mm")
    p.add_argument("--tau", type=float, default=0.02, help="yield stress, Pa")
    p.add_argument("--mu", type=float, default=0.05, help="plastic viscosity, Pa s")
    p.add_argument("--gamma", type=float, default=0.07, help="surface tension, N/m")
    p.add_argument("--theta", type=float, default=30.0, help="contact angle, degrees")
    p.add_argument("--hstar", type=float, default=20.0, help="precursor film, micrometres")
    p.add_argument("--film", type=float, default=0.3, help="water film added to the mud, mm")
    p.add_argument("--noise", type=float, default=0.02, help="relative noise on the start")
    p.add_argument("--noise-corr", type=float, default=2.0, help="noise correlation, mm")
    p.add_argument("--seed", type=int, default=1414)
    p.add_argument("--t-end", type=float, default=30.0)
    p.add_argument("--dt-max", type=float, default=5e-3)
    p.add_argument("--cfl", type=float, default=0.3)
    p.add_argument("--stab", type=float, default=1.0)
    p.add_argument("--stab-b", type=float, default=1.0)
    p.add_argument("--snaps", default="")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    meta = run(a)
    print(json.dumps({k: v for k, v in meta.items() if k != "log"}, indent=1))


if __name__ == "__main__":
    main()
