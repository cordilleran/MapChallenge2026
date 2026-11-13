# The Day 10 benchmark: one assignment, several AI coding agents

Before the Day 10 page was built, its assignment went to AI coding agents as a one-shot test (10 to 12 November 2026). Each agent had to write `sim.py`, a dryland hillslope simulator with soil creep, wash with deposition, random storms and patchy vegetation, plus a map page for a student. A harness then ran each script in a sealed container and checked the physics from the saved grids, without trusting what the script reported about itself. The page's last section tells the story; this folder holds the material.

| Path | What it is |
| :--- | :--- |
| `prompts/python_prompt_v2.md` | The assignment as the agents received it (version 2). `python_prompt.md` is version 1, used in round 1. The `*_homework.md` files are the same prompts with `homework_appendix.md` added, for runs pasted into a chat by hand; `html_prompt.md` asks for an app without Python. |
| `harness/` | The scoring harness. `evaluate_v2.py` runs an entry on its default surface and on the test surfaces in `surfaces.py` (scarp, ramp, closed bowl, mirror, hillslope), then applies the checks in `checks_arrays.py` and `checks_runs.py`. `routing.py` is the harness's own flow routing. `run_agents.py` launched the agents; it writes to `runs/` beside `harness/` unless `BENCH_RT` is set. `Dockerfile` and `Dockerfile.landlab` build the container (no network, one CPU, 2 GB). |
| `harness/tests/reference/sim_reference.py` | A small reference simulator, a test fixture rather than an answer key. `tests/faults/` makes deliberately broken copies of it (`fault_matrix.md`); every one must fail at least one check. |
| `entries/<name>/` | Each entry: `sim.py` as written, `result_v2.json` (every check's values and the failed list), `final_reply.md` (the agent's own description of its model, with local paths shortened) and `run.json`. |

Entries: `agy-argon4` (Gemini 4 Argon in Antigravity, round 1), `cc-opus55` and `agy-opus55` (Opus 5.5 in Claude Code and in Antigravity), `agy-flash38` (Gemini 3.8 Flash), `agy-hydrogen4` (Gemini 4 Hydrogen), `landlab-ref`, `landlab-s2b` and `landlab-gully` (the Landlab build at three stages; the last is the page's `sim.py`). One run per entry: a data point, not a ranking.

The entries are AI-generated test subjects, published as the agents wrote them, bugs included, so the scores can be checked. They are released under this repository's MIT licence; the model, tool and date of each are in its `run.json`.

To score an entry: build the image (`docker build -t geo-bench:py314 -f harness/Dockerfile harness`, or `Dockerfile.landlab` for Landlab entries with `BENCH_IMAGE=geo-bench:landlab`). Make `RUNS/<cell>/` with the entry's `sim.py` in `work/` and its `run.json` beside it (copy one from `entries/<name>/`; cells without `run.json` are skipped). Then run `python harness/evaluate_v2.py RUNS <cell>`. The host needs NumPy, SciPy and matplotlib; screenshots of each entry's own page also need a headless Chromium (`evaluate.py`, written for Ubuntu's snap build).

**Two steps are not sandboxed; read before rerunning.** `run_agents.py` starts the agents on the host with their permission prompts switched off (`--dangerously-skip-permissions` for Antigravity), with network and the user's own environment: run it only in a disposable machine or account. The screenshot step in `evaluate.py` opens each entry's AI-written `map.html` in Chromium on the host with Chromium's own sandbox off. Running the simulators, which is the scoring itself, happens inside the container.

Comments in the harness cite decision ids (B1 to B14) and review notes from the author's working notes, which are not published; the page's benchmark section tells the same story in full.
