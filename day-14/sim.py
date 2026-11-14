"""Day 14: the tub drains. A Landlab model of a muddy film scoured by a draining bath.

Territory: an enamelled cast-iron bathtub after a muddy-dog bath, photographed drained (2026-03-18).
The model asks one question: can a falling pool over a thin settled mud film make the pale dendritic
scours, the axial swath and the drain halo in the photo?

Processes, in order:
  1 settling    rule: mud thickness from the water depth when full, times broad lobes and mm lumps
  2 strandlines rule: thin residue lines where the level lingered on the walls (drawn by rule, not flow)
  3 drawdown    Landlab OverlandFlow (de Almeida et al. 2012 shallow-water scheme), from a still pool
                (--stage) at the drain; the drain is a sink emptied every step
  4 scour       detachment-limited, threshold shear: E = K (tau - tau_c) where tau > tau_c (tau_c varies at
                ~3 mm), Manning shear from OverlandFlow depth and discharge; the enamel does not erode;
                the mud surface is the bed, so scours steer later flow
  4b film       once a node emerges its film (--film) drains over --tau-f s; Landlab FlowAccumulator
                (D-infinity) routes it over a lightly smoothed mud surface to the shoreline, which is the
                base level; channels cut where E = Kr max(q S - theta, 0)
  5 dewetting   rule: thin film on a slope beads into blobs (the spotted far end), seeded
K, Kr and the thresholds are calibrated against the photo, not measured; see README.md.
Units: metres, seconds. Arrays are written row 0 = top of the photo (the drain is at the left end).

Run:  python sim.py --out runs/base [--dx 0.002] [--seed 14] [--K 2e-3] [--tauc 0.06] [--Kr 5e2] ...
      (python sim.py -h lists every option; scripts/run_set.sh holds the published runs)
Single-threaded maths is about 12 times faster here: set OMP_NUM_THREADS=1.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from landlab import RasterModelGrid
from landlab.components import FlowAccumulator, OverlandFlow

LX, LY = 1.28, 0.52              # wetted footprint seen in the photo, m (floor plus lower walls)
DRAIN = (0.12, 0.26)             # drain centre, m from the left end and from the top edge
FALL = 0.008                     # floor fall toward the drain (0.8 %)
DISH = 0.003                     # floor dish across, m (centre lower than the sides)
RHO, G = 1000.0, 9.80665


def field(rng, shape, corr_px, sigma=1.0):
    """Gaussian random field, unit variance then scaled, correlation length in pixels."""
    f = gaussian_filter(rng.standard_normal(shape), corr_px, mode="reflect")
    return sigma * (f - f.mean()) / (f.std() + 1e-12)


def geometry(nx, ny, dx):
    x = (np.arange(nx) + 0.5) * dx
    y = (np.arange(ny) + 0.5) * dx
    X, Y = np.meshgrid(x, y)                       # row 0 = top
    # rounded-rectangle coordinate: 0 at the centre, 1 at the footprint edge
    xc, yc = LX / 2, LY / 2
    u = np.abs(X - xc) / xc
    v = np.abs(Y - yc) / yc
    r = (u ** 6 + v ** 6) ** (1 / 6)
    # backrest: the far-end wall starts further in, so it is gentler; blended smoothly along the tub
    r0 = 0.88 - 0.10 * np.clip((X - 0.6 * LX) / (0.4 * LX), 0, 1) ** 2
    wall = 0.06 * np.clip((r - r0) / (1 - r0), 0, None) ** 2
    bed = FALL * (X - DRAIN[0]).clip(0) + DISH * ((Y - yc) / yc) ** 2 + wall
    d = np.hypot(X - DRAIN[0], Y - DRAIN[1])
    bed = np.where(d < 0.03, bed - 0.004 * (1 - d / 0.03), bed)   # the flange dips into the drain
    return X, Y, r, bed, d


def run(a):
    rng = np.random.default_rng(a.seed)
    dx = a.dx
    nx, ny = int(round(LX / dx)), int(round(LY / dx))
    X, Y, r, bed, ddrain = geometry(nx, ny, dx)
    cpx = 0.001 / dx                                # 1 mm in pixels

    # 1 settling: thickness ~ depth when full (fill 0.15 m over the drain), times patchy flocs
    fill = 0.15
    depth_full = np.clip(fill - bed, 0, None)
    patch = np.exp(field(rng, bed.shape, 25 * cpx, a.patch))          # broad lobes ~ 2.5 cm
    floc = field(rng, bed.shape, max(2.0 * cpx, 1.0), a.rough)      # mm-scale lumps
    H0 = a.H0 * (depth_full / fill) * patch * np.clip(1 + floc, 0.2, None)
    slope_bed = np.hypot(*np.gradient(bed, dx))
    H0 *= np.clip(1 - slope_bed / 0.8, 0.15, 1)                     # steep wall keeps less
    H0[ddrain < 0.018] = 0                                          # the drain hole itself

    # 2 strandlines: residue at five levels where the water lingered (rule)
    strand = np.zeros_like(bed)
    for lev in np.linspace(0.022, 0.05, 5):
        strand += 0.25 * a.H0 * np.exp(-((bed - lev) / 0.0006) ** 2) * (r > 0.85)
    H0 = H0 + strand

    # 3 drawdown: Landlab grid (node 0 bottom left, so flip rows)
    grid = RasterModelGrid((ny, nx), xy_spacing=dx)
    grid.set_closed_boundaries_at_grid_edges(True, True, True, True)
    flip = lambda A: A[::-1].ravel()                                 # noqa: E731
    unflip = lambda v: v.reshape(ny, nx)[::-1]                       # noqa: E731
    H = flip(H0).copy()
    bedn = flip(bed)
    z = grid.add_field("topographic__elevation", bedn + H, at="node")
    stage0 = a.stage
    h = grid.add_field("surface_water__depth", np.clip(stage0 - z, 0, None) + 2e-4, at="node")
    tcf = flip(np.exp(field(rng, bed.shape, 3 * cpx, 0.3)))     # cohesion varies at ~3 mm
    drain_nodes = np.flatnonzero(flip(ddrain) < 0.019)
    of = OverlandFlow(grid, mannings_n=a.n, steep_slopes=True, h_init=1e-6, alpha=0.6)

    t, t_end = 0.0, a.tmax
    tau_max = np.zeros(grid.number_of_nodes)
    emerge = np.full(grid.number_of_nodes, np.nan)
    eroded = np.zeros(grid.number_of_nodes)
    vol0 = h[grid.core_nodes].sum() * dx * dx
    log, nstep, t_wall = [], 0, time.time()
    while t < t_end:
        dt = min(of.calc_time_step(), 0.05)
        of.overland_flow(dt=dt)
        h[drain_nodes] = 0.0
        # shear at nodes from link discharge: tau = rho g n^2 u^2 / h^(1/3)
        q = np.abs(grid.at_link["surface_water__discharge"])
        qn = np.maximum(grid.map_max_of_inlinks_to_node(q), grid.map_max_of_outlinks_to_node(q))
        hh = np.maximum(h, 1e-5)
        u = qn / hh
        tau = RHO * G * a.n ** 2 * u ** 2 / hh ** (1 / 3)
        tau[h < 2e-5] = 0.0
        tau_max = np.maximum(tau_max, tau)
        tc = a.tauc * tcf
        E = a.K * np.clip(tau - tc, 0, None) * dt
        E = np.minimum(E, H)
        H -= E
        eroded += E
        z[:] = bedn + H
        wet = h > 1e-4
        newly = np.isnan(emerge) & ~wet
        emerge[newly] = t
        t += dt
        nstep += 1
        if nstep % 200 == 0:
            vol = h[grid.core_nodes].sum() * dx * dx
            log.append([round(t, 2), round(vol / vol0, 4), round(float((~wet[grid.core_nodes]).mean()), 4)])
            if vol / vol0 < a.stop_frac:
                break
    # 4b film drainage: once a node emerges, the film left on it (a.film m deep) drains over a.tau_f seconds.
    # Landlab FlowAccumulator (D-infinity) routes it over the mud surface; nodes still under water are the base
    # level, so the network grows toward the shoreline as it retreats (the drained-reservoir analogue).
    # Rill detachment: E = Kr * max(q S - theta, 0), capped by the mud left; the enamel does not erode.
    t_out = t
    em = np.where(np.isnan(emerge), t_out, emerge)
    rill = np.zeros(grid.number_of_nodes)
    if a.Kr > 0:
        routing = grid.add_zeros("routing__surface", at="node")
        runoff = grid.add_zeros("water__unit_flux_in", at="node")
        fa = FlowAccumulator(grid, surface="routing__surface", flow_director="FlowDirectorDINF",
                             runoff_rate="water__unit_flux_in")
        tf = 0.0
        while tf < t_out + 4 * a.tau_f:
            dtf = a.dt_film
            out_ = em > tf                                    # still under water: base level
            # the film (~0.3 mm) bridges sub-mm floc bumps, so it is routed over a lightly smoothed surface
            zs = flip(gaussian_filter(unflip(z), a.film_smooth, mode="nearest"))
            routing[:] = np.where(out_, zs - 0.01, zs)
            age = tf - em
            runoff[:] = np.where(age >= 0, a.film / a.tau_f * np.exp(-np.clip(age, 0, None) / a.tau_f), 0.0)
            fa.run_one_step()
            Q = grid.at_node["surface_water__discharge"]
            rcv = grid.at_node["flow__receiver_node"]
            # slope to the steeper of the two D-inf receivers, from the real mud surface
            rc = np.clip(rcv, 0, None)
            zz = np.where(rcv >= 0, zs[rc], zs[:, None])
            # distance to each receiver: dx for a side neighbour, dx * sqrt(2) for a diagonal one
            dist = np.hypot(grid.x_of_node[rc] - grid.x_of_node[:, None], grid.y_of_node[rc] - grid.y_of_node[:, None])
            S = np.max(np.clip((zs[:, None] - zz) / np.maximum(dist, dx), 0, None), axis=1)
            qS = Q / dx * S
            Er = a.Kr * np.clip(qS - a.theta, 0, None) * dtf
            Er[out_] = 0.0
            Er = np.minimum(Er, H)
            H -= Er
            rill += Er
            z[:] = bedn + H
            tf += dtf
    # 5 dewetting: thin film on a slope beads into blobs (rule)
    Hm = unflip(H)
    if not a.no_dewet:
        blobs = field(rng, bed.shape, 4 * cpx, 1.0) + 0.6 * field(rng, bed.shape, 1.5 * cpx, 1.0)
        thin = (Hm < 0.6 * a.H0) & (slope_bed > 0.04)
        bead = np.where(blobs > 0.35, 1.6, 0.25)
        Hm = np.where(thin, Hm * bead, Hm)
    else:
        thin = np.zeros_like(Hm, dtype=bool)
    rule = thin | (strand > 0.02 * a.H0)          # where a rule, not the flow, set the mud
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "fields.npz", bed=bed.astype("f4"), H0=H0.astype("f4"), H=Hm.astype("f4"),
                        tau_max=unflip(tau_max).astype("f4"), emerge=unflip(emerge).astype("f4"),
                        eroded=unflip(eroded).astype("f4"), rill=unflip(rill).astype("f4"), r=r.astype("f4"), rule=rule)
    meta = {"args": vars(a), "nx": nx, "ny": ny, "steps": nstep, "t_end_s": round(t, 2), "wall_s": round(time.time() - t_wall, 1),
            "bare_frac": float(((Hm < 0.15 * a.H0) & (r < 1)).mean()), "log": log}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta



def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--dx", type=float, default=0.002)
    p.add_argument("--seed", type=int, default=14)
    p.add_argument("--K", type=float, default=2e-3, help="mud detachment, m/s per Pa of excess shear")
    p.add_argument("--tauc", type=float, default=0.06, help="critical shear, Pa")
    p.add_argument("--H0", type=float, default=4e-4, help="mean settled mud on the floor, m")
    p.add_argument("--rough", type=float, default=0.05, help="mm-scale floc roughness, fraction of H0")
    p.add_argument("--n", type=float, default=0.02, help="Manning n")
    p.add_argument("--stage", type=float, default=0.012, help="pool depth over the drain when the model starts, m")
    p.add_argument("--tmax", type=float, default=120.0)
    p.add_argument("--stop-frac", type=float, default=0.01)
    p.add_argument("--no-dewet", action="store_true")
    p.add_argument("--Kr", type=float, default=5e2, help="film rill detachment, per (m^2/s) of excess q*S")
    p.add_argument("--theta", type=float, default=1e-9, help="film rill threshold on q*S, m^2/s")
    p.add_argument("--film", type=float, default=3e-4, help="film left on emerged mud, m")
    p.add_argument("--tau-f", type=float, default=8.0, help="film drainage time scale, s")
    p.add_argument("--dt-film", type=float, default=1.0)
    p.add_argument("--film-smooth", type=float, default=1.5, help="smoothing of the film routing surface, grid cells")
    p.add_argument("--patch", type=float, default=0.2, help="log-sd of the 2.5 cm mud lobes")
    a = p.parse_args()
    print(json.dumps({k: v for k, v in run(a).items() if k != "log"}, indent=1))


if __name__ == "__main__":
    main()
