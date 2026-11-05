"""Check that D4C.dbscan (site/js/day04core.js) reproduces scikit-learn DBSCAN on real flashes.
Run: python3 -I day-04/tests/dbscan_vs_sklearn.py   (needs numpy and scikit-learn; node on PATH)
Compares, for three parameter sets, labels (exact and after mapping), adjusted Rand index and core masks."""
import json, os, subprocess, sys, tempfile
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.metrics import adjusted_rand_score

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CORE = os.path.join(ROOT, "site", "js", "day04core.js")
GLM = os.path.join(ROOT, "site", "data", "day04_glm.js")

with open(GLM) as fh:
    txt = fh.read()
d = json.loads(txt[txt.index("{", txt.index("window.D4GLM")):txt.rindex("}") + 1])
f = d["flash"]
x = np.array(f["x"], float) / 100.0      # km
y = np.array(f["y"], float) / 100.0
t = np.array(f["t"], float) / 600.0      # minutes
sets = [dict(eps=5.0, tScale=1.0, minPts=5), dict(eps=10.0, tScale=1.0, minPts=10), dict(eps=15.0, tScale=1.0, minPts=5)]

JS = r"""
const C = require(process.argv[2]); const fs = require('fs');
const inp = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = inp.sets.map(p => { const r = C.dbscan(Float64Array.from(inp.x), Float64Array.from(inp.y), Float64Array.from(inp.t), p);
  return { labels: Array.from(r.labels), core: Array.from(r.core), k: r.k }; });
fs.writeFileSync(process.argv[4], JSON.stringify(out));
"""
ok = True
with tempfile.TemporaryDirectory() as tmp:
    inp, outp, js = (os.path.join(tmp, n) for n in ("in.json", "out.json", "run.js"))
    with open(inp, "w") as fh:
        json.dump(dict(x=x.tolist(), y=y.tolist(), t=t.tolist(), sets=sets), fh)
    with open(js, "w") as fh:
        fh.write(JS)
    subprocess.run(["node", js, CORE, inp, outp], check=True)
    with open(outp) as fh:
        res = json.load(fh)
    for p, r in zip(sets, res, strict=True):
        X = np.column_stack([x, y, t * p["tScale"]])
        m = DBSCAN(eps=p["eps"], min_samples=p["minPts"]).fit(X)
        sk = m.labels_; skcore = np.zeros(len(x), int); skcore[m.core_sample_indices_] = 1
        jl = np.array(r["labels"]); jc = np.array(r["core"])
        ari = adjusted_rand_score(sk, jl)
        core_same = bool((skcore == jc).all())
        # label-by-label after mapping: each sklearn cluster maps to exactly one JS cluster, noise to noise
        mapping, mapped_ok = {}, True
        for a, b in zip(sk, jl, strict=True):
            if mapping.setdefault(a, b) != b: mapped_ok = False
        mapped_ok = mapped_ok and mapping.get(-1, -1) == -1 and len(set(mapping.values())) == len(mapping)
        exact = bool((sk == jl).all())
        k_sk = int(sk.max()) + 1
        good = ari == 1.0 and core_same and mapped_ok and r["k"] == k_sk
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {p}: k sklearn {k_sk} js {r['k']}, noise {int((sk == -1).sum())}, "
              f"ARI {ari:.6f}, cores {int(skcore.sum())} identical {core_same}, mapped-identical {mapped_ok}, numbering-identical {exact}")
sys.exit(0 if ok else 1)
