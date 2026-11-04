# Day 3 · Polygons: lines on a known world

An interactive lab on the modifiable areal unit problem, on simulated data. Two Gaussian random fields, X and Y, cover a 51.2 km square (256 by 256 cells of 200 m). Because the world is simulated, the true answer to each question is known. Choose a question (a mean, the share of variance between zones, a correlation, the share above a threshold, a zone ranking), a set of polygons (grid, hexagons, random Voronoi, Voronoi of the sites) and a way of placing sites (every cell, random with an optional preference, systematic, stratified by zone), and see how far the answer lands from the truth. Replicates redraw the world, the sites or the zoning, one at a time, to show where the spread comes from.

Live: <https://cordilleran.github.io/MapChallenge2026/day-03.html>

## Files

- `site/js/day03simcore.js`: the engine (no DOM): FFT simulation of Matérn fields on a torus (circulant embedding), zones, sampling designs, estimands, replicates, and Krige's expected between-zone share. It also holds a watershed world that the page does not use yet (held for a later day).
- `site/js/day03simworker.js`: runs replicates, scale curves and offset sweeps in a Web Worker.
- `site/js/day03sim.js`: the page: map, controls, charts, readouts, formulas, settings as JSON.
- `site/day-03.qmd`: the page text.
- `tests/sim_smoke.js`, `tests/sim_theory.js`: engine checks under node (census mean equals the truth under every zoning; Krige's curve and the input variogram match the simulation).
- `tests/smoke_sim.py`: drives the built page in headless Chromium.
- The first version on real snow data is kept outside this repo for a later day.

## Reproduce

```
pip install -r day-03/requirements.txt          # websocket-client, for smoke_sim.py only
node day-03/tests/sim_smoke.js
node day-03/tests/sim_theory.js
(cd site && quarto render day-03.qmd)
python3 -m http.server 8766 -d site/_site       # run in a separate terminal
python3 day-03/tests/smoke_sim.py http://127.0.0.1:8766/ /tmp/day03-shots
fuser -k 8766/tcp                               # stop the server when done
```

The node tests exit 1 if an invariant breaks (census mean equals the truth under every zoning; Krige's curve within 0.03 of the simulated share; the empirical variogram within 0.06 of its input).

## Limits

Stationary fields (the same recipe everywhere). The correlation counts each zone once, not by area. Hexagons and Voronoi zones are staircased on the 200 m cells. Every number is simulated in the browser; nothing here describes a real place.
