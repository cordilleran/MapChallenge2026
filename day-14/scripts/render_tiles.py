"""Day 14: downscale a model run to 0.25 mm and cut deep-zoom tiles for the map.

Downscaling, stated plainly (the model cell is read from the run: 2 mm for the published run):
  1 the model's mud thickness is upsampled (cubic) to 0.25 mm;
  2 detail below the model cell is synthesised: a seeded random field with a power-law spectrum, scaled by the
    local mud thickness so bare enamel stays smooth. The slope is fitted to the photo's grain between 0.7 and
    2 mm wavelengths at its native 0.336 mm a pixel, then clipped to [-3.5, -2] (JPEG blur steepens the fit;
    the published fit is -4.3, so -3.5 is used). Without the photo, -3.5 is used and meta.json says so;
  3 each model cell is rescaled toward the model's value with a smooth correction, repeated six times, so
    averaging back returns the model to within max_block_error_um and mean_block_error_um (meta.json);
  4 for drawing only, the field is blurred by 0.5 mm so the model's cells do not show as steps. This changes
    what is drawn, not the field checked in step 3.
Then: hillshade of the mud surface (vertical exaggeration VE), in two looks, each light and dark: a sepia ramp by
thickness (light, dark), a grey hillshade with the mud tinted umber by thickness (grey, greydark), and wet mud:
thickness as Beer-Lambert tone over the enamel with gentle relief and no synthesised texture (tone, tonedark).
Tiles: OUT/tiles/{light,dark,grey,greydark,tone,tonedark,photo}/z/x/y.jpg, 256 px; zoom z has 2**(z - ZMAX) * 4 px per mm; Leaflet
CRS.Simple, origin top-left. Also OUT/emerge.json (drain replay), OUT/rules.png (where the rules acted),
OUT/meta.json, and RUN_DIR/preview_light.jpg.

Run: python -I scripts/render_tiles.py RUN_DIR OUT_DIR [--photo] [--ve 150]
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

ROOT = Path(__file__).resolve().parents[1]
TILE = 256
PX_MM = 4                    # at the deepest zoom


def spectral_slope(img, lo_mm=0.5, hi_mm=2.0, px_mm=0.5):
    f = np.fft.fftshift(np.abs(np.fft.fft2(img - img.mean())) ** 2)
    ny, nx = img.shape
    ky, kx = np.meshgrid(np.fft.fftshift(np.fft.fftfreq(ny, px_mm)), np.fft.fftshift(np.fft.fftfreq(nx, px_mm)), indexing="ij")
    k = np.hypot(kx, ky)
    m = (k > 1 / hi_mm) & (k < 1 / lo_mm)
    b = np.polyfit(np.log(k[m]), np.log(f[m]), 1)[0]
    return float(b)


def synth(shape, beta, rng, cutoff_px):
    """Random field with power spectrum ~ k^beta, high-passed above the model's resolution."""
    ny, nx = shape
    ky = np.fft.fftfreq(ny)[:, None]
    kx = np.fft.rfftfreq(nx)[None, :]
    k = np.hypot(kx, ky)
    k[0, 0] = 1
    amp = k ** (beta / 2) * (k > 1 / cutoff_px)
    ph = rng.standard_normal((ny, nx // 2 + 1)) + 1j * rng.standard_normal((ny, nx // 2 + 1))
    f = np.fft.irfft2(amp * ph, s=shape)
    return f / (f.std() + 1e-12)


def block_mean(a, b):
    ny, nx = a.shape[0] // b, a.shape[1] // b
    return a[:ny * b, :nx * b].reshape(ny, b, nx, b).mean((1, 3))


def hillshade(z, px_m, az=315, alt=35):
    gy, gx = np.gradient(z, px_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    a, e = math.radians(az), math.radians(alt)
    hs = np.sin(e) * np.cos(slope) + np.cos(e) * np.sin(slope) * np.cos(a - aspect)
    return np.clip(hs, 0, 1)


def ramp(t, stops):
    t = np.clip(t, 0, 1)
    xs = np.array([s[0] for s in stops])
    out = np.zeros(t.shape + (3,))
    for c in range(3):
        out[..., c] = np.interp(t, xs, [s[1][c] for s in stops])
    return out


LIGHT = [(0.0, (246, 241, 230)), (0.12, (226, 211, 186)), (0.35, (168, 128, 92)), (0.7, (104, 72, 50)), (1.0, (58, 40, 30))]
DARK = [(0.0, (22, 24, 27)), (0.12, (52, 44, 36)), (0.35, (140, 98, 56)), (0.7, (206, 152, 88)), (1.0, (240, 198, 128))]


def cut(rgb, out, name, quality=84, pad=(236, 230, 218)):
    """Write a tile pyramid: zoom ZMAX holds the full image; each lower zoom halves it."""
    h, w = rgb.shape[:2]
    zmax = 0
    while max(h, w) / (2 ** zmax) > TILE:
        zmax += 1
    im = Image.fromarray(rgb)
    n = 0
    for z in range(zmax, -1, -1):
        s = 2 ** (zmax - z)
        lvl = im if s == 1 else im.resize((math.ceil(w / s), math.ceil(h / s)), Image.LANCZOS)
        for ty in range(math.ceil(lvl.height / TILE)):
            for tx in range(math.ceil(lvl.width / TILE)):
                t = Image.new("RGB", (TILE, TILE), pad)       # beyond the image: the page's ground, not black
                t.paste(lvl.crop((tx * TILE, ty * TILE, min(tx * TILE + TILE, lvl.width), min(ty * TILE + TILE, lvl.height))), (0, 0))
                d = out / "tiles" / name / str(z) / str(tx)
                d.mkdir(parents=True, exist_ok=True)
                t.save(d / f"{ty}.jpg", quality=quality)
                n += 1
    return zmax, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--ve", type=float, default=150.0)
    ap.add_argument("--seed", type=int, default=1414)
    ap.add_argument("--detail", type=float, default=0.10, help="synthesised detail, fraction of local mud thickness")
    ap.add_argument("--photo", action="store_true", help="also tile the rectified photo")
    a = ap.parse_args()
    run, out = Path(a.run), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    d = np.load(run / "fields.npz")
    H, bed = d["H"].astype("f8"), d["bed"].astype("f8")
    H[d["r"] >= 1.0] = 0.0                    # outside the waterline footprint the enamel is clean
    rng = np.random.default_rng(a.seed)

    dx_mm = 1280 / H.shape[1]                 # the run's model cell
    UP = int(round(dx_mm * PX_MM))            # model cell -> 0.25 mm
    # spectral slope of the photo's grain at native resolution (about 0.336 mm a pixel), lighting flattened
    photo_src = ROOT / "data" / "source" / "tub_20260318_noexif.jpg"
    if photo_src.exists():
        src = Image.open(photo_src).convert("L").crop((120, 608, 3932, 2152))
        px_mm_photo = 1280 / src.width
        Lp = np.asarray(src, float)
        y0, x0 = int(150 / px_mm_photo), int(300 / px_mm_photo)
        patch = Lp[y0:y0 + 900, x0:x0 + 2400]
        patch = patch / nd.gaussian_filter(patch, 40 / px_mm_photo)
        beta = spectral_slope(patch, lo_mm=0.7, hi_mm=2.0, px_mm=px_mm_photo)
    else:
        beta = None                           # the photo is not in the repository; use the clip value
    beta_used = float(np.clip(beta if beta is not None else -3.5, -3.5, -2.0))

    Hu = nd.zoom(H, UP, order=3).clip(0)
    noise = synth(Hu.shape, beta_used, rng, cutoff_px=UP)
    detail = a.detail * noise * nd.zoom(nd.uniform_filter(H, 3), UP, order=1).clip(0)
    Hf = (Hu + detail).clip(0)
    # rescale so every 2 mm block averages to the model's value; a smooth (bilinear) correction, repeated, so
    # mud edges do not turn into 2 mm steps; the remaining error is reported
    Hc = H[:Hf.shape[0] // UP, :Hf.shape[1] // UP]
    for _ in range(6):
        bm = block_mean(Hf, UP)
        fac = np.where(bm > 1e-9, Hc / np.maximum(bm, 1e-12), 1.0).clip(0, 4)
        Hf = Hf * nd.zoom(fac, UP, order=1, grid_mode=True, mode="nearest")[:Hf.shape[0], :Hf.shape[1]]
    err = float(np.abs(block_mean(Hf, UP) - Hc).max() * 1e6)
    err_mean = float(np.abs(block_mean(Hf, UP) - Hc).mean() * 1e6)
    bedu = nd.zoom(bed, UP, order=1)
    px_m = dx_mm / 1000 / UP
    Hd = nd.gaussian_filter(Hf, 2.0)            # display only: 0.5 mm blur so the model's 2 mm cells do not show as steps
    surf = (Hd * a.ve) + bedu * 0.6          # the tub's own form, gently, so the walls read as walls
    hs = hillshade(surf, px_m)
    hs2 = hillshade(surf, px_m, az=20, alt=25)
    shade = 0.62 * hs + 0.38 * hs2
    t = (Hd / np.percentile(Hd[Hd > 0], 98)) ** 0.8
    for name, stops, lo, hi, pad in (("light", LIGHT, 0.55, 1.12, (236, 230, 218)), ("dark", DARK, 0.35, 1.25, (20, 21, 23))):
        base = ramp(t, stops)
        rgb = np.clip(base * (lo + (hi - lo) * shade[..., None]), 0, 255).astype("uint8")
        zmax, n = cut(rgb, out, name, pad=pad)
        if name == "light":
            Image.fromarray(rgb).resize((1280, 520), Image.LANCZOS).save(run / "preview_light.jpg", quality=88)
    # the grey look: a neutral hillshade, the mud laid over it as a translucent umber tint by thickness
    for name, g0, g1, tint, pad in (("grey", 62, 250, (118, 86, 60), (236, 230, 218)), ("greydark", 16, 210, (190, 150, 108), (20, 21, 23))):
        g = (g0 + (g1 - g0) * shade)[..., None] * np.array([1.0, 1.0, 1.02])
        alpha = (0.5 * t ** 1.4)[..., None]
        rgb = np.clip(g * (1 - alpha) + np.array(tint) * alpha * (0.55 + 0.6 * shade[..., None]), 0, 255).astype("uint8")
        cut(rgb, out, name, pad=pad)
        if name == "grey":
            Image.fromarray(rgb).resize((1280, 520), Image.LANCZOS).save(run / "preview_grey.jpg", quality=88)
    # the wet-mud look (Fable 5.2, second consult): thickness as tone over the enamel (Beer-Lambert per colour
    # channel, blue darkening fastest), relief only gently (VE 25, multiplied in at 20 %), and no synthesised lumps
    Hs = nd.gaussian_filter(Hu, 2.0)
    surf2 = Hs * 25 + bedu * 0.6
    hs3 = 0.62 * hillshade(surf2, px_m) + 0.38 * hillshade(surf2, px_m, az=20, alt=25)
    k = np.array([1 / 2.2e-4, 1 / 1.6e-4, 1 / 1.1e-4])
    a_ = 1 - np.exp(-Hs[..., None] * k)
    for name, ground, mud, pad in (("tone", (240, 236, 226), (64, 44, 28), (236, 230, 218)), ("tonedark", (24, 25, 28), (214, 168, 112), (20, 21, 23))):
        rgb = np.array(ground) * (1 - a_) + np.array(mud) * a_
        rgb = rgb * (0.8 + 0.2 * (hs3 / max(hs3.mean(), 1e-6)).clip(0, 1.6))[..., None]
        cut(np.clip(rgb, 0, 255).astype("uint8"), out, name, pad=pad)
        if name == "tone":
            Image.fromarray(np.clip(rgb, 0, 255).astype("uint8")).resize((1280, 520), Image.LANCZOS).save(run / "preview_tone.jpg", quality=88)
    meta = {"zmax": zmax, "width_px": int(Hf.shape[1]), "height_px": int(Hf.shape[0]), "px_per_mm_at_zmax": PX_MM,
            "model_dx_mm": round(dx_mm, 3), "display_dx_mm": 0.25, "ve": a.ve,
            "photo_spectral_slope": None if beta is None else round(beta, 2), "synth_slope_used": round(beta_used, 2), "synth_amplitude": a.detail,
            "max_block_error_um": round(err, 2), "mean_block_error_um": round(err_mean, 3), "tiles_per_set": n, "run": str(run.name)}
    if a.photo:
        src = Image.open(ROOT / "data" / "source" / "tub_20260318_noexif.jpg").convert("RGB").crop((120, 608, 3932, 2152))
        im = np.asarray(src.resize((Hf.shape[1], Hf.shape[0]), Image.LANCZOS))
        pz, pn = cut(im, out, "photo")
        meta.update({"photo_tiles": pn, "photo_note": "the rectified photo resampled from about 0.34 mm to 0.25 mm a pixel"})
    # emergence times for the drain replay and isochrones (4 mm cells); never emerged = a puddle, kept wet
    em = d["emerge"].astype("f8")
    t_end = float(json.loads((run / "meta.json").read_text())["t_end_s"])
    em = np.where(np.isnan(em), t_end + 1, em)
    em_small = nd.median_filter(block_mean(em, max(1, int(round(4 / dx_mm)))), size=5)   # puddles left behind make the raw field speckled
    em_small = nd.gaussian_filter(em_small, 1.2)
    (out / "emerge.json").write_text(json.dumps({"nx": em_small.shape[1], "ny": em_small.shape[0], "dx_mm": 4, "t_max": round(t_end, 1),
                                                 "t": np.round(em_small, 1).ravel().tolist()}))
    # where the two rules (dewetting, tide lines) set the mud, as sim.py recorded it: hatched, 1 px per mm
    rule = d["rule"] & (d["r"] < 1.0)
    rule = nd.zoom(rule.astype(float), dx_mm, order=0)[:520, :1280] > 0.5
    yy, xx = np.mgrid[0:rule.shape[0], 0:rule.shape[1]]
    hatch = rule & (((xx + yy) % 7) < 1)
    edge = rule ^ nd.binary_erosion(rule, iterations=1)
    rgba = np.zeros(rule.shape + (4,), "uint8")
    rgba[hatch | edge] = (138, 79, 36, 230)
    Image.fromarray(rgba).save(out / "rules.png", optimize=True)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
