"""Day 10: a dryland hillslope under creep, storm runoff and patchy shrubs, built on Landlab 2.11.

The physics is Landlab's; each process is a published component:
  storms   PrecipitationDistribution  Poisson storm arrivals, exponential durations, gamma depths
  routing  FlowAccumulator, D8; the default surface is pit-filled once (SinkFillerBarnes), later pits trap
  wash     ErosionDeposition          Davy and Lague (2009): erosion K Q^m S^n (m 0.75, n 1), deposition v_s qs / q
  creep    LinearDiffuser             q = -D grad z, D varying with shrub cover
  runon    LossyFlowAccumulator's rule: water flowing onto a shrub patch soaks into the capacity
           the storm left unused there; computed by `runon()`, tested equal to the component (tests/test_runon.py)
Written for this build: the starting surface, the vegetation pattern, runoff by infiltration excess, the runon loop, the volume ledger and the outputs.

Run:  python sim.py --seed 42 --out OUTDIR [--z0 F] [--rain-scale F] [--veg-scale F] [--dt-scale F] [--no-map]
Contract: the benchmark prompt, benchmark/prompts/python_prompt_v2.md in this folder (fixed flags and output files).
The default run is 2,000 years; set D10_YEARS to change it (build_page.py runs 4,000).
Arrays are written row 0 = top (north); Landlab's node 0 is bottom left, so grids are flipped on the way in and out.
"""
import argparse, csv, json, time
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from landlab import RasterModelGrid
from landlab.components import (ErosionDeposition, FlowAccumulator, LinearDiffuser, PrecipitationDistribution,
                                 SinkFillerBarnes)

# ---- Parameters (units: m, years; storms in hours and mm) -------------------------------
NY, NX, DX = 120, 120, 5.0           # 600 m square
YEARS = float(__import__("os").environ.get("D10_YEARS", 2000.0))
DT_STEP = 5.0                        # creep step, years; storms are handled one by one inside it
HOURS_PER_YEAR = 8766.0
STORM_MEAN_DURATION_H = 2.0          # convective storms
STORMS_PER_YEAR = 12.0
STORM_MEAN_DEPTH_MM = 14.0           # mean annual rain about 170 mm
INFIL_BARE_M, INFIL_SHRUB_M = 0.006, 0.020   # storm depth soaked up before runoff, bare to full cover
M_SP = 0.75                          # discharge exponent m in K Q^m S: the higher it is, the more big flows dominate and gullies branch
Q_REF = 5.5e4                        # reference discharge, m^3/yr: a typical storm's runoff from about 100 cells
K_REF = 4.69                         # wash erosion rate per unit slope at Q_REF, m/yr; same as the old K 0.02 at m 0.5
V_S = 1000.0                         # effective settling velocity on bare ground, m/yr (Landlab: [L/T])
V_S_SHRUB_GAIN = 2.0                 # full cover triples v_s: stems and litter slow the flow (an assumption)
K_SHRUB_FACTOR = 0.15                # erodibility under full cover, as a share of bare
D_BARE = 0.005                       # creep diffusivity on bare ground, m^2/yr
D_SHRUB_GAIN = 0.5                   # full cover raises D by 50 % (roots and burrows loosen the soil)
VEG_COVER_MEAN = 0.35


def nonneg(s):
    v = float(s)
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {s}")
    return v


def positive(s):
    v = float(s)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"must be more than 0, got {s}")
    return v


def parse():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--z0")
    p.add_argument("--rain-scale", type=nonneg, default=1.0)
    p.add_argument("--veg-scale", type=nonneg, default=1.0)
    p.add_argument("--dt-scale", type=positive, default=1.0)
    p.add_argument("--no-map", action="store_true")
    return p.parse_args()


