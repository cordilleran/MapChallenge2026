"""Score a run against the photo: pale fraction, along-axis and across profiles, orientation roses by zone."""
import json, sys
from pathlib import Path
import numpy as np
from scipy import ndimage as nd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from photo_metrics import metrics, structure_orientation  # noqa: E402
ROOT = Path(__file__).resolve().parents[1]


def model_metrics(run, thresh_frac=0.3):
    d = np.load(Path(run) / "fields.npz")
    H, r = d["H"].astype("f8"), d["r"]
    dx_mm = 1280 / H.shape[1]
    up = int(round(dx_mm))
    Hm = nd.zoom(H, up, order=1)[:520, :1280]
    rm = nd.zoom(r, up, order=1)[:520, :1280]
    mask = rm < 0.97
    ref = np.median(H[(r < 0.97) & (H > 0)])
    pale = Hm < thresh_frac * ref
    theta, coh = structure_orientation(-Hm / (ref + 1e-12))
    return metrics(pale, theta, coh, mask, 1.0)


def score(m, p):
    al = np.nanmean(np.abs(np.array(m["along"]) - np.array(p["along"])))
    ac = np.nanmean(np.abs(np.array(m["across"]) - np.array(p["across"])))
    ro = np.mean([np.abs(np.array(m["rose"][k]) - np.array(p["rose"][k])).sum() / 2 for k in p["rose"]])
    return {"pale_err": round(abs(m["pale_frac"] - p["pale_frac"]), 3), "along_mae": round(float(al), 3),
            "across_mae": round(float(ac), 3), "rose_tv": round(float(ro), 3),
            "total": round(float(abs(m["pale_frac"] - p["pale_frac"]) + al + ac + ro), 3)}


if __name__ == "__main__":
    p = json.loads((ROOT / "data/derived/photo_metrics.json").read_text())
    for run in sys.argv[1:]:
        m = model_metrics(run)
        s = score(m, p)
        (Path(run) / "score.json").write_text(json.dumps({"score": s, "metrics": m}, indent=1))
        print(run, round(m["pale_frac"], 3), s)
