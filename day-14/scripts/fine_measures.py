"""Day 14: measures of the fine (1-5 mm) pattern, for the photo and for a model drawn the same way.

Fable 5.2 (second consult) proposed Minkowski functionals against threshold. Photo brightness and model thickness
are not on one scale, so both are thresholded at the same pale fractions (quantiles), and at each fraction we take:
  perimeter density  boundary length of the pale set per unit area, 1/mm (fine lace = high)
  euler density      (pale patches - holes in them) per cm^2 (positive = isolated pale specks,
                     negative = a connected pale net with many dark islands)
Also: the pale-set correlation length (where the autocorrelation of the pale mask falls to 1/e), mm.
Everything at 0.5 mm a pixel; the photo is flattened by a 20 mm blur first. Pale = brightest fraction for the
photo, thinnest mud for the model.
"""
import numpy as np
from scipy import ndimage as nd

FRACS = (0.15, 0.25, 0.35, 0.5)


def _euler(mask):
    lab, n_fg = nd.label(mask, structure=np.ones((3, 3)))
    bg, n_bg = nd.label(~mask)
    border = set(np.unique(np.concatenate([bg[0], bg[-1], bg[:, 0], bg[:, -1]]))) - {0}
    return n_fg - (n_bg - len(border))


def _perim(mask, px_mm):
    m = mask.astype(np.int8)
    edges = np.abs(np.diff(m, axis=0)).sum() + np.abs(np.diff(m, axis=1)).sum()
    return edges * px_mm * (np.pi / 4)          # 4-neighbour edge count overstates diagonal boundaries by 4/pi


def _corr_len(mask, px_mm):
    f = mask.astype(float) - mask.mean()
    ac = np.fft.irfft2(np.abs(np.fft.rfft2(f)) ** 2, s=f.shape)
    ac /= ac[0, 0] + 1e-12
    r = np.hypot(*np.meshgrid(np.fft.fftfreq(f.shape[1]) * f.shape[1], np.fft.fftfreq(f.shape[0]) * f.shape[0]))
    rb = np.bincount(r.astype(int).ravel(), ac.ravel()) / np.maximum(np.bincount(r.astype(int).ravel()), 1)
    k = np.argmax(rb < np.exp(-1))
    return float(k * px_mm)


def measures(pale_score, px_mm=0.5):
    """pale_score: 2-D array, larger = paler (photo lightness, or minus model thickness)."""
    area_mm2 = pale_score.size * px_mm ** 2
    out = {}
    for f in FRACS:
        m = pale_score >= np.quantile(pale_score, 1 - f)
        out[f"perim_{f}"] = round(_perim(m, px_mm) / area_mm2, 4)
        out[f"euler_{f}"] = round(_euler(m) / (area_mm2 / 100), 3)
    out["corr_len_mm"] = _corr_len(pale_score >= np.quantile(pale_score, 0.75), px_mm)
    return out


def photo_patch(src_gray, x0, y0, w, h, px_mm=0.5):
    """src_gray: the source photo as a float array (full frame). Returns the flattened patch at px_mm."""
    from PIL import Image
    pxmm = 3812 / 1280
    pad = 20
    box = (int(120 + (x0 - pad) * pxmm), int(608 + (y0 - pad) * pxmm), int(120 + (x0 + w + pad) * pxmm), int(608 + (y0 + h + pad) * pxmm))
    im = Image.fromarray(src_gray).crop(box)
    im = im.resize((int((w + 2 * pad) / px_mm), int((h + 2 * pad) / px_mm)), Image.LANCZOS)
    a = np.asarray(im, float)
    a = a / nd.gaussian_filter(a, 20 / px_mm)
    p = int(pad / px_mm)
    return a[p:-p, p:-p]


def score(photo_m, model_m):
    """Mean absolute log-ratio of perimeter density, plus scaled Euler difference, plus correlation length."""
    s = []
    for f in FRACS:
        s.append(abs(np.log((model_m[f"perim_{f}"] + 1e-6) / (photo_m[f"perim_{f}"] + 1e-6))))
        s.append(abs(model_m[f"euler_{f}"] - photo_m[f"euler_{f}"]) / (abs(photo_m[f"euler_{f}"]) + 5))
    s.append(abs(np.log(model_m["corr_len_mm"] / max(photo_m["corr_len_mm"], 0.5))))
    return round(float(np.mean(s)), 3)