def default_surface(rng):
    """Mountain front over a piedmont: a 30 % escarpment easing to a 2 % apron, with seeded roughness and hollows."""
    s = np.arange(NY)[:, None] / (NY - 1) * np.ones((1, NX))          # 0 at the top row, 1 at the bottom
    L = (NY - 1) * DX
    upper = s < 0.45
    z = np.where(upper, 0.02 * L * (1 - 0.45) + 0.30 * L * (0.45 - s), 0.02 * L * (1 - s))
    z = gaussian_filter(z, 2.0, mode="nearest")
    # Inherited relief: roughness at two scales, stronger on the escarpment, and five shallow hollows
    # at seeded places that taper downslope, slower than the apron falls, so they never make a pit.
    unit = lambda a: (a - a.mean()) / a.std()
    esc = 0.25 + 0.75 * np.clip((0.55 - s) / 0.55, 0, 1)
    rough = 0.6 * unit(gaussian_filter(rng.standard_normal((NY, NX)), 1.5)) + unit(gaussian_filter(rng.standard_normal((NY, NX)), 4.0))
    z = z + 0.15 * rng.standard_normal((NY, NX)) + 0.5 * rough * esc
    x = np.arange(NX)[None, :] / (NX - 1)
    for xc in np.sort(rng.uniform(0.08, 0.92, 5)):
        z = z - 3.0 * np.clip(1 - s / 0.75, 0, 1) * np.exp(-((x - xc) / 0.06) ** 2)
    # Fill the seeded pits once, with a tiny gradient, so runoff starts connected (SinkFillerBarnes).
    g = RasterModelGrid((NY, NX), xy_spacing=DX)
    g.add_field("topographic__elevation", to_ll(z), at="node")
    g.set_closed_boundaries_at_grid_edges(True, True, True, False)
    SinkFillerBarnes(g, method="D8", fill_flat=False).run_one_step()
    return from_ll(g.at_node["topographic__elevation"])


def vegetation(rng, scale):
    """Patchy shrub cover from a smoothed random field: about 35 % of the ground under shrubs."""
    f = gaussian_filter(rng.standard_normal((NY, NX)), 2.5, mode="wrap")
    f = (f - f.mean()) / f.std()
    cut = np.quantile(f, 1 - VEG_COVER_MEAN)
    cover = np.clip((f - cut) / 1.0 + 0.4, 0, 0.95) * (f > cut)
    return np.clip(cover * scale, 0, 1), cover


def storms(seed, years):
    """One row per storm: start year, depth mm, duration h. PrecipitationDistribution sets the global
    random and numpy states from the seed; nothing else in this script draws from them."""
    pd = PrecipitationDistribution(mean_storm_duration=STORM_MEAN_DURATION_H,
                                   mean_interstorm_duration=HOURS_PER_YEAR / STORMS_PER_YEAR - STORM_MEAN_DURATION_H,
                                   mean_storm_depth=STORM_MEAN_DEPTH_MM, total_t=years * HOURS_PER_YEAR, random_seed=seed)
    out = []
    for start, end, intensity in pd.get_storm_time_series():
        dur = end - start
        if dur > 0 and intensity > 0:
            out.append((start / HOURS_PER_YEAR, intensity * dur, dur))
    return out


def depth_groups(r):
    """Nodes grouped by their number of D8 steps to an outlet or pit, deepest group first.
    A donor is always one step deeper than its receiver, so a group's donors are all finished before it."""
    n = len(r)
    depth = (r != np.arange(n)).astype(np.int64)   # pointer jumping: about log2(longest path) passes
    up = r.copy()
    while True:
        depth = depth + depth[up]
        nxt = up[up]
        if np.array_equal(nxt, up):
            break
        up = nxt
    order = np.argsort(-depth, kind="stable")
    cuts = np.flatnonzero(np.diff(depth[order])) + 1
    return [grp for grp in np.split(order, cuts) if depth[grp[0]] > 0]


def runon(q_local, r, groups, capacity):
    """LossyFlowAccumulator's rule, vectorised: each node passes on max(Q - capacity, 0) to its receiver.
    Q is the node's own runoff plus what its donors passed on, in m^3/yr. 0.4 ms against the component's
    67 ms a storm on this grid (the component calls a Python loss function at every node)."""
    q = q_local.copy()
    for grp in groups:
        q += np.bincount(r[grp], weights=np.maximum(q[grp] - capacity[grp], 0.0), minlength=len(q))
    return q


