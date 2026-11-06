#!/usr/bin/env python3
"""
scripts/render_panoramas.py
Renders 360-degree simulated panoramas and skylines for six Bridgland 1914 camera stations.
Outputs:
  out/pano/pano_<stn>.webp (colour)
  out/pano/pano_<stn>_grey.webp (greyscale)
  out/pano/skyline_<stn>.json (skyline vertical angle and distance per 0.1 deg azimuth)
"""

import os
import sys
import math
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from osgeo import gdal, osr

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()

# Ensure output directories exist
# Paths: defaults from MC26_DAY05_DIR (IN -> slice_a/derived, OUT -> MC26_DAY05_DIR).
# D5_PANO_IN, D5_PANO_OUT, D5_VS_DIR can override.
# PANO_LABELS=1 burns peak labels into the image (old behaviour);
# by default the page draws the peaks itself from the peaks list in skyline_<stn>.json.
IN = os.environ.get("D5_PANO_IN", str(DATA_DIR / "slice_a" / "derived"))
OUT = os.environ.get("D5_PANO_OUT", str(DATA_DIR))
BURN_LABELS = os.environ.get("PANO_LABELS", "0") == "1"
# D93: "station" (the MLP station point, as recorded) or "highpoint" (highest cell of its 3x3 window);
# highpoint files carry the suffix _hp.
POSITION = os.environ.get("D5_PANO_POSITION", "station")
SUFFIX = "_hp" if POSITION == "highpoint" else ""
os.makedirs(f"{OUT}/pano", exist_ok=True)

# Coordinate & Geodesy Constants
EARTH_RADIUS = 6371000.0  # meters
K_REFRACTION = 0.13
CURV_FACTOR = (1.0 - K_REFRACTION) / (2.0 * EARTH_RADIUS)  # ~6.8278e-8 m^-1
MAX_DIST = 30000.0  # 30 km
STEP_SIZE = 20.0  # 20 m ray-marching step (1500 steps)
N_AZIMUTHS = 3600  # 0.1 degree per column
AZ_STEP_DEG = 360.0 / N_AZIMUTHS  # 0.1 deg

# Panorama dimensions
IMG_WIDTH = 3600
IMG_HEIGHT = 370  # Claude 11-05: 0.1 deg per row, the same as per column, so the view has no vertical exaggeration (was 740 rows, 2x)
VERT_MIN_DEG = -25.0
VERT_MAX_DEG = 12.0
VERT_SPAN_DEG = VERT_MAX_DEG - VERT_MIN_DEG  # 37.0 deg
DEG_PER_ROW = VERT_SPAN_DEG / IMG_HEIGHT  # 0.1 deg per row
H0 = int(round(VERT_MAX_DEG / DEG_PER_ROW))  # horizon row

# Sun direction for Lambert shading (SSE summer sun in Rockies)
SUN_AZ_DEG = 155.0
SUN_ALT_DEG = 42.0
sun_az_rad = math.radians(SUN_AZ_DEG)
sun_alt_rad = math.radians(SUN_ALT_DEG)
SUN_VEC = np.array([
    math.cos(sun_alt_rad) * math.sin(sun_az_rad),
    math.cos(sun_alt_rad) * math.cos(sun_az_rad),
    math.sin(sun_alt_rad)
], dtype=np.float32)

# WorldCover 2021 Muted Natural Colour Palette (RGB)
WC_COLOURS = {
    10: np.array([55, 82, 52], dtype=np.float32),    # Tree cover (conifer forest)
    20: np.array([108, 125, 82], dtype=np.float32),  # Shrubland
    30: np.array([142, 146, 98], dtype=np.float32),  # Grassland / alpine meadow
    40: np.array([155, 148, 105], dtype=np.float32), # Cropland
    50: np.array([125, 125, 125], dtype=np.float32), # Built-up
    60: np.array([168, 158, 148], dtype=np.float32), # Bare / sparse (rock, scree, limestone)
    70: np.array([238, 242, 246], dtype=np.float32), # Snow and ice
    80: np.array([55, 85, 122], dtype=np.float32),   # Permanent water
    90: np.array([88, 112, 88], dtype=np.float32),   # Herbaceous wetland
    95: np.array([88, 112, 88], dtype=np.float32),   # Mangroves
    100: np.array([128, 132, 102], dtype=np.float32) # Moss / lichen / tundra
}
DEFAULT_COLOUR = np.array([150, 145, 135], dtype=np.float32)

