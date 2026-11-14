"""Day 14: gather the exploratory analysis for the page into one JSON, plus sweep thumbnails.

Reads runs/base_2mm, runs/grid_{1,4}mm, runs/sweep/*, data/derived/photo_metrics.*.
Writes OUT/eda.json and OUT/thumbs/*.jpg (OUT defaults to ../site/data/day14).
Rill spacing: transect length over pale crossings on the flanks (40 to 140 mm either side of the axis, x 300 to
1100 mm), counted across and along the tub; the smaller spacing is reported (photo pale mask, model bare mask).
Run: python -I scripts/build_eda.py [OUT]
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import model_metrics, score  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "site" / "data" / "day14"


def model_pale_1mm(run):
    """Channels in a model run: mud thinner than 70 % of its 6 mm neighbourhood (a relative test, like the
    photo's 'paler than the neighbourhood' mask)."""
    H = np.load(run / "fields.npz")["H"].astype("f8")
    up = int(round(1280 / H.shape[1]))
    Hm = nd.zoom(H, up, order=1)[:520, :1280] if up > 1 else H[:520, :1280]
    return Hm < 0.7 * nd.gaussian_filter(Hm, 6)


def spacing(pale):
    """Mean spacing of pale channels on the flanks: crossings per mm along transects in both directions
    (across and along the tub); the direction with more crossings is the one cutting across the channels."""
    out = []
    for cross in (True, False):
        n_tot, l_tot = 0, 0
        for lo, hi in ((120, 220), (300, 400)):
            if cross:
                for x in range(300, 1101, 25):
                    col = pale[lo:hi, x].astype(int)
                    n_tot += int((np.diff(col) == 1).sum()); l_tot += hi - lo
            else:
                for y in range(lo, hi, 10):
                    row = pale[y, 300:1100].astype(int)
                    n_tot += int((np.diff(row) == 1).sum()); l_tot += 800
        out.append(l_tot / n_tot if n_tot else None)
    vals = [v for v in out if v]
    return round(float(min(vals)), 1) if vals else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "thumbs").mkdir(exist_ok=True)
    photo = json.loads((ROOT / "data/derived/photo_metrics.json").read_text())
    ph = np.load(ROOT / "data/derived/photo_metrics.npz")
    eda = {"photo": {"pale_frac": round(photo["pale_frac"], 3), "along": photo["along"], "across": photo["across"],
                     "rose": photo["rose"], "spacing_mm": spacing(ph["pale"] & ph["mask"])},
           "along_x_mm": photo["along_x_mm"], "across_y_mm": photo["across_y_mm"], "rose_bins_deg": photo["rose_bins_deg"]}
    base = RUNS / "base_2mm"
    bm = model_metrics(base)
    meta = json.loads((base / "meta.json").read_text())
    eda["base"] = {"pale_frac": round(bm["pale_frac"], 3), "along": bm["along"], "across": bm["across"], "rose": bm["rose"],
                   "score": score(bm, photo), "spacing_mm": spacing(model_pale_1mm(base)), "args": meta["args"],
                   "t_end_s": meta["t_end_s"], "drawdown": meta["log"]}
    grid = []
    for name, dx in (("grid_1mm", 1), ("base_2mm", 2), ("grid_4mm", 4)):
        run = RUNS / name
        if not (run / "fields.npz").exists():
            continue
        m = model_metrics(run)
        grid.append({"dx_mm": dx, "pale_frac": round(m["pale_frac"], 3), "spacing_mm": spacing(model_pale_1mm(run)),
                     "score": score(m, photo)["total"]})
    eda["grid"] = grid
    sweep = []
    for run in sorted((RUNS / "sweep").glob("K*_Kr*")):
        if not (run / "fields.npz").exists():
            continue
        a = json.loads((run / "meta.json").read_text())["args"]
        m = model_metrics(run)
        s = score(m, photo)
        H = np.load(run / "fields.npz")["H"]
        v = np.clip(H / np.percentile(H, 98), 0, 1)
        rgb = np.stack([246 - v * 188, 241 - v * 201, 230 - v * 200], -1).astype("uint8")
        Image.fromarray(rgb).resize((320, 130), Image.LANCZOS).save(OUT / "thumbs" / f"{run.name}.jpg", quality=82)
        sweep.append({"name": run.name, "K": a["K"], "Kr": a["Kr"], "pale_frac": round(m["pale_frac"], 3),
                      "along": [round(x, 3) for x in m["along"]], "score": s})
    eda["sweep"] = sweep
    # the three best-scoring sweep runs, to show they look different
    best = sorted(sweep, key=lambda r: r["score"]["total"])[:3]
    eda["equifinal"] = [b["name"] for b in best]
    (OUT / "eda.json").write_text(json.dumps(eda, separators=(",", ":")))
    print(json.dumps({"photo_spacing": eda["photo"]["spacing_mm"], "base": eda["base"]["score"],
                      "base_spacing": eda["base"]["spacing_mm"], "grid": grid, "best": [(b["name"], b["score"]["total"]) for b in best]}, indent=1))


if __name__ == "__main__":
    main()
