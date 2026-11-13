<!-- The agent's final reply, verbatim except that local file paths are shortened. -->
I've written and tested `sim.py`. It runs on a 100 × 100 grid of 2 m cells (a 200 m slope) for 600 years, with storms of random size, overland flow that erodes and deposits, creep, and patchy vegetation. Volume is conserved to about 1e-12 %, and halving the time step changes the result by 1–2 %. The page's JavaScript was never actually run (see 4 and 5).

## 1. Main assumptions

| Topic | Assumption | Reasoning |
|---|---|---|
| Grid and time | 100 × 100 cells of 2 m; 600 years; base step 1 year | Hillslope scale. This is long enough for rills and sediment aprons to form and still run in about 22 s. |
| Starting surface | Rounded crest, steep midslope (up to about 24 %), curved-in footslope, 1.2 % plain at the foot; gentle spurs and hollows; 3 cm random roughness | A typical dryland hillslope profile. The hollows give flow somewhere to gather. |
| Soil | Never runs out (transport-limited supply); one erodibility | Keeps the model simple for teaching. Bedrock is not modelled. |
| Rain | Storms arrive at random (Poisson, about 16 a year); depths are exponential with a 12 mm mean; about 188 mm a year | Random arrivals with exponential depths is the standard stochastic rainfall model (Rodriguez-Iturbe et al. 1999). The totals are semi-arid. |
| Runoff | Each storm loses a fixed depth to infiltration: 6 mm on bare crusted soil, up to 25 mm under full cover. The rest runs off. | A simple depth-threshold version of infiltration-excess runoff. Storm intensity is not modelled. |
| Flow routing | Multiple flow directions, exponent 1.1 (Freeman 1991), with contour-length weights (Quinn et al. 1991) | Spreads sheet flow realistically on hillslopes. Ordering cells high to low gives an exact single-pass solve. |
| Erosion and deposition | Detachment E = K·q^0.5·S per storm. Deposition D = V·Qs/Q (the Davy & Lague 2009 erosion–deposition model). | Sediment is carried downslope and dropped where flow is weak, such as flats, plant patches and closed hollows. Nothing is deleted. |
| Creep | Linear diffusion; D = 0.005 m²/yr on bare ground | Linear creep is the standard hillslope model, and 0.005 m²/yr is a typical dryland value. |
| Vegetation (static) | Patches cover about 38 % of the ground, slightly stretched along the contour; 0.05 cover between patches | Patchy shrub and grass cover. Plants do not grow or die during the run. |
| Boundaries | Bottom edge open: the last row is a fixed base level and everything reaching it is counted as exported. Top, left and right are closed. | Meets the brief. Nothing is uplifted, so `uplift_or_baselevel_m3 = 0`. |
| Numerical scheme | Explicit flux-form creep with automatic sub-stepping (D·dt/dx² ≤ 0.1). Erosion in one pulse is capped at half the drop to the lowest neighbour. Flow is recomputed for every storm pulse. | Stable for any surface. With `--dt-scale 0.5`, each storm's erosion is applied as two halves with flow re-routed between them. |
| Mass-balance measure | 100 × (volume change on the grid + volume exported) ÷ (gross volume eroded) | Closes to machine precision. |

**What vegetation does to each process (cover from 0 to 1):**
- **Runoff:** it raises infiltration from 6 to 25 mm per storm, and a fully vegetated cell soaks up 50 % of the water flowing into it from upslope. Runoff goes down.
- **Erosion:** it lowers erodibility to K × e^(−3·cover). Erosion goes down. The exponential fall with cover follows Gyssels et al. (2005).
- **Deposition:** it multiplies the settling term V by up to 10. Sediment trapping goes up.
- **Creep:** it raises D by up to 2× (roots and burrowing animals stir the soil). Creep goes up.

## 2. Command and telemetry

`python3 sim.py --seed 42 --out out42` took 62 s wall time including both maps and two extra scenario runs (bare ground and doubled cover). It printed:

```json
{"seed": 42, "grid_shape": [100, 100], "cell_size_m": 2.0, "years_simulated": 600.0,
 "timesteps": 600, "dt_years": 1.0, "storm_count": 9420, "mean_annual_rain_mm": 187.5283331233877,
 "creep_diffusivity_m2_per_yr": 0.005, "open_boundaries": ["bottom"],
 "sediment_exported_m3": 133.47522996762234, "uplift_or_baselevel_m3": 0.0,
 "mass_balance_error_pct": -2.385571085120127e-12}
```

`mean_annual_rain_mm` reports the rain actually applied, after `--rain-scale`.

## 3. Where each process is in `sim.py`

1. **Creep:** `creep_step`, lines 221–244, called at line 283.
2. **Overland-flow erosion and deposition:** `route_flow` (130–168), `_downslope_solve` (171–181) and `storm_pulse` (184–215).
3. **Random storms:** `make_storms` (101–106), and the storm loop in `run_model` (lines 271–281), which also splits storms into halves for `--dt-scale`.
4. **Vegetation:** `make_vegetation` (91–98) and `veg_fields` (109–117). The resulting values are used in `storm_pulse` and `creep_step`.

## 4. What I verified by running something, and what I didn't

**Verified by running:**
- **Timings (no maps):** the default run takes about 22 s; the slowest other case was `--rain-scale 2` at 30 s. With `--dt-scale 0.5` the default surface took 52 s in a run before the final speed-up, and other surfaces took 38–44 s. The full run with maps takes 62 s.
- **Single core:** CPU time was close to wall time, so it effectively runs on one core. I could not pin it to one core because `taskset` was blocked.
- **Time step:** halving it changed the final surface by 1.0 % (default surface), 2.0 % (plane) and 1.5 % (steep rough surface), measured as RMS difference ÷ RMS change.
- **Mass balance:** the error was at most about 1e-11 % in every case.
- **Same seed, same result:** two runs with seed 42 gave identical output (same md5).
- **`--z0`:** works on three other surfaces (a plane, a steep rough surface with many closed hollows, and a concave valley). `z_initial` equals the input exactly, and every value stays finite.
- **`--rain-scale 0`:** creep only; the run takes 0.2 s.
- **Vegetation's effect:** with `--veg-scale 0`, export is about 100 times higher than the default run (13,341 vs 133 m³).
- **Static map:** I looked at `map.png`. It shows a gully in a hollow, deposits on the upslope side of plant patches, and a deposition band near the foot of the slope.
- **The HTML page (no browser, and no JS engine):**
  - I parsed it in Python. It is 1.40 MB with no external addresses, and the tags nest correctly.
  - Every element the script looks up exists, and brackets in the script balance.
  - There are 9 `data-bench` controls: time, play, four layer buttons, a vegetation outline toggle, a scenario selector, and a vertical-exaggeration slider.
  - The data embedded in the page decodes to match the `.npy` files (within 3e-5 m).
  - A Python transcription of the page's hillshade matches matplotlib's (correlation 1.000) after I fixed a wrong light direction.

**Not verified:**
- The page's JavaScript never actually ran. Node.js was blocked by permissions, so drawing, the controls, layout and legends in a real browser are untested.
- The literature citations: I am confident of them, but I did not check them.
- The parameter values are reasonable for drylands but not calibrated against any field site.

## 5. What I couldn't do

- **Browser behaviour:** see section 4. A JavaScript runtime error would stop the page working, and I could not rule one out.
- **Run time:** timed on this machine only. A checker machine more than about 2.5 times slower could exceed the 60 s no-map limit.
- **Model limits:**
  - Vegetation is fixed: it does not grow, die or respond to erosion.
  - Runoff depends only on storm depth, not intensity.
  - Soil depth is unlimited, so nothing can erode down to bedrock.
- **Results on the page:**
  - On the "loss / gain" layer, each scenario has its own colour scale, labelled in the legend.
  - The run's output files are in `out42/`. The test scripts are in `/tmp/geotools/`, outside the project.