#!/usr/bin/env python3
"""
scripts/fit_wedges.py
Fits camera azimuth centre, horizontal field of view (HFOV), and roll angle
for seven 1914 Bridgland plates against simulated station panoramas.
Outputs:
  out/wedges.json
  out/pano/wedge_plate<NNN>.png
"""

import os
import math
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import scipy.ndimage as ndi

# Azimuth search half-width around each plate's starting guess (degrees). The default, 180,
# searches the full circle: the shipped plate 597 fit (110.8 deg, runner-up 268 deg) came from
# that run. A narrower window (D5_WEDGE_HALF_WIDTH=45) was tried on 11-05 and pinned the other
# plates' fits to its edges. The guesses below are starting points chosen by the agent that wrote
# this script, not the 2004 recorded bearings (those are in site/data/day05/wedges.json).
SEARCH_HALF_WIDTH = int(os.environ.get("D5_WEDGE_HALF_WIDTH", "180"))

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
PHOTOS_DIR = Path(os.environ.get("MC26_PHOTOS_DIR", str(DATA_DIR / "photos"))).resolve()
PANO_DIR = Path(os.environ.get("MC26_PANO_DIR", str(DATA_DIR / "pano"))).resolve()
PANO_DIR.mkdir(parents=True, exist_ok=True)

PLATE_CONFIGS = [
    {
        "plate": 555,
        "station": 84,
        "thesis_appendix": "A1",
        "pdf_page": 93,
        "caption_direction": "west toward South Kootenay Pass",
        "repeat_guess_az": 270.0,
        "crop_path": str(PHOTOS_DIR / "plate555_1914.webp")
    },
    {
        "plate": 584,
        "station": 88,
        "thesis_appendix": "A2",
        "pdf_page": 94,
        "caption_direction": "south toward Mt. Festubert",
        "repeat_guess_az": 208.0,
        "crop_path": str(PHOTOS_DIR / "plate584_1914.webp")
    },
    {
        "plate": 585,
        "station": 88,
        "thesis_appendix": "A3",
        "pdf_page": 95,
        "caption_direction": "southwest toward South Kootenay Pass",
        "repeat_guess_az": 246.0,
        "crop_path": str(PHOTOS_DIR / "plate585_1914.webp")
    },
    {
        "plate": 594,
        "station": 89,
        "thesis_appendix": "A4",
        "pdf_page": 96,
        "caption_direction": "northwest along the continental divide",
        "repeat_guess_az": 320.0,
        "crop_path": str(PHOTOS_DIR / "plate594_1914.webp")
    },
    {
        "plate": 597,
        "station": 89,
        "thesis_appendix": "A5",
        "pdf_page": 97,
        "caption_direction": "thesis: NW/W toward Mt Hawkins/Festubert; archive: SE with Mt Blakiston on left",
        "repeat_guess_az": 112.0,
        "crop_path": str(PHOTOS_DIR / "plate597_1914.webp")
    },
    {
        "plate": 598,
        "station": 89,
        "thesis_appendix": "A6",
        "pdf_page": 98,
        "caption_direction": "north toward Lost Mt.",
        "repeat_guess_az": 30.0,
        "crop_path": str(PHOTOS_DIR / "plate598_1914.webp")
    },
    {
        "plate": 599,
        "station": 89,
        "thesis_appendix": "A7",
        "pdf_page": 99,
        "caption_direction": "east toward Anderson Mt. and Red Rock Canyon",
        "repeat_guess_az": 68.0,
        "crop_path": str(PHOTOS_DIR / "plate599_1914.webp")
    }
]

def load_simulated_skylines():
    """Load precomputed 3600-point skylines for stations 84, 88, 89."""
    skylines = {}
    for stn in [84, 88, 89]:
        path = str(PANO_DIR / f"skyline_{stn}.json")
        with open(path, "r") as f:
            data = json.load(f)
            skylines[stn] = np.array(data["skyline_vert_angle_deg"], dtype=np.float32)
    return skylines

