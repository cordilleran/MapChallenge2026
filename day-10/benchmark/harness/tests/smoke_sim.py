"""Harness smoke test only: closed-boundary diffusion of a noisy ramp. Not a benchmark entry."""
import argparse, json
from pathlib import Path
import numpy as np, matplotlib.pyplot as plt
p = argparse.ArgumentParser(); p.add_argument("--seed", type=int); p.add_argument("--out"); a = p.parse_args()
o = Path(a.out); o.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(a.seed)
z0 = np.add.outer(np.linspace(50, 0, 100), np.zeros(100)) + rng.normal(0, .2, (100, 100)); z = z0.copy()
for _ in range(200):
    zp = np.pad(z, 1, mode="edge"); z = z + 0.2 * (zp[2:, 1:-1] + zp[:-2, 1:-1] + zp[1:-1, 2:] + zp[1:-1, :-2] - 4 * z)
np.save(o / "z_initial.npy", z0); np.save(o / "z_final.npy", z); dz = z - z0
json.dump({"seed": a.seed, "grid_shape": [100, 100], "cell_size_m": 1.0, "years_simulated": 200, "timesteps": 200,
           "open_boundaries": [], "sediment_exported_m3": 0.0, "uplift_or_baselevel_m3": 0.0,
           "max_erosion_m": float(-dz.min()), "max_deposition_m": float(dz.max()), "mass_balance_error_pct": 0.0}, open(o / "telemetry.json", "w"))
plt.imshow(dz, cmap="RdBu"); plt.savefig(o / "map.png")
(o / "map.html").write_text("<html><body><h1>smoke</h1><input type=range></body></html>")