# Sky Colours
SKY_TOP = np.array([182, 208, 235], dtype=np.float32)
SKY_HORIZON = np.array([218, 228, 238], dtype=np.float32)
SKY_LOW = np.array([225, 232, 240], dtype=np.float32)

def make_sky_background():
    """Generates 740x3600 background sky gradient."""
    # Row 0 is +12 deg, Row 240 is 0 deg (horizon), Row 739 is -25 deg
    rows = np.arange(IMG_HEIGHT, dtype=np.float32)
    sky = np.zeros((IMG_HEIGHT, 1, 3), dtype=np.float32)
    # 0 to 240: top to horizon
    frac_upper = np.clip(rows[:H0 + 1] / float(H0), 0.0, 1.0)[:, None]
    sky[:H0 + 1, 0, :] = (1.0 - frac_upper) * SKY_TOP + frac_upper * SKY_HORIZON
    # 241 to 740: horizon to low
    frac_lower = np.clip((rows[H0 + 1:] - H0) / (IMG_HEIGHT - H0), 0.0, 1.0)[:, None]
    sky[H0 + 1:, 0, :] = (1.0 - frac_lower) * SKY_HORIZON + frac_lower * SKY_LOW
    return np.tile(sky, (1, IMG_WIDTH, 1))

print("Loading DEM and rasters...")
t0 = time.time()
dem_ds = gdal.Open(f"{IN}/dem_viewshed_30m_epsg3979.tif")
dem_arr = dem_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
dem_gt = dem_ds.GetGeoTransform()
dem_nodata = dem_ds.GetRasterBand(1).GetNoDataValue()

# Compute DEM surface normals for Lambert shading
# Cell size is 30m
dz_dx = np.zeros_like(dem_arr)
dz_dy = np.zeros_like(dem_arr)
dz_dx[:, 1:-1] = (dem_arr[:, 2:] - dem_arr[:, :-2]) / 60.0
dz_dy[1:-1, :] = (dem_arr[:-2, :] - dem_arr[2:, :]) / 60.0  # +y is north, but row index decreases northwards
norm_len = np.sqrt(dz_dx**2 + dz_dy**2 + 1.0)
dem_nx = -dz_dx / norm_len
dem_ny = -dz_dy / norm_len
dem_nz = 1.0 / norm_len

# WorldCover raster
wc_ds = gdal.Open(f"{IN}/worldcover_2021_viewshed_10m_epsg3979.tif")
wc_arr = wc_ds.GetRasterBand(1).ReadAsArray()
wc_gt = wc_ds.GetGeoTransform()

# Setup spatial reference for convergence
srs_grid = osr.SpatialReference()
srs_grid.ImportFromEPSG(3979)
srs_geo = osr.SpatialReference()
srs_geo.ImportFromEPSG(4326)
srs_grid.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
srs_geo.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
ct_to_grid = osr.CoordinateTransformation(srs_geo, srs_grid)
ct_to_geo = osr.CoordinateTransformation(srs_grid, srs_geo)

print(f"Rasters loaded in {time.time()-t0:.2f}s")

# Bare-earth viewsheds (r.viewshed, slice b) decide whether a peak below the skyline is seen,
# that is, in front of a higher ridge rather than hidden behind a nearer one. Any of the 3x3
# cells around the named point counts. Optional: without D5_VS_DIR only skyline peaks are kept.
VS_DIR = os.environ.get("D5_VS_DIR", str(DATA_DIR / "viewsheds"))
_vs_cache = {}
def seen_in_viewshed(stn, px, py):
    if not VS_DIR:
        return False
    if stn not in _vs_cache:
        ds = gdal.Open(f"{VS_DIR}/vs_{stn}_main.tif")
        _vs_cache[stn] = (ds.GetGeoTransform(), ds.ReadAsArray())
    gt, a = _vs_cache[stn]
    c = int((px - gt[0]) / gt[1]); r = int((py - gt[3]) / gt[5])
    win = a[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2]
    return bool(win.size and win.max() > 0)

# Load named peaks
peaks_path = Path(f"{IN}/names_peaks_passes.geojson")
if not peaks_path.exists():
    peaks_path = DATA_DIR / "slice_a" / "names_peaks_passes.geojson"
with open(peaks_path) as f:
    peaks_gj = json.load(f)

