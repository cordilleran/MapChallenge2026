# Corpus geography app

The Day 9 page: a canvas map of where a library's papers are written and what they study, with an origin-region by setting table and a topic table that count every paper and filter the map. The design notes and decision log (D numbers in comments) are kept outside the repository; `../README.md` describes the method and the builds.

Plain JavaScript and canvas, no libraries, no build step.

| Path | What |
| :--- | :--- |
| `core.js` | Pure functions: contract loader, filter view, weights, setting splits, topic counts, line merging (bundling by nested cells), Equal Earth, great circles, nested zoom clustering |
| `app.js`, `app.css`, `index.html` | The map, controls, readouts, setting bar, key, region and topic tables, fold-outs |
| `data/day09.json` | The public data contract (coarsened; see `../README.md`, "Public and private builds") |
| `data/day09_private.json` | Cite keys and titles; local only, gitignored; the app lists papers for a selection only when it is present |
| `data/sim*.json`, `scripts/simulate.py` | A simulated corpus in the same contract (invented papers, real GeoNames places), for tests and for trying the app without the real corpus; the JSON files are committed, and regenerating them needs the local pipeline database |
| `data/world50.json`, `data/admin1/` | Natural Earth outlines (public domain) |
| `data/borders.json`, `data/admin1/*_lines.json` | Land-border lines and lakes from `scripts/18_border_lines.py` (Natural Earth, public domain) |
| `tests/core.test.mjs` | `npm test`: simulated totals reproduced exactly; weight invariants; setting splits; nested clusters; merged lines keep their weight at every zoom; topic selection |
| `serve.sh` | Serves on localhost and the Tailscale address only, port 8790 |

URL hash: `c=` corpus (`day09`, `sim`, `sim_b`), `s=` scopes, `dir=`, `o=` (all or corresponding authors), `b=0` (abstract only), `col=kind`, `t=` topic level, `sel=region:<name>` or `sel=<level>:<term>` for a table selection. Shift-click a scope to show only that one.