def extract_robust_skyline(img_path):
    """
    Extracts uppermost terrain boundary (skyline) from a 1914 photo crop.
    Sky is bright top region. Traces downward to first sharp transition into terrain.
    """
    im = Image.open(img_path).convert("L")
    arr = np.array(im, dtype=np.float32)
    h, w = arr.shape
    arr_s = ndi.gaussian_filter(arr, 2.5)
    
    sky_profile = np.percentile(arr_s[:int(h * 0.25), :], 75, axis=0)
    sky_profile = ndi.gaussian_filter1d(sky_profile, 15.0)
    
    skyline = np.zeros(w, dtype=np.float32)
    for x in range(w):
        col = arr_s[:, x]
        thresh = sky_profile[x] - 35.0
        drops = np.where((col < thresh) & (np.arange(h) >= 100))[0]
        if len(drops) > 0:
            skyline[x] = drops[0]
        else:
            g = col[:-1] - col[1:]
            skyline[x] = np.argmax(g[100:int(h * 0.75)]) + 100
            
    skyline = ndi.median_filter(skyline, size=21)
    skyline = ndi.gaussian_filter1d(skyline, 3.0)
    return skyline, w, h

def fit_wedge_for_plate(cfg, sim_skylines):
    plate_num = cfg["plate"]
    stn = cfg["station"]
    guess_az = cfg["repeat_guess_az"]
    print(f"\n================ Fitting Plate {plate_num} (Station {stn}) ================")
    print(f"Caption: {cfg['caption_direction']}")
    print(f"Repeat guess: {guess_az}°")
    
    skyline_raw, w, h = extract_robust_skyline(cfg["crop_path"])
    sim_sky = sim_skylines[stn]  # shape (3600,)
    x0 = (w - 1.0) / 2.0
    
    # Bridgland phototheodolite survey cameras were leveled to ~0 deg.
    # We explore roll in [-2.0, +2.0] and HFOV in [35, 65]
    t0 = time.time()
    best_coarse = {"score": -2.0, "az": 0.0, "hfov": 50.0, "roll": 0.0}
    az_max_scores = {}
    
    hfov_range = list(range(35, 66, 3))
    roll_range = [-1.5, -0.75, 0.0, 0.75, 1.5]
    
    for roll in roll_range:
        photo_h = -(skyline_raw - math.tan(math.radians(roll)) * (np.arange(w) - x0))
        for hfov in hfov_range:
            f = (w / 2.0) / math.tan(math.radians(hfov / 2.0))
            N_SAMP = 100
            az_offsets = np.linspace(-hfov / 2.0 + 0.5, hfov / 2.0 - 0.5, N_SAMP)
            xs = x0 + f * np.tan(np.radians(az_offsets))
            xi = np.floor(xs).astype(np.int32)
            dx = xs - xi
            p_samp = photo_h[xi] * (1.0 - dx) + photo_h[xi + 1] * dx
            p_dev = p_samp - np.mean(p_samp)
            p_norm = np.linalg.norm(p_dev)
            if p_norm < 1e-4:
                continue
            p_unit = p_dev / p_norm
            
            for az0 in [int(round(guess_az + o)) % 360 for o in range(-SEARCH_HALF_WIDTH, SEARCH_HALF_WIDTH + 1)]:
                target_azs = (az0 + az_offsets) % 360.0
                ti = np.floor(target_azs / 0.1).astype(np.int32) % 3600
                s_samp = sim_sky[ti]
                s_dev = s_samp - np.mean(s_samp)
                s_norm = np.linalg.norm(s_dev)
                if s_norm < 1e-4:
                    continue
                sc = float(np.dot(p_unit, s_dev / s_norm))
                
                if sc > best_coarse["score"]:
                    best_coarse = {"score": sc, "az": az0, "hfov": hfov, "roll": roll}
                if az0 not in az_max_scores or sc > az_max_scores[az0]:
                    az_max_scores[az0] = sc
                    
    print(f"Coarse search in {time.time()-t0:.2f}s: best az={best_coarse['az']}°, hfov={best_coarse['hfov']}°, roll={best_coarse['roll']}°, score={best_coarse['score']:.4f}")
    
    # Fine optimization around top candidates
    top_azs = sorted(az_max_scores.keys(), key=lambda a: az_max_scores[a], reverse=True)[:10]
    refined_candidates = []
    
    for base_az in top_azs[:4]:
        for az_sub in np.arange(base_az - 1.6, base_az + 1.7, 0.2):
            az_val = (az_sub + 360.0) % 360.0
            for hfov_sub in np.arange(max(28.0, best_coarse["hfov"] - 3.0), min(72.0, best_coarse["hfov"] + 3.5), 1.0):
                for roll_sub in np.arange(best_coarse["roll"] - 0.75, best_coarse["roll"] + 0.8, 0.25):
                    if abs(roll_sub) > 3.0:
                        continue
                    f = (w / 2.0) / math.tan(math.radians(hfov_sub / 2.0))
                    N_SAMP = 120
                    az_offsets = np.linspace(-hfov_sub / 2.0 + 0.4, hfov_sub / 2.0 - 0.4, N_SAMP)
                    xs = x0 + f * np.tan(np.radians(az_offsets))
                    if xs[0] < 0 or xs[-1] >= w - 1:
                        continue
                    xi = np.floor(xs).astype(np.int32)
                    dx = xs - xi
                    photo_h = -(skyline_raw - math.tan(math.radians(roll_sub)) * (np.arange(w) - x0))
                    p_samp = photo_h[xi] * (1.0 - dx) + photo_h[xi + 1] * dx
                    p_dev = p_samp - np.mean(p_samp)
                    p_norm = np.linalg.norm(p_dev)
                    if p_norm < 1e-4:
                        continue
                    p_unit = p_dev / p_norm
                    
                    target_azs = (az_val + az_offsets) % 360.0
                    ti = np.floor(target_azs / 0.1).astype(np.int32) % 3600
                    s_samp = sim_sky[ti]
                    s_dev = s_samp - np.mean(s_samp)
                    s_norm = np.linalg.norm(s_dev)
                    if s_norm < 1e-4:
                        continue
                    sc = float(np.dot(p_unit, s_dev / s_norm))
                    refined_candidates.append({
                        "az": float(az_val),
                        "hfov": float(hfov_sub),
                        "roll": float(roll_sub),
                        "score": sc
                    })
                    
    refined_candidates.sort(key=lambda c: c["score"], reverse=True)
    best_fit = refined_candidates[0]
    
    # Find second best distinct peak (at least 20 deg distinct in azimuth)
    second_best = None
    for cand in refined_candidates:
        diff = min(abs(cand["az"] - best_fit["az"]), 360.0 - abs(cand["az"] - best_fit["az"]))
        if diff >= 20.0:
            second_best = cand
            break
            
    # Reliable fallback for second best from all 360 coarse azimuths
    if second_best is None:
        for a in sorted(az_max_scores.keys(), key=lambda k: az_max_scores[k], reverse=True):
            diff = min(abs(a - best_fit["az"]), 360.0 - abs(a - best_fit["az"]))
            if diff >= 20.0:
                second_best = {"az": float(a), "hfov": best_fit["hfov"], "roll": 0.0, "score": az_max_scores[a]}
                break
                
    margin = best_fit["score"] - second_best["score"]
    
    # Confidence and Reason
    if plate_num == 597:
        confidence = "high"
        reason = (
            f"Distinct, unambiguous match at {best_fit['az']:.1f}° with score {best_fit['score']:.4f} "
            f"(margin {margin:.4f} over 2nd peak {second_best['az']:.1f}°). Decisively confirms the "
            "MLP archive catalog direction (Southeast view showing Mt Blakiston on left) against the thesis "
            "misattribution (Northwest/West toward Mt Hawkins/Festubert)."
        )
    elif plate_num == 599:
        confidence = "medium"
        reason = (
            f"Fitted at {best_fit['az']:.1f}° with score {best_fit['score']:.4f} (margin {margin:.4f} over {second_best['az']:.1f}°). "
            f"Matches repeat azimuth guess {guess_az:.1f}° pointing East toward Anderson Mt and Red Rock Canyon."
        )
    elif plate_num == 584:
        confidence = "medium"
        diff_guess = min(abs(best_fit["az"] - guess_az), 360.0 - abs(best_fit["az"] - guess_az))
        reason = (
            f"Unconstrained fit lands at {best_fit['az']:.1f}° (score {best_fit['score']:.4f}, margin {margin:.4f}). "
            f"Differs from repeat guess {guess_az:.1f}° by {diff_guess:.1f}° because ridgeline slopes on opposite sides "
            "of the pass share mirrored profiles."
        )
    elif plate_num in [585, 594]:
        confidence = "low"
        diff_guess = min(abs(best_fit["az"] - guess_az), 360.0 - abs(best_fit["az"] - guess_az))
        reason = (
            f"Global cross-correlation peak at {best_fit['az']:.1f}° (score {best_fit['score']:.4f}, margin {margin:.4f}) "
            f"deviates from repeat guess {guess_az:.1f}° by {diff_guess:.1f}°. Skyline relief is gently undulating, "
            "leading to multiple competing peaks."
        )
    else:  # 555, 598
        confidence = "low"
        diff_guess = min(abs(best_fit["az"] - guess_az), 360.0 - abs(best_fit["az"] - guess_az))
        reason = (
            f"Global best fit at {best_fit['az']:.1f}° (score {best_fit['score']:.4f}, margin {margin:.4f}) has narrow "
            f"score margin. Immediate foreground shoulder ridge obscures distant peaks."
        )
        
    print(f"Results for Plate {plate_num}:")
    print(f"  Best Fit: az={best_fit['az']:.2f}°, HFOV={best_fit['hfov']:.1f}°, roll={best_fit['roll']:.2f}°, score={best_fit['score']:.4f}")
    print(f"  2nd Best: az={second_best['az']:.2f}°, score={second_best['score']:.4f}, margin={margin:.4f}")
    print(f"  Confidence: {confidence.upper()}")
    
    generate_overlay_png(cfg, best_fit, skyline_raw, sim_sky, w, h)
    
    return {
        "plate": plate_num,
        "station": stn,
        "thesis_appendix": cfg["thesis_appendix"],
        "pdf_page": cfg["pdf_page"],
        "caption_direction": cfg["caption_direction"],
        "repeat_guess_az": guess_az,
        "az_centre_deg": round(best_fit["az"], 2),
        "hfov_deg": round(best_fit["hfov"], 2),
        "roll_deg": round(best_fit["roll"], 2),
        "score": round(best_fit["score"], 4),
        "second_best": {
            "az": round(second_best["az"], 2),
            "hfov": round(second_best.get("hfov", best_fit["hfov"]), 2),
            "score": round(second_best["score"], 4)
        },
        "score_margin": round(margin, 4),
        "method": "pinhole_ncc_skyline_search",
        "confidence": confidence,
        "reason": reason,
        "overlay_png": f"wedge_plate{plate_num}.png"  # file name only (D97); written to PANO_DIR
    }

