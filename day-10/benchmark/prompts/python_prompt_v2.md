You are building a small interactive teaching tool: a simulated map of hillslope erosion and deposition in a dryland environment. Work in the current folder. Python 3 with numpy, scipy and matplotlib is installed; nothing else may be installed or downloaded.

## The science

Simulate the evolution of a synthetic dryland hillslope, at least 100 by 100 cells, over a time span you choose. State the span in years: the checker reports your erosion rates in millimetres per year. The model must include all four of these processes, coupled through elevation:

1. Hillslope creep (diffusion of soil downslope).
2. Erosion by overland flow, driven by local slope and an upslope contributing area that you route over the surface. Eroded sediment must be carried downslope and deposited where the flow can no longer carry it (for example at the foot of the slope), not deleted from the grid.
3. Rain that arrives as random storms of varying size, not as a steady rate. Each storm is one event with its own time and depth; save the list (see `storms.csv`).
4. Patchy vegetation that changes how easily the surface erodes. Say in your reply what vegetation does to each process, and in which direction.

Choose the equations, parameter values, boundaries, grid spacing and time step yourself, from broadly accepted geomorphology, and keep the numerical scheme stable. You may set the boundaries open (sediment leaves the grid) or closed, but you must account for every cubic metre: whatever leaves the grid is counted. If any edge is open, the last row must be one of them. Name edges as `top`, `bottom`, `left` and `right` in array terms (row 0 is the top).

The model must not depend on your own starting surface: the checker will run it on other surfaces (`--z0`). Results should change little if the time step is halved.

All randomness (initial roughness, vegetation, storms) must come from one seed given on the command line, so the same seed always gives exactly the same result. With `--z0`, the seed controls only vegetation and storms.

## What to deliver

One file, `sim.py`, run as:

```
python3 sim.py --seed 42 --out OUTDIR [--z0 FILE] [--rain-scale F] [--veg-scale F] [--dt-scale F] [--no-map]
```

| Argument | Meaning |
| :--- | :--- |
| `--z0 FILE` | Start from this surface instead of your own: a 2D float64 `.npy` in metres, with the shape and cell size of your default grid, falling toward the last row. Use it exactly as given; add no roughness. Vegetation and storms still come from the seed. |
| `--rain-scale F` | Multiply every storm's depth by F (default 1). With 0 there is no rain and only creep acts. Storm times and order do not change. |
| `--veg-scale F` | Multiply vegetation cover everywhere by F, capped at full cover (default 1). With 0 the ground is bare. The pattern does not change. |
| `--dt-scale F` | Multiply every time step by F, keeping the same simulated time and the same storms (default 1). With 0.5, each step, and each storm, is computed as two halves with the surface updated between them. |
| `--no-map` | Write the `.npy`, `.csv` and `.json` files only. Skip both maps and any extra scenario runs. |

The default run, with maps, must finish within 240 seconds on one CPU core. With `--no-map` it must finish within 60 seconds (120 with `--dt-scale 0.5`). Create `OUTDIR` if needed and write exactly these files there:

| File | Content |
| :--- | :--- |
| `z_initial.npy` | starting elevation, metres, 2D float64 |
| `z_final.npy` | final elevation, metres, same shape |
| `vegetation.npy` | initial vegetation cover, 0 to 1, same shape |
| `storms.csv` | columns `year` and `depth_mm`, one row per storm, before any scaling |
| `telemetry.json` | the keys listed below |
| `map.png` | a static map of the result (not with `--no-map`) |
| `map.html` | the interactive teaching tool, one self-contained file that works offline (no CDN or other web addresses), under 5 MB (not with `--no-map`) |

`telemetry.json` keys: `seed` (int), `grid_shape` ([rows, cols]), `cell_size_m`, `years_simulated`, `timesteps` (int), `dt_years` (largest step), `storm_count`, `mean_annual_rain_mm`, `creep_diffusivity_m2_per_yr` (on bare ground at low slope; `null` if your creep is not diffusive), `open_boundaries` (list of edges, empty if closed), `sediment_exported_m3` (total that left the grid), `uplift_or_baselevel_m3` (volume added by any uplift or base-level change, positive for material added, 0 if none), and `mass_balance_error_pct` (your own measure of how well volume is conserved).

### The map

The map is for a student. It must:

- show the terrain with relief shading and a palette chosen for a dryland, not a default colour map;
- show where the surface lost and gained material, on a scale centred on zero;
- let the student explore time (before to after) and layers (terrain, change, vegetation, flow); a parameter control is optional;
- explain on the page, in plain words, what the model assumes and which landforms to look for;
- show a scale bar, a legend with units, and the vertical exaggeration of any shading;
- mark each control that changes the picture with the attribute `data-bench`.

## Your reply

No browser is available. Say how you tested the page instead.

After writing and testing `sim.py`, reply with:

1. A table of your main assumptions (soil, rain, vegetation, equations, boundaries, numerical scheme), one line of reasoning each. Cite a source only if you are sure of it.
2. The command you ran and the telemetry it printed.
3. For each of the four processes, the function and line range in `sim.py` that implements it.
4. Which statements in this reply you verified by running something, and which you did not.
5. Anything you could not do, said plainly.
