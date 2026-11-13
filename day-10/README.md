# Day 10: a dryland hillslope lab, built on Landlab

A teaching page for a 600 m mountain front under soil creep, storm sheetwash and patchy shrubs, with the physics done by [Landlab](https://landlab.csdms.io/) 2.11 components. The same assignment was a one-shot benchmark for AI coding agents first; the page tells that story in its last section.

| File | What it is |
| :--- | :--- |
| `sim.py` | The simulator, on the benchmark's v2 contract: `python sim.py --seed 42 --out DIR [--z0 F] [--rain-scale F] [--veg-scale F] [--dt-scale F] [--no-map]`. Writes seven files and the 13 telemetry keys, plus a few of its own (wash and creep export, runon soaked up). |
| `build_page.py` | Runs seven 4,000-year scenarios (baseline, rain ×0.5 and ×2, cover ×0 and ×2, wash exponent m 0.5 and 1) and packs them into `app/index.html`. `sim.py` alone runs 2,000 years unless `D10_YEARS` is set. `--repack` rebuilds the page from saved data and rereads the benchmark verdicts from `benchmark/entries/`; the site copy is `--repack --root ../ --out ../site/day10/index.html`. |
| `app/template.html` | The page: HTML, CSS and JavaScript, no libraries. The data is inlined at build, so the page works offline. |
| `tests/test_runon.py` | Checks that `sim.runon()` gives the same discharge as Landlab's `LossyFlowAccumulator`. |
| `requirements.txt`, `requirements.in` | The full lock of the environment that ran and scored this build (Python 3.13, landlab 2.11.0), and the four direct dependencies. |
| `benchmark/` | The AI-agent benchmark that tested this assignment: the prompt, the scoring harness, and each entry's `sim.py`, scores and own description. See `benchmark/README.md`. |

## Processes

| Process | Done by |
| :--- | :--- |
| Storms | `PrecipitationDistribution` |
| Runoff and runon | written for this build: infiltration excess, then `LossyFlowAccumulator`'s rule, vectorised (`runon()`) |
| Routing | `FlowAccumulator`, D8; the default surface is pit-filled once with `SinkFillerBarnes` |
| Sheetwash | `ErosionDeposition`, E = K Q^m S with m 0.75 (K set so K Q^m is the same at a reference discharge for any m), erodibility and settling varying with shrub cover |
| Creep | `LinearDiffuser`, diffusivity varying with shrub cover |
| Shrub pattern | written for this build: a seeded, smoothed random field, fixed for the run |
| Starting surface | written for this build: a 30 % front over a 2 % apron, seeded roughness and five shallow hollows that taper downslope; pit-filled once |

## Run

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python sim.py --seed 42 --out runs/d42 --no-map        # 2,000 years (the benchmark default), about 30 s
.venv/bin/python build_page.py                                   # about 7 min; writes app/index.html (about 5 MB)
.venv/bin/python tests/test_runon.py                             # or pytest, if installed
```

Open `app/index.html` from this folder so the site fonts load from `../../site/fonts/`. View a set state with a hash, for example `index.html#scenario=m10&layer=change&year=4000&cell=70,60`; the page keeps the hash in step as you use it.

## Licence and credits

Code MIT ([`LICENSE`](../LICENSE)); the page, its images and the derived data inside it CC BY 4.0 ([`LICENSE-IMAGES.md`](../LICENSE-IMAGES.md)). There is no third-party data: the surface, shrubs and storms are synthetic, generated from the seed. Software: Landlab, NumPy, SciPy and matplotlib (see [`THIRD_PARTY.md`](../THIRD_PARTY.md)); references are listed in the page's "Sources and software" section. The benchmark entries in `benchmark/entries/` were written by the AI models named in each `run.json`; see `benchmark/README.md`.

Built by GW with Claude Code (Opus 5.5): GW set the questions and reviewed the work; a Claude Fable 5.2 review and a three-model code review (Sonnet 5.5, Gemini 4 Hydrogen, Gemini 4 Argon) were checked and applied before publishing.