# Station definitions
STATIONS = [
    {"num": 84, "name": "Mt Blakiston (Shoulder)", "x": -1367940.82, "y": 217579.65},
    {"num": 85, "name": "Anderson", "x": -1365623.76, "y": 220952.08},
    {"num": 86, "name": "Sage Creek", "x": -1375860.42, "y": 226043.96},
    {"num": 87, "name": "Blakiston Divide", "x": -1372539.66, "y": 225266.61},
    {"num": 88, "name": "Lost Mt", "x": -1371682.06, "y": 221472.44},
    {"num": 89, "name": "Lone Mt", "x": -1374922.62, "y": 219847.80},
]

def bilinear_sample_dem(x_pts, y_pts):
    """Vectorized bilinear interpolation on DEM."""
    px = (x_pts - dem_gt[0]) / dem_gt[1]
    py = (y_pts - dem_gt[3]) / dem_gt[5]
    xi = np.floor(px).astype(np.int32)
    yi = np.floor(py).astype(np.int32)
    np.clip(xi, 0, dem_arr.shape[1] - 2, out=xi)
    np.clip(yi, 0, dem_arr.shape[0] - 2, out=yi)
    dx = px - xi
    dy = py - yi
    
    z00 = dem_arr[yi, xi]
    z01 = dem_arr[yi, xi + 1]
    z10 = dem_arr[yi + 1, xi]
    z11 = dem_arr[yi + 1, xi + 1]
    z = (z00 * (1.0 - dx) + z01 * dx) * (1.0 - dy) + (z10 * (1.0 - dx) + z11 * dx) * dy
    
    # Also sample normals
    nx = dem_nx[yi, xi]
    ny = dem_ny[yi, xi]
    nz = dem_nz[yi, xi]
    return z, nx, ny, nz

def sample_worldcover(x_pts, y_pts):
    """Nearest neighbor sampling on 10m WorldCover raster."""
    px = np.clip(np.floor((x_pts - wc_gt[0]) / wc_gt[1]).astype(np.int32), 0, wc_arr.shape[1] - 1)
    py = np.clip(np.floor((y_pts - wc_gt[3]) / wc_gt[5]).astype(np.int32), 0, wc_arr.shape[0] - 1)
    return wc_arr[py, px]

# Precompute distance steps
NEAR_SKIP = 45.0  # start beyond the station's own 30 m cell: the DEM cannot describe the summit block the camera stands on
dists = np.arange(NEAR_SKIP, MAX_DIST + STEP_SIZE, STEP_SIZE, dtype=np.float32)  # shape (N_STEPS,)
N_STEPS = len(dists)
dist_sq_curv = CURV_FACTOR * (dists ** 2)

