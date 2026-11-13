You are building a small interactive teaching tool: a simulated map of hillslope erosion and deposition in a dryland environment, delivered as one self-contained HTML file that runs in a browser with no network access.

## The science

Simulate the evolution of a synthetic dryland hillslope, at least 100 by 100 cells, over a time span you choose. The model must include all four of these processes, coupled through elevation:

1. Hillslope creep (diffusion of soil downslope).
2. Erosion by overland flow, driven by local slope and an upslope contributing area that you route over the surface. Eroded sediment must be carried downslope and deposited where the flow can no longer carry it (for example at the foot of the slope), not deleted from the grid.
3. Rain that arrives as random storms of varying size, not as a steady rate.
4. Patchy vegetation that changes how easily the surface erodes.

Choose the equations, parameter values, boundaries, grid spacing and time step yourself, from broadly accepted geomorphology, and keep the numerical scheme stable. You may set the boundaries open (sediment leaves the grid) or closed, but you must account for every cubic metre: whatever leaves the grid is counted.

All randomness must come from a seeded pseudo-random generator that you write (JavaScript's `Math.random` cannot be seeded). Read the seed from the page address (`?seed=42`), default 42. The same seed must always give exactly the same result.

## What to deliver

One file, `map.html`: HTML, CSS and JavaScript only, no external scripts, fonts or web addresses. The simulation runs when the page loads and must finish within 60 seconds.

When the simulation has finished, the page must put two machine-readable blocks in the document:

- `<script type="application/json" id="benchmark-telemetry">` holding a JSON object with the keys `seed`, `grid_shape` ([rows, cols]), `cell_size_m`, `years_simulated`, `timesteps`, `open_boundaries` (list of edges, empty if closed), `sediment_exported_m3`, `uplift_or_baselevel_m3` (0 if none), `max_erosion_m`, `max_deposition_m`, `mass_balance_error_pct` (your own measure of how well volume is conserved);
- `<script type="application/json" id="benchmark-arrays">` holding `{"z_initial": "<base64>", "z_final": "<base64>"}`, each the elevation grid in metres as little-endian Float64 values, row by row.

### The map

The map is for a student. It must:

- show the terrain with relief shading and a palette chosen for a dryland, not a default colour map;
- show where the surface lost and gained material, on a scale centred on zero;
- let the student explore at least two of: time (before to after), layers (terrain, change, vegetation, flow), or a parameter (storminess or vegetation cover);
- explain on the page, in plain words, what the model assumes and which landforms to look for.

## Your reply

Give the complete `map.html` in one code block, then:

1. A table of your main assumptions (soil, rain, vegetation, equations, boundaries, numerical scheme), one line of reasoning each. Cite a source only if you are sure of it.
2. Anything you could not do, said plainly.