def to_ll(a):
    return np.flipud(a).ravel().copy()


def from_ll(v):
    return np.flipud(v.reshape(NY, NX)).copy()


def run(args):
    rng = np.random.default_rng(args.seed)
    t_start = time.time()
    if args.z0:
        z_init = np.load(args.z0).astype(np.float64)
        if z_init.shape != (NY, NX):
            raise SystemExit(f"--z0 must have shape {(NY, NX)}, got {z_init.shape}")
    else:
        z_init = default_surface(rng)
    cover, cover_unscaled = vegetation(rng, args.veg_scale)
    storm_list = storms(args.seed, YEARS)

    g = RasterModelGrid((NY, NX), xy_spacing=DX)
    z = g.add_field("topographic__elevation", to_ll(z_init), at="node")
    g.set_closed_boundaries_at_grid_edges(True, True, True, False)   # right, top, left closed; bottom open
    c = to_ll(cover)
    runoff = g.add_zeros("water__unit_flux_in", at="node")
    fa = FlowAccumulator(g, flow_director="D8")   # no depression handler: a pit traps water and sediment
    K_wash = K_REF * Q_REF ** -M_SP     # so K Q^m equals K_REF at Q_REF whatever m is
    ed = ErosionDeposition(g, K=K_wash * (1 - (1 - K_SHRUB_FACTOR) * c), v_s=V_S * (1 + V_S_SHRUB_GAIN * c),
                           m_sp=M_SP, n_sp=1.0, F_f=0.0)
    q_field = g.at_node["surface_water__discharge"]
    node_area = np.full(g.number_of_nodes, DX * DX); node_area[g.boundary_nodes] = 0.0   # as FlowAccumulator
    receivers, groups = None, None
    D_node = D_BARE * (1 + D_SHRUB_GAIN * c)
    D_link = g.map_mean_of_link_nodes_to_link(D_node)
    ld = LinearDiffuser(g, linear_diffusivity=D_link, deposit=True)
    infil = INFIL_BARE_M + (INFIL_SHRUB_M - INFIL_BARE_M) * c
    core, bnd, cell_area = g.core_nodes, g.boundary_nodes, DX * DX
    z_ll0 = z.copy()

    dt = DT_STEP * args.dt_scale
    n_sub = max(1, int(round(1 / args.dt_scale))) if args.dt_scale < 1 else 1
    nsteps = int(round(YEARS / dt))
    exported_wash = exported_creep = 0.0
    wash_storms = 0
    runon_m3 = 0.0
    frames, frame_every = [], max(1, nsteps // 12)
    budget = []                                  # per creep step: year, exported, gross cut, gross fill (m^3)
    si = 0
    for k in range(nsteps):
        t1 = (k + 1) * dt
        while si < len(storm_list) and storm_list[si][0] < t1:
            _, depth_mm, dur_h = storm_list[si]
            si += 1
            rain_m = depth_mm / 1000 * args.rain_scale
            r = np.maximum(rain_m - infil, 0.0)
            if not r.any():
                continue
            dur_y = dur_h / HOURS_PER_YEAR
            runoff[:] = r / dur_y                                 # m/yr while it rains
            spare = np.maximum(infil - rain_m, 0.0) * node_area / dur_y   # unused soak-up, m^3/yr
            for _ in range(n_sub):
                fa.run_one_step()
                if spare.any():
                    rcv = g.at_node["flow__receiver_node"]
                    if receivers is None or not np.array_equal(rcv, receivers):
                        receivers, groups = rcv.copy(), depth_groups(rcv)
                    q_runon = runon(runoff * node_area, receivers, groups, spare)
                    moves = receivers != np.arange(len(receivers))   # loss happens only along a link
                    runon_m3 += float(np.minimum(q_runon, spare)[moves].sum()) * dur_y / n_sub
                    q_field[:] = q_runon
                ed.run_one_step(dur_y / n_sub)
                if spare.any():
                    # Where runon soaked up all the water, ErosionDeposition sets qs to zero and the incoming
                    # sediment would vanish; drop it there instead, the rule Landlab applies at pits.
                    qs_in = g.at_node["sediment__influx"]
                    rc = g.at_node["flow__receiver_node"][core]
                    dry = core[(q_field[core] <= 0.0) & (qs_in[core] > 0.0) & (rc != core)]   # pits: Landlab's rule
                    z[dry] += qs_in[dry] * (dur_y / n_sub) / cell_area
                exported_wash += float(g.at_node["sediment__influx"][bnd].sum()) * dur_y / n_sub
                wash_storms += 1
        v0 = z[core].sum()
        ld.run_one_step(dt)
        exported_creep += -(z[core].sum() - v0) * cell_area
        dzc = z[core] - z_ll0[core]
        budget.append((t1, exported_wash + exported_creep, float(-dzc[dzc < 0].sum()) * cell_area, float(dzc[dzc > 0].sum()) * cell_area))
        if (k + 1) % frame_every == 0 or k == 0:
            frames.append((t1, from_ll(z.copy())))
    z_final = from_ll(np.asarray(z))
    exported = exported_wash + exported_creep
    net = float((z_final - z_init).sum()) * cell_area
    gross = float(np.abs(z_final - z_init).sum()) * cell_area / 2
    tel = {
        "seed": args.seed, "grid_shape": [NY, NX], "cell_size_m": DX, "years_simulated": YEARS,
        "timesteps": nsteps, "dt_years": dt, "storm_count": len(storm_list),
        "mean_annual_rain_mm": round(sum(s[1] for s in storm_list) / YEARS, 2),
        "creep_diffusivity_m2_per_yr": D_BARE, "open_boundaries": ["bottom"],
        "sediment_exported_m3": exported, "uplift_or_baselevel_m3": 0.0,
        "mass_balance_error_pct": abs(net + exported) / max(gross, 1e-30) * 100,
        "exported_by_wash_m3": exported_wash, "exported_by_creep_m3": exported_creep,
        "wash_events_computed": wash_storms, "runon_infiltrated_m3": round(runon_m3, 2),
        "budget": budget,  # removed before telemetry.json is written
        "pits_at_end": int((g.at_node["flow__receiver_node"][core] == core).sum()), "runtime_s": round(time.time() - t_start, 2),
    }
    return z_init, z_final, cover, storm_list, tel, frames


def main():
    args = parse()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    z_init, z_final, cover, storm_list, tel, frames = run(args)
    tel.pop("budget", None)
    np.save(out / "z_initial.npy", z_init)
    np.save(out / "z_final.npy", z_final)
    np.save(out / "vegetation.npy", cover)
    with open(out / "storms.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["year", "depth_mm"])
        w.writerows([(round(y, 6), round(d, 4)) for y, d, _ in storm_list])
    (out / "telemetry.json").write_text(json.dumps(tel, indent=1))
    print(json.dumps(tel))
    if not args.no_map:
        write_maps(out, z_init, z_final, cover, storm_list, tel, frames)


def write_maps(out, z_init, z_final, cover, storm_list, tel, frames):
    """A quick static map; the interactive page is app/index.html, built by build_page.py."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dz = z_final - z_init
    v = float(np.quantile(np.abs(dz), 0.98)) or 1e-6
    fig, ax = plt.subplots(1, 2, figsize=(10, 5))
    ax[0].imshow(z_final, cmap="gist_earth"); ax[0].set_title("Elevation, m")
    ax[1].imshow(dz, cmap="RdBu", vmin=-v, vmax=v); ax[1].set_title("Change, m")
    fig.savefig(out / "map.png", dpi=100); plt.close(fig)
    (out / "map.html").write_text("<!doctype html><meta charset=utf-8><title>Day 10 run</title><p>Elevation and change at the end of this run. "
                                  "The interactive lab is app/index.html, built by build_page.py.</p><img src=\"map.png\" alt=\"Elevation and change maps\">")


if __name__ == "__main__":
    main()
