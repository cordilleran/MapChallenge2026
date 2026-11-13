You are building a small interactive teaching tool: a simulated map of hillslope erosion and deposition in a dryland environment. Work in the current folder. Python 3 with numpy, scipy and matplotlib is installed; nothing else may be installed or downloaded.

## The science

Simulate the evolution of a synthetic dryland hillslope, at least 100 by 100 cells, over a time span you choose. The model must include all four of these processes, coupled through elevation:

1. Hillslope creep (diffusion of soil downslope).
2. Erosion by overland flow, driven by local slope and an upslope contributing area that you route over the surface. Eroded sediment must be carried downslope and deposited where the flow can no longer carry it (for example at the foot of the slope), not deleted from the grid.
3. Rain that arrives as random storms of varying size, not as a steady rate.
4. Patchy vegetation that changes how easily the surface erodes.

Choose the equations, parameter values, boundaries, grid spacing and time step yourself, from broadly accepted geomorphology, and keep the numerical scheme stable. You may set the boundaries open (sediment leaves the grid) or closed, but you must account for every cubic metre: whatever leaves the grid is counted.

All randomness (initial roughness, vegetation, storms) must come from one seed given on the command line, so the same seed always gives exactly the same result.

## What to deliver

One file, `sim.py`, run as:

```
python3 sim.py --seed 42 --out OUTDIR
```

It must finish within 120 seconds on one CPU core, create `OUTDIR` if needed, and write exactly these files there:

| File | Content |
| :--- | :--- |
| `z_initial.npy` | starting elevation, metres, 2D float64 |
| `z_final.npy` | final elevation, metres, same shape |
| `telemetry.json` | the keys listed below |
| `map.png` | a static map of the result |
| `map.html` | the interactive teaching tool, one self-contained file that works offline (no CDN or other web addresses) |

`telemetry.json` keys: `seed` (int), `grid_shape` ([rows, cols]), `cell_size_m`, `years_simulated`, `timesteps` (int), `open_boundaries` (list of edges, empty if closed), `sediment_exported_m3` (total that left the grid), `uplift_or_baselevel_m3` (volume added or removed by any uplift or base-level change, 0 if none), `max_erosion_m`, `max_deposition_m`, and `mass_balance_error_pct` (your own measure of how well volume is conserved).

### The map

The map is for a student. It must:

- show the terrain with relief shading and a palette chosen for a dryland, not a default colour map;
- show where the surface lost and gained material, on a scale centred on zero;
- let the student explore at least two of: time (before to after), layers (terrain, change, vegetation, flow), or a parameter (storminess or vegetation cover);
- explain on the page, in plain words, what the model assumes and which landforms to look for.

## Your reply

After writing and testing `sim.py`, reply with:

1. A table of your main assumptions (soil, rain, vegetation, equations, boundaries, numerical scheme), one line of reasoning each. Cite a source only if you are sure of it.
2. The command you ran and the telemetry it printed.
3. Anything you could not do, said plainly.

## Show your homework

This run is part of a benchmark, and your working will be checked by other tests after you finish. Keep a record as you go, and at the end package everything as one file, `submission.zip`, that the user can download. Do not tidy away failed attempts: they are part of the record.

`submission.zip` must contain exactly this layout:

```
submission/
  sim.py                       the final script
  run42/                       the OUTDIR from: python3 sim.py --seed 42 --out run42
  homework/
    environment.txt            output of: python3 -V; python3 -c "import numpy, scipy, matplotlib; print(numpy.__version__, scipy.__version__, matplotlib.__version__)"; uname -a
    commands.log               every command you ran, in order: the command, its exit code, its run time, and the last 20 lines of its output
    attempts.md                each version of sim.py you ran, numbered: what you changed, what happened, why you changed it next
    assumptions.md             the assumptions table from your reply
    self_checks.md             any checks you ran on your own results (mass balance, stability, the same seed twice), with their output
    versions/                  every earlier version of sim.py, named attempt_01.py, attempt_02.py, ...
```

If you cannot run Python here, say so at the top of `homework/attempts.md`, still deliver `sim.py`, leave out `run42/`, and say which parts of the record are therefore missing. If you cannot make a zip file, give the same files and folders in your reply instead, one code block each, headed with their path.