# Load font for peak labels
font_path = os.environ.get("D5_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
try:
    label_font = ImageFont.truetype(font_path, 11)
except OSError:  # labels are off by default (PANO_LABELS=0); any font will do
    label_font = ImageFont.load_default()
bold_path = os.environ.get("D5_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
bold_font = ImageFont.truetype(bold_path, 12) if os.path.exists(bold_path) else label_font

def render_station_panorama(stn):
    stn_num = stn["num"]
    stn_name = stn["name"]
    stn_x = stn["x"]
    stn_y = stn["y"]
    if POSITION == "highpoint":
        # D93: move to the highest cell of the 3x3 window around the station cell (as 09_viewsheds.py --position highpoint)
        c0 = int((stn_x - dem_gt[0]) / dem_gt[1]); r0 = int((stn_y - dem_gt[3]) / dem_gt[5])
        win = dem_arr[r0 - 1:r0 + 2, c0 - 1:c0 + 2]
        dr, dc = np.unravel_index(int(np.argmax(win)), win.shape)
        r1, c1 = r0 + dr - 1, c0 + dc - 1
        stn_x = dem_gt[0] + (c1 + 0.5) * dem_gt[1]; stn_y = dem_gt[3] + (r1 + 0.5) * dem_gt[5]
        print(f"  highpoint: cell ({r1},{c1}), {dem_arr[r1, c1]:.2f} m")
    print(f"\n--- Rendering Station {stn_num}: {stn_name} ---")
    t_start = time.time()
    
    # Geographic location and grid convergence
    lon0, lat0, _ = ct_to_geo.TransformPoint(stn_x, stn_y)
    # Vector pointing True North from station
    p_n = ct_to_grid.TransformPoint(lon0, lat0 + 0.01)
    gamma_deg = math.degrees(math.atan2(p_n[0] - stn_x, p_n[1] - stn_y))
    print(f"  Coordinates: lon={lon0:.5f}, lat={lat0:.5f}, grid convergence gamma={gamma_deg:.3f} deg")
    
    # Station DEM elevation + 1.6 m observer height
    # Observer on the station's own DEM cell (nearest, as r.viewshed and gdal_viewshed do), plus 1.6 m.
    # Bilinear sampling at the point mixed in lower neighbours on summits and put the eye below the next cell.
    ci = int((stn_x - dem_gt[0]) / dem_gt[1]); ri = int((stn_y - dem_gt[3]) / dem_gt[5])
    z_ground = np.array([dem_arr[ri, ci]])
    z_obs = float(z_ground[0]) + 1.6
    print(f"  Ground elevation: {z_ground[0]:.2f} m, Observer elevation: {z_obs:.2f} m")
    
    # Grid directions for 3600 azimuths (True North: 0 = True North)
    az_true_deg = np.arange(N_AZIMUTHS, dtype=np.float32) * AZ_STEP_DEG
    az_grid_deg = (az_true_deg + gamma_deg) % 360.0
    az_grid_rad = np.radians(az_grid_deg)
    
    sin_grid = np.sin(az_grid_rad)  # shape (3600,)
    cos_grid = np.cos(az_grid_rad)  # shape (3600,)
    
    # Sample points along rays: shape (3600, N_STEPS)
    xs = stn_x + sin_grid[:, None] * dists[None, :]
    ys = stn_y + cos_grid[:, None] * dists[None, :]
    
    # Bilinear sample DEM
    t_dem = time.time()
    zs, nxs, nys, nzs = bilinear_sample_dem(xs, ys)
    # Effective elevation with curvature and refraction
    zs_eff = zs - dist_sq_curv[None, :]
    
    # Vertical angles in degrees
    # theta = arctan((z_eff - z_obs) / d)
    vert_angles = np.degrees(np.arctan((zs_eff - z_obs) / dists[None, :]))  # shape (3600, N_STEPS)
    print(f"  DEM sampled in {time.time()-t_dem:.2f}s, vert range: {vert_angles.min():.2f}° to {vert_angles.max():.2f}°")
    
    # Sample WorldCover classes
    wc_classes = sample_worldcover(xs, ys)
    
    # Lambert shading
    lambert = np.clip(nxs * SUN_VEC[0] + nys * SUN_VEC[1] + nzs * SUN_VEC[2], 0.0, 1.0)
    shade = 0.42 + 0.58 * lambert  # range [0.42, 1.0]
    
    # Initialize output image buffer with sky
    pano_img = make_sky_background()  # (740, 3600, 3)
    
    # Horizon-max ray march per column
    skyline_angles = np.full(N_AZIMUTHS, -999.0, dtype=np.float32)
    skyline_dists = np.full(N_AZIMUTHS, 0.0, dtype=np.float32)
    
    # Pre-lookup colours for classes
    colour_lut = np.zeros((101, 3), dtype=np.float32)
    for c in range(101):
        colour_lut[c] = WC_COLOURS.get(c, DEFAULT_COLOUR)
    
    # March near-to-far
    curr_row_top = np.full(N_AZIMUTHS, IMG_HEIGHT, dtype=np.int32)
    
    t_march = time.time()
    for step_idx in range(N_STEPS):
        d = dists[step_idx]
        angles_at_step = vert_angles[:, step_idx]
        
        # Pixels where this step is higher than max seen so far
        is_higher = angles_at_step > skyline_angles
        if not np.any(is_higher):
            continue
            
        new_row = np.clip(np.round((VERT_MAX_DEG - angles_at_step) / DEG_PER_ROW).astype(np.int32), 0, IMG_HEIGHT)
        
        # Distance haze factor
        haze = float(np.clip(1.0 - math.exp(-(d / 21000.0) ** 1.1), 0.0, 0.82))
        
        # For columns where new_row < curr_row_top
        mask = (new_row < curr_row_top) & is_higher
        cols = np.where(mask)[0]
        if len(cols) == 0:
            continue
            
        classes = wc_classes[cols, step_idx]
        base_colours = colour_lut[classes]  # (K, 3)
        shades = shade[cols, step_idx, None]
        shaded_colours = base_colours * shades
        
        # Paint pixels in columns
        for idx, col in enumerate(cols):
            r_top = new_row[col]
            r_bot = curr_row_top[col]
            if r_top < r_bot:
                # Atmospheric haze towards sky
                sky_sample = pano_img[r_top:r_bot, col, :]
                terrain_col = (1.0 - haze) * shaded_colours[idx] + haze * sky_sample
                pano_img[r_top:r_bot, col, :] = terrain_col
                curr_row_top[col] = r_top
                skyline_angles[col] = angles_at_step[col]
                skyline_dists[col] = float(d)
                
    print(f"  Horizon-max march completed in {time.time()-t_march:.2f}s")
    
    # Save skyline JSON
    skyline_record = {
        "station": stn_num,
        "station_name": stn_name,
        "observer_elev_m": round(z_obs, 2),
        "azimuth_deg": [round(float(a), 1) for a in az_true_deg],
        "skyline_vert_angle_deg": [round(float(v), 3) for v in skyline_angles],
        "skyline_dist_m": [round(float(d), 1) for d in skyline_dists],
        "labeled_peaks": []
    }
    
    # Convert numpy image to PIL Image (RGB uint8)
    pano_uint8 = np.clip(np.round(pano_img), 0, 255).astype(np.uint8)
    pil_img = Image.fromarray(pano_uint8, mode="RGB")
    draw = ImageDraw.Draw(pil_img)
    
    # Label named peaks that are visible / on skyline within 30 km
    labeled_peaks = []
    seen_cols = []
    
    # Candidates from geojson
    candidates = []
    for feat in peaks_gj["features"]:
        props = feat["properties"]
        geom = feat["geometry"]
        p_name = props.get("name")
        if not p_name:
            continue
        p_type = props.get("feature_type", "")
        # Filter for peaks, mountains, passes, ridges
        px = props.get("x_epsg3979")
        py = props.get("y_epsg3979")
        if px is None or py is None:
            continue
        dx = px - stn_x
        dy = py - stn_y
        dist = math.hypot(dx, dy)
        if dist < 400.0 or dist > MAX_DIST:
            continue
            
        # Geographic azimuth
        lon_p, lat_p = geom["coordinates"]
        dlon = math.radians(lon_p - lon0)
        phi1, phi2 = math.radians(lat0), math.radians(lat_p)
        y_geo = math.sin(dlon) * math.cos(phi2)
        x_geo = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlon)
        geo_az = math.degrees(math.atan2(y_geo, x_geo)) % 360.0
        
        # Elevation
        elev = props.get("elevation") or props.get("elevation_mrdem30_m")
        if elev is None:
            continue
        elev = float(elev)
        
        # Effective elevation & vertical angle
        elev_eff = elev - CURV_FACTOR * (dist ** 2)
        vert_ang = math.degrees(math.atan2(elev_eff - z_obs, dist))
        
        col = int(round(geo_az / AZ_STEP_DEG)) % N_AZIMUTHS
        sky_ang = skyline_angles[col]
        
        # Check if visible (near or at skyline)
        # Peak is visible if vert_ang >= sky_ang - 0.25 deg
        on_sky = vert_ang >= sky_ang - 0.35
        if on_sky or seen_in_viewshed(stn_num, px, py):
            candidates.append({
                "name": p_name,
                "type": p_type,
                "dist_km": dist / 1000.0,
                "dist_m": dist,
                "az_deg": geo_az,
                "vert_ang": vert_ang,
                "col": col,
                "sky_ang": float(sky_ang),
                "elev": elev,
                "elev_src": props.get("elevation_source") or "MRDEM-30",
                "x": px, "y": py,
            })

    # D97: border peaks come twice (CGNDB Alberta and BC records). Keep one per name within 1 km,
    # preferring a published height.
    deduped = []
    for c in sorted(candidates, key=lambda c: (c["elev_src"] == "MRDEM-30", c["dist_m"])):
        if any(d["name"] == c["name"] and math.hypot(d["x"] - c["x"], d["y"] - c["y"]) < 1000.0 for d in deduped):
            continue
        deduped.append(c)
    candidates = deduped
            
    # Sort candidates by prominence / elevation
    candidates.sort(key=lambda c: (-c["elev"], c["dist_km"]))
    
    # Priority names mentioned in plates and thesis
    PRIORITY_NAMES = [
        "Mount Blakiston", "Blakiston", "Festubert", "Lost Mountain", "Lost",
        "Lone Mountain", "Lone", "Mount Hawkins", "Hawkins", "Anderson",
        "South Kootenay Pass", "Red Rock", "Cloudy Ridge", "Mount Glendowan",
        "Mount Dungarvan", "Mount Galwey", "Mount Crandell", "Mount Rowe",
        "Mount Lineham", "Avion Ridge", "Kenow Mountain"
    ]
    
    def get_priority(name):
        for p in PRIORITY_NAMES:
            if p.lower() in name.lower():
                return 0
        return 1

    candidates.sort(key=lambda c: (get_priority(c["name"]), -c["elev"]))

    # Every visible named feature, for the page's hover markers (Claude 11-05).
    skyline_record["peaks"] = [{
        "name": c["name"], "type": c["type"],
        "azimuth_deg": round(c["az_deg"], 1),
        "vert_angle_deg": round(c["vert_ang"], 2),
        "distance_km": round(c["dist_km"], 2),
        "elevation_m": round(c["elev"], 0),
        "elevation_source": c["elev_src"],
        "on_skyline": bool(c["vert_ang"] >= c["sky_ang"] - 0.35),
        "col": c["col"],
        "row": int(round((VERT_MAX_DEG - c["vert_ang"]) / DEG_PER_ROW)),
    } for c in sorted(candidates, key=lambda c: c["az_deg"])]
    skyline_record["image"] = {"width": IMG_WIDTH, "height": IMG_HEIGHT,
                               "deg_per_px": AZ_STEP_DEG, "vert_max_deg": VERT_MAX_DEG}
    
    used_columns = []
    for cand in candidates:
        col = cand["col"]
        # Enforce minimum separation of 45 pixels (~4.5 deg)
        too_close = False
        for uc in used_columns:
            diff = min(abs(col - uc), N_AZIMUTHS - abs(col - uc))
            if diff < 45:
                too_close = True
                break
        if too_close:
            continue
            
        if not BURN_LABELS:
            continue
        used_columns.append(col)
        labeled_peaks.append(cand)
        skyline_record["labeled_peaks"].append({
            "name": cand["name"],
            "distance_km": round(cand["dist_km"], 2),
            "azimuth_deg": round(cand["az_deg"], 1),
            "vert_angle_deg": round(cand["vert_ang"], 2)
        })
        
        # Draw on image
        # Pixel position of peak summit
        row_peak = int(round((VERT_MAX_DEG - cand["vert_ang"]) / DEG_PER_ROW))
        row_peak = max(15, min(row_peak, IMG_HEIGHT - 30))
        
        # Draw vertical marker tick
        draw.line([(col, row_peak - 14), (col, row_peak)], fill=(40, 40, 40), width=2)
        draw.line([(col, row_peak - 14), (col, row_peak)], fill=(255, 255, 255), width=1)
        
        # Text label: Name and distance
        text_str = f"{cand['name']} ({cand['dist_km']:.1f}k)"
        bbox = label_font.getbbox(text_str)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        tx = col - tw // 2
        ty = row_peak - 28 - th
        if ty < 4:
            ty = 4
        # Draw subtle halo / outline for text
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
            draw.text((tx + dx, ty + dy), text_str, font=label_font, fill=(255, 255, 255))
        draw.text((tx, ty), text_str, font=label_font, fill=(20, 25, 30))
        
    print(f"  Labeled {len(labeled_peaks)} prominent peaks")
    
    # Save colour WebP
    out_webp = f"{OUT}/pano/pano_{stn_num}{SUFFIX}.webp"
    pil_img.save(out_webp, "WEBP", quality=82)
    print(f"  Saved {out_webp} ({os.path.getsize(out_webp)/1024:.1f} KB)")
    
    # Save greyscale WebP
    grey_img = pil_img.convert("L")
    out_grey = f"{OUT}/pano/pano_{stn_num}{SUFFIX}_grey.webp"
    grey_img.save(out_grey, "WEBP", quality=82)
    print(f"  Saved {out_grey} ({os.path.getsize(out_grey)/1024:.1f} KB)")
    
    # Save skyline JSON
    out_json = f"{OUT}/pano/skyline_{stn_num}{SUFFIX}.json"
    with open(out_json, "w") as f:
        json.dump(skyline_record, f)
    print(f"  Saved {out_json} ({os.path.getsize(out_json)/1024:.1f} KB)")
    print(f"  Station {stn_num} completed in {time.time()-t_start:.2f}s")

def main():
    print("Starting simulated panorama rendering for all 6 stations...")
    t_all = time.time()
    for stn in STATIONS:
        render_station_panorama(stn)
    print(f"\nAll 6 stations successfully rendered in {time.time()-t_all:.2f}s!")

if __name__ == "__main__":
    main()
