<!-- The agent's final reply, verbatim except that local file paths are shortened. -->
`sim.py` is written and tested. It runs in about 27 s on one core and writes exactly the five files. I also ran seed 7 and re-ran seed 42; the repeat gave byte-identical `z_final.npy` and `map.html`.

I checked `map.png` by eye. I could not open `map.html` in a browser, because running Firefox was not permitted here. Instead I ran its script under node against a stub DOM, and all four layers drew without errors. How it looks and behaves in a real browser is untested. It contains no web addresses.

## 1. Assumptions

| Area | Choice | Reasoning |
|---|---|---|
| Grid | 100×100 cells at 6 m, so 600 m × 600 m; 30 m of relief | Meets the size minimum. A hillslope-scale domain is where creep and overland flow both matter. |
| Initial surface | Convex divide, concave foot (z = 30·(1−s)^1.6), shallow hollows, roughness from the seed | Gives a ridge, a steep middle and a gentle foot. The hollows focus flow so rills can form. |
| Time | 5000 yr in 250 steps of 20 yr | Long enough for metre-scale change at dryland rates, and cheap enough for 9 runs. |
| Creep | Linear diffusion, D = 0.008 m²/yr, explicit | Within the usual semi-arid range (~10⁻³–10⁻² m²/yr). Stability number is DT·D/dx² ≈ 0.004, far below 0.25. |
| Rain | About 20 storms/yr, gamma-distributed depth (mean 12 mm, shape 0.8), Poisson counts per step | Many small storms and a few big ones, about 240 mm/yr. Each step's storms are grouped into 12 size classes, with the biggest storms kept distinct. |
| Runoff | Infiltration excess: 6 mm on bare crusted soil, up to +14 mm under full vegetation | Dryland runoff is mostly infiltration-limited. This makes large storms disproportionately effective. |
| Vegetation | Contour-parallel bands from a smoothed random field, thresholded to a cover fraction (35% baseline). Held fixed in time. | Banded patches are typical of drylands. Vegetation cuts detachment (×exp(−3.5v)), cuts transport capacity (×exp(−1.5v)) and raises infiltration. |
| Flow routing | Pit-filling by priority-flood with epsilon, then D8 steepest descent. Accumulation is an exact sparse solve per storm class. | Every cell drains and the flow graph has no loops. |
| Erosion | Detachment depth = K·g(v)·Σ w·q^1.2·S, with q the discharge per unit width and S the slope | Stream-power form. The K values were tuned by hand to give mm/yr-scale lowering, not taken from a source. |
| Transport and deposition | Capacity = K_t·Σ w·q^1.5·S^1.2. Load above capacity settles (40% per cell). Erosion is capped at 50% and deposition at 30% of the drop to the downslope neighbour. | Sediment is carried in m³ cell to cell, and nothing is deleted. Deposits form where slope or flow falls, such as the foot and behind vegetation. The caps keep each step stable. |
| Boundaries | Bottom edge is a fixed base-level row and is open. The other three edges are closed. No uplift. | All exported sediment is counted. This is flow exiting plus creep into the boundary row. |
| Scenarios | 3 storminess levels × 3 cover levels, computed with the same landscape and the same storm sequence | The HTML sliders switch between these 9 precomputed runs. The baseline is the main output. |
| Mass check | (net grid volume change + exported) ÷ gross eroded volume | The bookkeeping is independent of the grid. The error is rounding only. |

I'm not citing sources. The ingredients are standard ones: stream-power erosion, linear creep, priority-flood filling and D8 routing. The specific constants are my own choices.

## 2. Command and telemetry

```
python3 sim.py --seed 42 --out run42
```
```json
{
  "seed": 42,
  "grid_shape": [100, 100],
  "cell_size_m": 6.0,
  "years_simulated": 5000.0,
  "timesteps": 250,
  "open_boundaries": ["south"],
  "sediment_exported_m3": 8276.688902860229,
  "uplift_or_baselevel_m3": 0.0,
  "max_erosion_m": 1.8696280223849007,
  "max_deposition_m": 0.8413539036743432,
  "mass_balance_error_pct": 1.160544935412536e-13
}
```
- **Volumes:** gross eroded was 42,319 m³ and gross deposited 34,642 m³. The net grid change was −8,277 m³, matching the exported volume.
- **Sanity check on `max_erosion_m`:** the 1.87 m maximum is a local value at gully heads, well above the 99.5th-percentile scale of about 0.86 m that the map uses.

## 3. What I could not do or verify

- **Browser test:** I couldn't open `map.html` in a browser, as noted above, so layout and the play button are unchecked in practice.
- **Parameter controls:** storminess and vegetation cover are precomputed. The model runs in Python and is not reimplemented in the browser, and the page says so.
- **Calibration:** nothing is calibrated to a real site. Erosion rates are plausible in order of magnitude only.
- **Vegetation:** it is static, so it does not respond to erosion or rainfall. There is also no run-on infiltration, where runoff soaks in on a vegetated band.
- **Routing artefacts:** D8 routing leaves visible grid-aligned flow lines in the Flow layer.
- **Edge stripes:** the Change map has thin stripes in the first and last rows. They are edge effects from the divide row and the fixed base-level row, not features.
- **`sim.py` is untested beyond Python:** I only ran it on the Python in this environment.