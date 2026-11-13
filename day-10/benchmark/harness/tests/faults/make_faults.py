"""Write the reference, its seven faulty copies and three correct variants as runs, ready for evaluate_v2.py.

Usage: make_faults.py RUNS_DIR

Each fault should be caught by its target check; the reference and each variant should pass everything.
"""
import json, sys
from pathlib import Path

REF = Path(__file__).resolve().parents[1] / "reference" / "sim_reference.py"
FAULTS = {  # fault: (what it does, the check that must catch it)
    "ref": ("none", None),
    "F1": ("sediment deleted, export set to the remainder", "C3/C2/A4"),   # C3 only bites if the entry routes inside closed hollows
    "F2": ("no creep", "C1"),
    "F3": ("vegetation ignored", "C8"),
    "F4": ("steady rain", "B1"),
    "F5": ("deposits placed at random", "A2/A3/A5"),
    "F6": ("step-dependent storms: a step's runoff lumped into one pulse", "C9"),
    "F7": ("routing favours one side", "C5"),
}
VARIANTS = {  # correct but different models: each must pass every check (B11)
    "V1": "wash ten times stronger",
    "V2": "creep five times weaker",
    "V3": "a wash detachment threshold, wash five times stronger above it",
}

if __name__ == "__main__":
    runs = Path(sys.argv[1]); src = REF.read_text()
    for f, (what, target) in FAULTS.items():
        d = runs / f"fixture-{f}"
        (d / "work").mkdir(parents=True, exist_ok=True)
        code = src if f == "ref" else src.replace("FAULT = None", f'FAULT = "{f}"', 1)
        assert f == "ref" or f'FAULT = "{f}"' in code
        (d / "work" / "sim.py").write_text(code)
        (d / "run.json").write_text(json.dumps({"harness": "fixture", "model": "reference", "fault": f, "fault_does": what,
                                                "must_fail": target, "exit": 0, "wall_s": 0}, indent=1))
        (d / "stream.ndjson").write_text("")
    for v, what in VARIANTS.items():
        d = runs / f"fixture-{v}"
        (d / "work").mkdir(parents=True, exist_ok=True)
        code = src.replace("VARIANT = None", f'VARIANT = "{v}"', 1)
        assert f'VARIANT = "{v}"' in code
        (d / "work" / "sim.py").write_text(code)
        (d / "run.json").write_text(json.dumps({"harness": "fixture", "model": "reference", "variant": v, "variant_does": what,
                                                "must_fail": None, "exit": 0, "wall_s": 0}, indent=1))
        (d / "stream.ndjson").write_text("")
    print("wrote", len(FAULTS) + len(VARIANTS), "fixtures to", runs)