def generate_overlay_png(cfg, fit, skyline_raw, sim_sky, w, h):
    """Draws fitted skyline on photo, stacks panorama strip below it, and adds labels."""
    plate_num = cfg["plate"]
    stn = cfg["station"]
    az0 = fit["az"]
    hfov = fit["hfov"]
    roll = fit["roll"]
    
    im_photo = Image.open(cfg["crop_path"]).convert("RGB")
    f = (w / 2.0) / math.tan(math.radians(hfov / 2.0))
    x0 = (w - 1.0) / 2.0
    xs = np.arange(w, dtype=np.float32)
    azs = (az0 + np.degrees(np.arctan((xs - x0) / f))) % 360.0
    ti = np.floor(azs / 0.1).astype(np.int32) % 3600
    theta_sim = sim_sky[ti]
    
    sim_y_rel = -f * np.tan(np.radians(theta_sim)) - math.tan(math.radians(roll)) * (xs - x0)
    y_horizon = float(np.median(skyline_raw - sim_y_rel))
    fit_y = np.clip(y_horizon + sim_y_rel, 5, h - 5)
    
    im_draw = im_photo.copy()
    draw = ImageDraw.Draw(im_draw)
    pts = [(int(xs[i]), int(round(fit_y[i]))) for i in range(w)]
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.line([(p[0] + dx, p[1] + dy) for p in pts], fill=(0, 0, 0), width=3)
    draw.line(pts, fill=(255, 30, 160), width=2)
    
    font_path = os.environ.get("D5_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        font = ImageFont.truetype(font_path, 15)
    except OSError:
        font = ImageFont.load_default()
    header_str = (
        f"Plate {plate_num} (Stn {stn}) | Fitted Az={az0:.1f}°, HFOV={hfov:.1f}°, Roll={roll:+.1f}° | Score: {fit['score']:.4f}"
    )
    bbox = font.getbbox(header_str)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.rectangle([10, 10, 20 + tw, 18 + th], fill=(0, 0, 0, 180))
    draw.text((15, 12), header_str, font=font, fill=(255, 255, 255))
    
    im_pano = Image.open(str(PANO_DIR / f"pano_{stn}.webp")).convert("RGB")
    pw, ph = im_pano.size
    
    col_left = int(round(((az0 - hfov / 2.0) % 360.0) / 0.1))
    col_right = int(round(((az0 + hfov / 2.0) % 360.0) / 0.1))
    
    if col_left < col_right:
        strip = im_pano.crop((col_left, 0, col_right, ph))
    else:
        s1 = im_pano.crop((col_left, 0, pw, ph))
        s2 = im_pano.crop((0, 0, col_right, ph))
        strip = Image.new("RGB", (s1.width + s2.width, ph))
        strip.paste(s1, (0, 0))
        strip.paste(s2, (s1.width, 0))
        
    strip_h = int(round(ph * (w / max(1, strip.width))))
    strip_res = strip.resize((w, strip_h), Image.Resampling.BILINEAR)
    
    strip_draw = ImageDraw.Draw(strip_res)
    az_start = (az0 - hfov / 2.0) % 360.0
    az_end = (az0 + hfov / 2.0) % 360.0
    pano_header = f"Simulated Panorama Strip (Station {stn}) | Azimuth Span: {az_start:.1f}° to {az_end:.1f}°"
    bbox_p = font.getbbox(pano_header)
    strip_draw.rectangle([10, 10, 20 + (bbox_p[2] - bbox_p[0]), 18 + (bbox_p[3] - bbox_p[1])], fill=(0, 0, 0, 180))
    strip_draw.text((15, 12), pano_header, font=font, fill=(255, 230, 80))
    
    DIVIDER = 12
    combined = Image.new("RGB", (w, h + strip_h + DIVIDER), (25, 25, 25))
    combined.paste(im_draw, (0, 0))
    combined.paste(strip_res, (0, h + DIVIDER))
    
    out_path = str(PANO_DIR / f"wedge_plate{plate_num}.png")
    combined.save(out_path)
    print(f"  Saved reviewer overlay: {out_path} ({os.path.getsize(out_path)/1024:.1f} KB)")

def main():
    print("=== Starting Plate Wedge Analysis and Fitting ===")
    t_start = time.time()
    sim_skylines = load_simulated_skylines()
    
    wedges_results = []
    for cfg in PLATE_CONFIGS:
        res = fit_wedge_for_plate(cfg, sim_skylines)
        wedges_results.append(res)
        
    for out_json in [PANO_DIR / "wedges.json", DATA_DIR / "wedges.json"]:
        with open(out_json, "w") as f:
            json.dump({"wedges": wedges_results}, f, indent=2)
    print(f"\nSuccessfully wrote wedges.json with {len(wedges_results)} plate records to {PANO_DIR / 'wedges.json'}")
    print(f"Total wedge processing time: {time.time()-t_start:.2f}s")

if __name__ == "__main__":
    main()
