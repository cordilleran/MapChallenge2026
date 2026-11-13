<!-- The agent's final reply, verbatim except that local file paths are shortened. -->
### Testing the Interactive Page Without a Browser

Because no interactive browser is available in this environment, [`map.html`](output/map.html) was verified through automated programmatic checks:
1. **Offline & Zero-CDN Verification**: Inspected the HTML file with regular expressions to confirm zero external URLs (`http://`, `https://`, CDN fonts, or external stylesheets). The file is completely self-contained and weighs 652 KB (well under the 5 MB limit).
2. **Benchmark Attributes**: Verified the presence of required `data-bench` attributes across all interactive elements (`layer-terrain`, `layer-change`, `layer-vegetation`, `layer-flow`, `layer-select`, `time-slider`, `time-before`, `time-after`, `time-play`, `vertical-exaggeration`, `sun-azimuth`, `layer-opacity`, `toggle-shading`, `toggle-contours`).
3. **Headless JavaScript Engine Validation**: Extracted the `<script>` payload and validated syntax using `node -c`. Ran the script under Node.js v22 with mock DOM and canvas `ImageData` objects to confirm that the relief shading calculations, color ramps, time scrubbing, and hover probe listeners execute without errors.

---

### Vegetation Feedback on Processes

In dryland environments, vegetation cover $V \in [0, 1]$ modulates each process as follows:
- **Hillslope Creep (Soil Diffusion)**: **Reduces creep** ($D(V) = D_0 / (1 + 2V)$). Shrub canopies intercept raindrops, reducing splash detachment, while root networks anchor soil aggregates, suppressing dry ravel and surface disturbance.
- **Overland Flow Erosion**: **Reduces detachment and transport capacity** ($T_c \propto 1 / (1 + c_{veg} V)$). Rigid stems and roots increase surface roughness (Manning's $n$), dissipating boundary shear stress and increasing erosion resistance.
- **Storm Infiltration & Runoff Generation**: **Reduces surface runoff** ($Q_w = A \cdot P \cdot (1 - 0.4V)$). Shrub patches increase infiltration capacity and organic matter content, diverting rainfall into the subsurface.
- **Sediment Deposition**: **Promotes deposition**. When sediment-laden runoff enters dense vegetation clumps, flow decelerates and transport capacity drops below incoming sediment load, triggering deposition and forming vegetated sediment mounds / micro-terraces.

---

### 1. Main Assumptions and Reasoning

| Domain | Assumption | Line of Reasoning / Citation |
| :--- | :--- | :--- |
| **Soil** | Cohesionless to weakly cohesive regolith with linear diffusive creep at low slopes ($D_0 = 0.005\text{ m}^2/\text{yr}$) | Standard representation of dryland rainsplash and dry ravel (Culling 1960; Roering et al. 1999). |
| **Rain** | Episodic convective storms sampled from a Gamma distribution ($k=2, \theta=12.5$, mean $\sim 19.5\text{ mm}$) | Convective thunderstorm bursts govern overland flow and geomorphic work in arid catchments (Wolman & Miller 1960; Eagleson 1978). |
| **Vegetation** | Patchy shrub clusters separated by bare inter-spaces, generated via smoothed spatial noise | Water-limited dryland ecosystems self-organize into spotted or banded vegetation mosaics (Puigdefábregas 2005). |
| **Equations** | Coupled Culling diffusion and stream-power transport capacity ($T_c \propto Q_w S$) with local deficit entrainment and excess deposition | Classic transport-capacity / detachment-limited exchange formulation for hillslope erosion (Howard 1994; Tucker & Bras 2000). |
| **Boundaries** | Closed (no-flux) for top, left, and right; open for bottom edge (row 99) | Simulates a hillslope draining from an upper drainage divide down to an axial valley or base-level outlet. |
| **Numerical Scheme** | Finite-volume face fluxes for diffusion; single-pass topological accumulation on a D8 directed graph with priority-flood pit filling | Finite-volume cell transfers mathematically conserve sediment volume to machine precision ($\sim 10^{-15}\%$ error). |

---

### 2. Command Executed and Output Telemetry

Command run:
```bash
python3 sim.py --seed 42 --out output
```

Printed telemetry (`output/telemetry.json`):
```json
{
  "seed": 42,
  "grid_shape": [
    100,
    100
  ],
  "cell_size_m": 1.0,
  "years_simulated": 200,
  "timesteps": 200,
  "dt_years": 1.0,
  "storm_count": 200,
  "mean_annual_rain_mm": 19.4815,
  "creep_diffusivity_m2_per_yr": 0.005,
  "open_boundaries": [
    "bottom"
  ],
  "sediment_exported_m3": 117.5411,
  "uplift_or_baselevel_m3": 0.0,
  "mass_balance_error_pct": 3.854838822065845e-15
}
```

Generated files in [`output/`](output):
- [`z_initial.npy`](output/z_initial.npy)
- [`z_final.npy`](output/z_final.npy)
- [`vegetation.npy`](output/vegetation.npy)
- [`storms.csv`](output/storms.csv)
- [`telemetry.json`](output/telemetry.json)
- [`map.png`](output/map.png)
- [`map.html`](output/map.html)

---

### 3. Implementation of the Four Processes in `sim.py`

- **Process 1: Hillslope Creep (Soil Diffusion)**  
  Implemented in `simulate_hillslope`: [sim.py#L213-L239](sim.py#L213-L239). Computes finite-volume diffusive fluxes across internal faces modulated by vegetation, enforces no-flux at top/left/right boundaries, and exports creep sediment crossing the bottom boundary.
- **Process 2: Overland Flow Erosion, Transport, and Deposition**  
  Implemented in `simulate_hillslope`: [sim.py#L241-L316](sim.py#L241-L316). Routes contributing area downhill, evaluates local transport capacity $T_c$, deposits excess sediment when flow is over-capacity ($Q_{s,in} > T_c$), and detaches sediment up to capacity when flow is under-capacity.
- **Process 3: Random Storms of Varying Size**  
  Implemented in `generate_storms`: [sim.py#L71-L85](sim.py#L71-L85) (stochastic event depths) and `simulate_hillslope`: [sim.py#L201-L210](sim.py#L201-L210) & [sim.py#L290](sim.py#L290) (event grouping, sub-step division, and runoff generation).
- **Process 4: Patchy Vegetation Dynamics**  
  Implemented in `generate_vegetation`: [sim.py#L51-L68](sim.py#L51-L68) (correlated shrub cluster generation) and coupled in `simulate_hillslope`: [sim.py#L198](sim.py#L198), [sim.py#L290](sim.py#L290), [sim.py#L293](sim.py#L293), and [sim.py#L304](sim.py#L304).

---

### 4. Verification Record

**Verified by running tests:**
- Full default run: completed in 3.8 seconds with maps (allowed: 240 seconds).
- Fast run with `--no-map`: completed in 2.2 seconds (allowed: 60 seconds).
- Time-step halving (`--dt-scale 0.5`): completed 400 steps in 4.5 seconds (allowed: 120 seconds); mean elevation difference from default is 0.016 mm (0.05% of mean change), confirming numerical stability.
- Zero rain (`--rain-scale 0`): confirmed zero overland erosion, with only diffusive creep acting and exact preservation of `storms.csv`.
- Zero vegetation (`--veg-scale 0`): confirmed bare ground array (`vegetation.npy` all zeros) with increased sediment export (172.0 m³ vs. 117.5 m³).
- Custom starting surface (`--z0`): tested with an external surface containing flat spots and depressions; confirmed automatic priority-flood drainage, exact volume conservation, and strict seed independence for vegetation and storms.
- Offline integrity: confirmed zero external URLs in [`map.html`](output/map.html), verified size (0.65 MB < 5 MB), validated all `data-bench` attributes, and verified JavaScript execution in Node.js.

**Not verified by execution:**
- Empirical field calibration of diffusivity and erodibility values against a specific real-world arid catchment (parameters were drawn from published geomorphic literature values).

---

### 5. Limitations

- **Visual browser inspection**: A live web browser was not available to visually inspect canvas rendering or perform interactive mouse clicks in real time; all verification was completed via headless Node.js execution and DOM inspection scripts.
- **Subsurface hydrological routing**: The model simulates Hortonian infiltration-excess overland flow; it does not model 3D groundwater water-table dynamics or perched aquifer flow.
