"""Separate the 1958 mosaic into its ink plates, one density-like byte raster per ink.

Input:  $MC26_DAY07_DATA/derived/htmc/sheets1958_utm15.tif (11_htmc_mosaic.py)
Output: $MC26_DAY07_DATA/derived/htmc/
        ink_<plate>.tif   byte 0-255, 0 = no ink; plates:
            line inks: black (lettering, culture, railways), red (roads), blue (drainage lines, water
                       lettering), brown (contours, incl. pit and dump contours)
            area tints: green (woodland), water (blue water tint), urban (orange built-up fill)
        inks_report.json  per-sheet reference colours, thresholds, plate shares over the frame
        check_<window>.png  original beside each plate, for three (+1) windows
Method (adapted from day-06/scripts/ink.py; optical density OD = -log10(I / reference)):
1. Lines first (step 3): pixels whose OD against a light local background exceeds LINE_MIN are
   line pixels; the rest are tint candidates.
2. Tints. OD of each non-line pixel (3 x 3 median) against the sheet's paper; one-ink fits against the sheet's green,
   water and urban reference colours; the best-fitting tint (or bare paper) wins, and its amount
   (1.0 = that sheet's reference tint) is the plate value. This is the per-sheet normalisation:
   each sheet's green plate is measured in units of its own woodland green, so Two Harbors' pale
   green and Ashland's saturated green both map to ~1.0.
   Paper and green: k-means (k=10, seeded) of each sheet's background; paper = the lightest
   cluster above 1.5 % share, green = the largest cluster whose OD against paper is blue-weighted
   (d_B > 0.45). Water: the 11 x 11 background median at a named lake of the sheet (WATER_AT).
   Urban: median of the cores of the orange fill (R > 200, 80 < G < 175, B < 90 over a whole 9 x 9
   block; whole sheet read at full resolution), pooled over all sheets where a sheet has fewer than 500.
   A tint is kept only when its fit leaves less than TINT_REL_RESID of the OD unexplained and its
   amount exceeds TINT_MIN_AMT; line pixels and unexplained pixels take the tint of the nearest
   classified pixel (the tint runs on under the line plates); pixels next to a line are not used as
   tint evidence. Each tint plate is then smoothed by a TINT_SMOOTH x TINT_SMOOTH median. Tint plate: 255 = TINT_FULL x reference.
3. Lines. OD of the pixel against a lighter local background (80th percentile per channel,
   11 x 11, as on Day 6: the median failed where wide red roads filled half the window), so a road over woodland reads as red ink,
   not as red plus green. Classified by the share of each channel in the summed OD (d = OD / sum):
   blue d_R > 0.45; red d_R < 0.20, d_G > 0.38 and d_G > d_B - 0.08; brown d_B > d_G + 0.06,
   d_G > 0.18, d_R < 0.30; black min(d) > 0.22 (neutral); first match in the order
   black, blue, red, brown. Plate value = summed OD / LINE_FULL, clipped.
Rerun-safe: skips plates that exist (delete them to rebuild).
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from PIL import Image
from scipy import ndimage as ndi

gdal.UseExceptions()

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
DATA = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
OUT = DATA / "derived" / "htmc"
MOSAIC = OUT / "sheets1958_utm15.tif"
BOX = (-93.30, 46.40, -91.30, 47.72)        # the Day 7 frame, lon/lat
SHEETS = ("Duluth", "Ashland", "Hibbing", "Two Harbors")   # id = (lon > -92) + 2 (lat > 47)
LINES = ("black", "blue", "red", "brown")
TINTS = ("green", "water", "urban")
PLATES = LINES + TINTS
BG_SIZE = 11
LINE_MIN = 0.22      # summed OD against the background below which a pixel is no line
LINE_FULL = 1.2      # summed OD read as solid line ink (255)
TINT_MIN = 0.06      # summed OD against paper below which the background is bare paper
TINT_REL_RESID = 0.30  # a tint is accepted only if it explains the background OD to this share
TINT_MIN_AMT = {"green": 0.3, "water": 0.3, "urban": 0.5}   # amount below which a tint fit is refused
TINT_SMOOTH = 5      # median (px) over each filled tint plate
TINT_FULL = 1.25     # tint amount (x the sheet's reference) written as 255
LINE_PCT = 80
WATER_AT = {"Duluth": (-92.02, 46.74), "Ashland": (-91.50, 46.80), "Hibbing": (-93.0431, 47.6786),
            "Two Harbors": (-91.40, 47.10)}   # Lake Superior; Sturgeon Lake for Hibbing
STRIP = 1024
REF_WINDOWS = 60    # 256 px windows sampled per sheet for the paper and tint references
PAD = 16
WINDOWS = {  # name: (lon, lat, km)
    "duluth_harbour": (-92.12, 46.77, 9.0),
    "hibbing_hull_rust": (-92.93, 47.45, 9.0),
    "rural_contours": (-91.80, 47.25, 6.0),
    "rural_woodland": (-92.60, 46.95, 6.0),
}
SHOW = {"black": (20, 20, 20), "blue": (30, 90, 200), "red": (210, 30, 30), "brown": (140, 70, 20),
        "green": (40, 140, 40), "water": (90, 170, 220), "urban": (240, 140, 20)}


def srs(code):
    s = osr.SpatialReference()
    s.SetFromUserInput(code)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def lonlat_grid(gt, w, h, step=64):
    ct = osr.CoordinateTransformation(srs("EPSG:26915"), srs("EPSG:4326"))
    xs = gt[0] + gt[1] * (np.arange(0, w + step, step) + 0.5)
    ys = gt[3] + gt[5] * (np.arange(0, h + step, step) + 0.5)
    X, Y = np.meshgrid(xs, ys)
    ll = np.array(ct.TransformPoints(np.column_stack([X.ravel(), Y.ravel()])))
    lon = upsample(ll[:, 0].reshape(X.shape), step, h, w)
    lat = upsample(ll[:, 1].reshape(X.shape), step, h, w)
    return lon, lat


def upsample(g, step, h, w):
    """Bilinear from nodes every `step` pixels (node k at pixel k * step) to every pixel.
    ndi.zoom would stretch N nodes over N * step pixels and drift by up to one node."""
    def axis(n):
        t = np.arange(n) / step
        i = np.minimum(t.astype(int), g.shape[0 if n == h else 1] - 2)
        return i, (t - i)
    iy, fy = axis(h)
    rows = g[iy] * (1 - fy)[:, None] + g[iy + 1] * fy[:, None]
    ix, fx = axis(w)
    return rows[:, ix] * (1 - fx) + rows[:, ix + 1] * fx


def od(img, ref):
    ref = ref if np.ndim(ref) == 3 else np.asarray(ref, float)[:, None, None]
    return np.maximum(0, -np.log10(np.clip(img, 3, 255) / np.clip(ref, 3, 255)))


def background(a):
    return np.stack([ndi.median_filter(c, size=BG_SIZE) for c in a])


def light_background(a):
    return np.stack([ndi.percentile_filter(c, LINE_PCT, size=BG_SIZE) for c in a])


def kmeans(x, k, seed=0, iters=40):
    rng = np.random.default_rng(seed)
    c = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = ((x[:, None] - c[None]) ** 2).sum(2).argmin(1)
        c = np.array([x[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
    return c, np.bincount(lab, minlength=k) / len(lab)


def references(ds, sid, gt):
    """Per-sheet paper, green, water and urban colours (RGB)."""
    h, w = sid.shape
    refs, orange = {}, {}
    for s, name in enumerate(SHEETS):
        rng = np.random.default_rng(s)   # one stream per sheet: a sheet's sample does not hang on the others'
        ys, xs = np.where(sid[::32, ::32] == s)
        bgs, rgbs = [], []
        for i in rng.choice(len(ys), REF_WINDOWS, replace=False):
            y0 = int(np.clip(ys[i] * 32 - 128, 0, h - 256))
            x0 = int(np.clip(xs[i] * 32 - 128, 0, w - 256))
            a = ds.ReadAsArray(x0, y0, 256, 256).astype(float)
            keep = sid[y0:y0 + 256, x0:x0 + 256] == s
            bgs.append(background(a)[:, keep].T)
            rgbs.append(a[:, keep].T)
        bg = np.concatenate(bgs)
        c, share = kmeans(bg[rng.choice(len(bg), 60000, replace=False)], 10)
        big = share > 0.015
        paper = c[big][c[big].sum(1).argmax()]
        o = od(c.T[:, :, None], paper)[:, :, 0].T
        d = o / np.maximum(o.sum(1, keepdims=True), 1e-6)
        cand = (d[:, 2] > 0.45) & (o.sum(1) > 0.1)
        if not cand.any():
            raise SystemExit(f"{name}: no green tint among the background clusters; raise REF_WINDOWS")
        green = c[cand][share[cand].argmax()]
        ct = osr.CoordinateTransformation(srs("EPSG:4326"), srs("EPSG:26915"))
        x, y, _ = ct.TransformPoint(*WATER_AT[name])
        px_, py_ = int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5])
        water = np.median(ds.ReadAsArray(px_ - 5, py_ - 5, 11, 11).reshape(3, -1), 1)
        refs[name] = {"paper": paper, "green": green, "water": water}
    for y0 in range(0, h, STRIP):
        r0, r1 = max(0, y0 - PAD), min(h, y0 + STRIP + PAD)
        a = ds.ReadAsArray(0, r0, w, r1 - r0)
        R, G, B = a.astype(np.int16)
        core = ndi.uniform_filter(((R > 200) & (G > 80) & (G < 175) & (B < 90)).astype(np.float32), 9) > 0.999
        core[: y0 - r0] = False
        core[y0 - r0 + STRIP:] = False
        for s, name in enumerate(SHEETS):
            orange.setdefault(name, []).append(a[:, core & (sid[r0:r1] == s)].T)
    orange = {k: np.concatenate(v) for k, v in orange.items()}
    pooled = np.concatenate(list(orange.values()))
    for name in SHEETS:
        o = orange[name] if len(orange[name]) >= 500 else pooled
        refs[name]["urban"] = np.median(o, 0)
        refs[name]["urban_px"] = int(len(orange[name]))
    return refs


def classify(a, sid, refs):
    """Plates (float, 0-1+) for one block."""
    out = {p: np.zeros(a.shape[1:], np.float32) for p in PLATES}
    ol = od(a, light_background(a))
    tot = ol.sum(0)
    d = ol / np.maximum(tot, 1e-6)
    line = tot > LINE_MIN
    smooth = np.stack([ndi.median_filter(c, size=3) for c in a])
    label = np.full(a.shape[1:], -2, np.int8)        # -2 unknown, -1 paper, k tint
    amount = np.zeros(a.shape[1:], np.float32)
    for s, name in enumerate(SHEETS):
        m = sid == s
        if not m.any():
            continue
        r = refs[name]
        b = od(smooth, r["paper"])
        bare = np.sqrt((b ** 2).sum(0))
        resid_best, k_best = np.full(b.shape[1:], np.inf), np.full(b.shape[1:], -2, np.int8)
        amt_best = np.zeros(b.shape[1:], np.float32)
        for k, t in enumerate(TINTS):
            v = od(np.asarray(r[t], float)[:, None, None], r["paper"])[:, 0, 0]
            amt = np.clip(np.tensordot(v, b, 1) / (v @ v), 0, 2.0)
            res = np.sqrt(((b - amt * v[:, None, None]) ** 2).sum(0))
            better = (res < resid_best) & (amt > TINT_MIN_AMT[t])
            resid_best[better], k_best[better], amt_best[better] = res[better], k, amt[better]
        k_best[resid_best > TINT_REL_RESID * bare] = -2
        k_best[b.sum(0) < TINT_MIN] = -1
        sel = m & ~ndi.binary_dilation(line)        # line fringes are mixed pixels: not tint evidence
        label[sel], amount[sel] = k_best[sel], amt_best[sel]
        black = m & line & (d.min(0) > 0.22)
        blue = m & line & ~black & (d[0] > 0.45)
        red = m & line & ~black & ~blue & (d[0] < 0.20) & (d[1] > 0.38) & (d[1] > d[2] - 0.08)
        brown = m & line & ~black & ~blue & ~red & (d[2] > d[1] + 0.06) & (d[1] > 0.18) & (d[0] < 0.30)
        val = np.clip(tot / LINE_FULL, 0, 1)
        for p, sel in zip(LINES, (black, blue, red, brown)):
            out[p][sel] = val[sel]
    # Under lines and wherever no tint fits (line fringes, lettering), the tint of the nearest
    # classified pixel continues, as the printed tint does under the line plates.
    known = label > -2
    if known.any():
        idx = ndi.distance_transform_edt(~known, return_distances=False, return_indices=True)
        label, amount = label[idx[0], idx[1]], amount[idx[0], idx[1]]
    for k, t in enumerate(TINTS):
        sel = label == k
        out[t][sel] = amount[sel] / TINT_FULL
        out[t] = ndi.median_filter(out[t], size=TINT_SMOOTH)
    return out


def main():
    ds = gdal.Open(str(MOSAIC))
    gt, w, h = ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize
    lon, lat = lonlat_grid(gt, w, h)
    sid = ((lon > -92).astype(np.uint8) + 2 * (lat > 47)).astype(np.uint8)
    inframe = (lon >= BOX[0]) & (lon <= BOX[2]) & (lat >= BOX[1]) & (lat <= BOX[3])
    del lon, lat
    paths = {p: OUT / f"ink_{p}.tif" for p in PLATES}
    refs = references(ds, sid, gt)
    if not all(p.exists() for p in paths.values()):
        drv = gdal.GetDriverByName("GTiff")
        dst = {}
        for p, path in paths.items():
            o = drv.Create(str(path), w, h, 1, gdal.GDT_Byte, options=["COMPRESS=DEFLATE", "TILED=YES"])
            o.SetGeoTransform(gt)
            o.SetProjection(ds.GetProjection())
            o.GetRasterBand(1).SetDescription(p)
            dst[p] = o
        for y0 in range(0, h, STRIP):
            r0, r1 = max(0, y0 - PAD), min(h, y0 + STRIP + PAD)
            a = ds.ReadAsArray(0, r0, w, r1 - r0).astype(float)
            planes = classify(a, sid[r0:r1], refs)
            for p, arr in planes.items():
                v = np.clip(arr[y0 - r0:y0 - r0 + min(STRIP, h - y0)] * 255, 0, 255).round().astype(np.uint8)
                dst[p].GetRasterBand(1).WriteArray(v, 0, y0)
            print("rows", y0, flush=True)
        for o in dst.values():
            o.FlushCache()
        dst = o = None    # close every plate before it is read back
    share = {}
    for p, path in paths.items():
        v = gdal.Open(str(path)).ReadAsArray()
        share[p] = {"any_ink": round(float((v[inframe] > 0).mean()), 4),
                    "mean_density": round(float(v[inframe].mean() / 255), 4)}
        if p == "green":
            share[p]["by_sheet_median_of_inked"] = {n: round(float(np.median(v[inframe & (sid == s) & (v > 0)])
                                                              / 255), 3) for s, n in enumerate(SHEETS)}
    report = {"bg_median_px": BG_SIZE, "line_min_od": LINE_MIN, "line_full_od": LINE_FULL, "tint_min_od": TINT_MIN,
              "refs_rgb": {n: {k: (np.round(v, 1).tolist() if not isinstance(v, int) else v) for k, v in r.items()}
                           for n, r in refs.items()},
              "share_of_frame": share}
    (OUT / "inks_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    contact(ds, gt, paths)


def contact(ds, gt, paths):
    ct = osr.CoordinateTransformation(srs("EPSG:4326"), srs("EPSG:26915"))
    for name, (lon, lat, km) in WINDOWS.items():
        x, y, _ = ct.TransformPoint(lon, lat)
        n = int(km * 1000 / gt[1])
        px, py = int((x - gt[0]) / gt[1]) - n // 2, int((y - gt[3]) / gt[5]) - n // 2
        panels = [np.moveaxis(ds.ReadAsArray(px, py, n, n), 0, -1).astype(np.uint8)]
        for p in PLATES:
            v = gdal.Open(str(paths[p])).ReadAsArray(px, py, n, n).astype(float)[..., None] / 255
            col = np.array(SHOW[p], float)
            panels.append((255 * (1 - v) + col * v).astype(np.uint8))
        tiles = [Image.fromarray(np.ascontiguousarray(t)) for t in panels]
        cols = 4
        W = Image.new("RGB", (cols * n + (cols - 1) * 6, 2 * n + 6), "white")
        for i, t in enumerate(tiles):
            W.paste(t, ((i % cols) * (n + 6), (i // cols) * (n + 6)))
        W.save(OUT / f"check_{name}.png", optimize=True)


if __name__ == "__main__":
    main()
