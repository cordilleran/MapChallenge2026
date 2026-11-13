<!-- The agent's final reply, verbatim except that local file paths are shortened. -->
Waiting for the run to finish.
Waiting for the convergence tests.
Waiting.
Waiting.
Meanwhile, I'll write an HTML test harness.
Waiting.
I've written and tested `sim.py`. The default run with maps takes about 16 s on one core and all seven output files are written. The slope's overall behaviour holds up when the time step is halved, but on bare ground the exact positions of individual gullies shift (see section 5).

## 1. Main assumptions

| Topic | Choice | Reasoning |
|---|---|---|
| Grid and time | 120 rows × 100 columns, 2 m cells (240 m long, 200 m wide); **1000 years**, 1-year steps | Long enough for rills and fans to show at dryland rates, and fast enough for the time limits. |
| Starting surface | Concave slope from 22 m down to 0 m, two shallow hollows across it, about 2 cm of random roughness from the seed | A typical dryland profile, with hollows to gather the flow. |
| Soil | Always erodible (no bedrock), one soil type | Keeps the teaching model simple. Stated on the page. |
| Rain | Storms arrive at random (about 20 a year); each storm's depth is random around a 12 mm mean, giving about 240 mm a year | Random storm arrivals and depths are the standard way to model dryland rain (Eagleson 1978). |
| Runoff | Rain beyond what the soil absorbs per storm runs off: 8 mm on bare crusted soil, 30 mm under full cover. Plant patches also soak up 50% × cover of the runoff arriving from upslope | Patches capturing runoff from bare ground upslope is a key dryland feedback. |
| Creep | Linear diffusion, rate D = 0.005 m²/yr on bare ground, rising to D·(1+v) under plants | Linear diffusion is the classic creep law (Culling 1960). The value sits in the commonly quoted 10⁻³–10⁻² m²/yr range. |
| Overland-flow erosion | Water is routed downhill cell by cell (steepest descent, D8). Carrying capacity rises with storm water per metre of width and with slope (both to the power 1.5). The sediment load moves toward that capacity over a settling length L (20 m on bare ground): soil is picked up where the load is below capacity and dropped where it is above | Follows the erosion–deposition idea of Davy & Lague (2009). Sediment is carried downslope and dropped where the flow slows; nothing is deleted. |
| Calibration | Transport coefficient set to 0.1 by trial | Gives a mean loss rate of about 0.05 mm/yr with plants and 0.5 mm/yr on bare ground, which I judged plausible for drylands. |
| Vegetation pattern | Smoothed random noise stretched along the contour, giving bands and spots; mean cover 0.32 | Mimics banded and spotted dryland vegetation. It does not grow or die during the run. |
| **What vegetation does** | **Runoff:** less (soaks in more rain and catches runoff from above). **Flow erosion:** less (carrying capacity × (1 − 0.9v)). **Deposition:** more (settling length × (1 − 0.8v), so patches trap sediment). **Creep:** faster (× (1+v), from burrowing and roots) | |
| Boundaries | Top, left and right closed; **bottom open**, draining to a channel held at a fixed height just beyond the last row | Everything that leaves (by creep or by water) is counted in `sediment_exported_m3`. There is no uplift. |
| Numerical scheme | Creep is updated explicitly in a mass-conserving way, sub-stepped to stay stable (limit 0.2). Each storm's water and sediment routing is solved exactly as a sparse system, factorised once per step | Sediment balance is exact: about 1e-12 % error. |
| `--dt-scale` | Steps are scaled. With 0.5, each storm is split into 2 half-duration pieces, with the slope recomputed between them | Splitting by duration keeps runoff the same, so halving the step changes little. |

## 2. Command and telemetry

