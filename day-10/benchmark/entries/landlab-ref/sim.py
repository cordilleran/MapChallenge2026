"""Day 10: a dryland hillslope under creep, storm runoff and patchy shrubs, built on Landlab 2.11.

The physics is Landlab's (decisions D191, D195, D197):
  storms   PrecipitationDistribution  Poisson storm arrivals, exponential durations, gamma depths
  routing  FlowAccumulator, D8; the default surface is pit-filled once (SinkFillerBarnes), later pits trap
  wash     ErosionDeposition          Davy and Lague (2009): erosion K Q^m S^n, deposition v_s qs / q
  creep    LinearDiffuser             q = -D grad z, D varying with shrub cover
Our own code: the vegetation pattern, runoff by infiltration excess, the volume ledger and the outputs.

Run:  python sim.py --seed 42 --out OUTDIR [--z0 F] [--rain-scale F] [--veg-scale F] [--dt-scale F] [--no-map]
Contract: the geo-benchmark prompt v2 (vault day-10/benchmark/prompts/python_prompt_v2.md).
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
K_WASH = 2.0e-2                      # ErosionDeposition erodibility (Q in m^3/yr, m_sp 0.5, n_sp 1)
V_S = 1000.0                            # settling velocity term, dimensionless in Landlab's form
K_SHRUB_FACTOR = 0.15                # erodibility under full cover, as a share of bare
D_BARE = 0.005                       # creep diffusivity on bare ground, m^2/yr
D_SHRUB_GAIN = 0.5                   # full cover raises D by 50 % (roots and burrows loosen the soil)
VEG_COVER_MEAN = 0.35


def parse():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--z0")
    p.add_argument("--rain-scale", type=float, default=1.0)
    p.add_argument("--veg-scale", type=float, default=1.0)
    p.add_argument("--dt-scale", type=float, default=1.0)
    p.add_argument("--no-map", action="store_true")
    return p.parse_args()


def default_surface(rng):
    """Mountain front over a piedmont: a 30 % escarpment easing to a 2 % apron, with seeded roughness."""
    s = np.arange(NY)[:, None] / (NY - 1) * np.ones((1, NX))          # 0 at the top row, 1 at the bottom
    L = (NY - 1) * DX
    upper = s < 0.45
    z = np.where(upper, 0.02 * L * (1 - 0.45) + 0.30 * L * (0.45 - s), 0.02 * L * (1 - s))
    z = gaussian_filter(z, 2.0, mode="nearest")
    z = z + 0.15 * rng.standard_normal((NY, NX)) + 0.6 * gaussian_filter(rng.standard_normal((NY, NX)), 4.0)
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
    ed = ErosionDeposition(g, K=K_WASH * (1 - (1 - K_SHRUB_FACTOR) * c), v_s=V_S, m_sp=0.5, n_sp=1.0, F_f=0.0)
    D_node = D_BARE * (1 + D_SHRUB_GAIN * c)
    D_link = g.map_mean_of_link_nodes_to_link(D_node)
    ld = LinearDiffuser(g, linear_diffusivity=D_link, deposit=True)
    infil = INFIL_BARE_M + (INFIL_SHRUB_M - INFIL_BARE_M) * c
    core, bnd, cell_area = g.core_nodes, g.boundary_nodes, DX * DX

    dt = DT_STEP * args.dt_scale
    n_sub = max(1, int(round(1 / args.dt_scale))) if args.dt_scale < 1 else 1
    nsteps = int(round(YEARS / dt))
    exported_wash = exported_creep = 0.0
    wash_storms = 0
    frames, frame_every = [], max(1, nsteps // 8)
    si = 0
    for k in range(nsteps):
        t1 = (k + 1) * dt
        while si < len(storm_list) and storm_list[si][0] < t1:
            _, depth_mm, dur_h = storm_list[si]
            si += 1
            r = np.maximum(depth_mm / 1000 * args.rain_scale - infil, 0.0)
            if not r.any():
                continue
            dur_y = dur_h / HOURS_PER_YEAR
            runoff[:] = r / dur_y                                 # m/yr while it rains
            for _ in range(n_sub):
                fa.run_one_step()
                ed.run_one_step(dur_y / n_sub)
                exported_wash += float(g.at_node["sediment__influx"][bnd].sum()) * dur_y / n_sub
                wash_storms += 1
        v0 = z[core].sum()
        ld.run_one_step(dt)
        exported_creep += -(z[core].sum() - v0) * cell_area
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
        "wash_events_computed": wash_storms,
        "pits_at_end": int((g.at_node["flow__receiver_node"][core] == core).sum()), "runtime_s": round(time.time() - t_start, 2),
    }
    return z_init, z_final, cover, storm_list, tel, frames


def main():
    args = parse()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    z_init, z_final, cover, storm_list, tel, frames = run(args)
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
    """Placeholder until slice S4 builds the teaching page."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dz = z_final - z_init
    v = float(np.quantile(np.abs(dz), 0.98)) or 1e-6
    fig, ax = plt.subplots(1, 2, figsize=(10, 5))
    ax[0].imshow(z_final, cmap="gist_earth"); ax[0].set_title("Elevation, m")
    ax[1].imshow(dz, cmap="RdBu", vmin=-v, vmax=v); ax[1].set_title("Change, m")
    fig.savefig(out / "map.png", dpi=100); plt.close(fig)
    (out / "map.html").write_text("<!doctype html><title>Day 10 placeholder</title><p>Teaching page arrives in slice S4.</p>")


if __name__ == "__main__":
    main()