```
taskset -c 0 python3 sim.py --seed 42 --out out42      # 16.4 s wall time
```
```json
{"seed": 42, "grid_shape": [120, 100], "cell_size_m": 2.0, "years_simulated": 1000.0,
 "timesteps": 1000, "dt_years": 1.0, "storm_count": 19987, "mean_annual_rain_mm": 240.3469436894399,
 "creep_diffusivity_m2_per_yr": 0.005, "open_boundaries": ["bottom"],
 "sediment_exported_m3": 229.60535602726094, "uplift_or_baselevel_m3": 0.0,
 "mass_balance_error_pct": 8.319154610111529e-13}
```
Outputs are in `out42/`: [map.png](out42/map.png) and [map.html](out42/map.html) (1.7 MB).

## 3. Where each process is in `sim.py`

1. **Creep:** `creep_step`, [lines 114–141](sim.py#L114-L141).
2. **Overland-flow erosion and deposition:**
   - routing: `d8_receivers` and `Network`, [lines 144–214](sim.py#L144-L214)
   - erosion and deposition: `overland_flow_event`, [lines 227–248](sim.py#L227-L248)
3. **Random storms:**
   - generation: `make_storms`, [lines 103–108](sim.py#L103-L108)
   - applying each storm and splitting it into pieces: `simulate`, [lines 283–299](sim.py#L283-L299)
4. **Vegetation:**
   - pattern: `make_vegetation`, [lines 92–100](sim.py#L92-L100)
   - effects on each process: `simulate`, [lines 255–261](sim.py#L255-L261)

## 4. What I checked by running something, and what I didn't

**Checked by running:**
- **Timing:** about 16 s for the full run with maps on one core (`taskset -c 0`); 7 s with `--no-map`; 16 s with `--no-map --dt-scale 0.5`.
- **Same seed, same result:** two identical runs gave bit-identical `z_final`.
- **`--z0`:** the file is used exactly as given; vegetation and storms are identical with and without `--z0`.
- **Storm list:** `storms.csv` is unchanged by `--rain-scale`.
- **Bare ground:** `--veg-scale 0` gives zero cover.
- **No rain:** `--rain-scale 0` runs creep only (no flow events computed).
- **Mass balance:** error below 1e-12 % in every run.
- **Halving the time step:** the difference in the elevation-change map, as a share of the change itself (relative L2):

  | Run | Difference | Sediment exported (dt 1 → 0.5) |
  |---|---|---|
  | Default | 1.4% | 230 → 234 m³ |
  | Planar `--z0` | 0.75% | 732 → 732 m³ |
  | Rough `--z0`, bare | 4.6% | 13,778 → 13,714 m³ |
  | Rain × 2 | 6.3% | 1,654 → 1,683 m³ |
  | Default surface, bare | 17% | 24,248 → 25,031 m³ |

- **How I tested the page (no browser available):**
  - I ran the page's actual script in Node with a small stand-in for the browser page ([test_html.js](test_html.js)).
  - It drove every control: the 4 layer buttons at 3 time points each, the bare-ground toggle, Play, and the hover readout. Each produced a valid image and legend, and the readout gave sensible values.
  - A Python scan found no `http`, `www` or CDN addresses, including inside the decoded embedded PNGs (I removed matplotlib's web address from the image metadata).
  - The 7 `data-bench` controls are present and the file is 1.7 MB.
  - I looked at `map.png` myself.

**Not checked:**
- How the HTML actually looks in a real browser (layout, image scaling, hover position).
- Whether the erosion rates match measured field rates; they were calibrated by judgement only.
- The citations are from memory, not looked up.

## 5. What I couldn't do

- **Gully positions on bare ground:** with no plants, halving the step changes the change map by 17%, because which cells become gullies is sensitive to small differences. Totals still agree within about 3%. Recomputing flow paths before every storm didn't help (still 14%) and was too slow, so I didn't keep it.
- **Bare-ground colours:** the bare-ground comparison on the page uses the vegetated run's colour scale (±0.5 m), so the deepest bare-ground gullies (up to 4.2 m) all show at the darkest colour. The page says so.
- **Not modelled:** vegetation never grows, dies or gets buried; there is no bedrock or soil-production limit; and creep is linear (no extra speed-up on steep slopes).
