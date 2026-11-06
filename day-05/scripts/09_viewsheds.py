#!/usr/bin/env python3
"""
Deterministic viewshed computations (Runs 1-6) for the 1914 Bridgland camera stations:
  1. Main viewsheds: out/vs_<stn>_main.tif (station point, observer=1.6m, target=0m)
  2. Position & height variants: out/variants.csv and out/vs_<stn>_unc.tif
  3. Cumulative main viewshed: out/cum_main.tif (when all 6 stations are present)
  4. GDAL cross-check: gdal_viewshed (-cc 0.87, -oz 1.6, -tz 0, -md 30000) vs GRASS r.viewshed
  5. Forest scenarios (10m, 20m, 30m canopy): out/vs_<stn>_forest<h>.tif and out/cum_forest<h>.tif
  6. Drone scenario (120m observer): out/vs_<stn>_drone.tif and out/cum_drone.tif

Usage:
  /usr/bin/python3 day-05/scripts/09_viewsheds.py --stations 84
  /usr/bin/python3 day-05/scripts/09_viewsheds.py --stations 84 85 86 87 88 89
"""

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from osgeo import gdal
from scipy.ndimage import binary_dilation, binary_erosion

gdal.DontUseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
DERIVED_DIR = SLICE_A_DIR / "derived"

ALL_STATIONS = ["84", "85", "86", "87", "88", "89"]
DEM_PATH = str(Path(os.environ.get("MC26_DEM_PATH", str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif"))).resolve())
FOREST_MASK_PATH = str(Path(os.environ.get("MC26_FOREST_MASK_PATH", str(DERIVED_DIR / "forest_mask_viewshed_30m_epsg3979.tif"))).resolve())
_stn_cand = SLICE_A_DIR / "stations.csv"
if not _stn_cand.exists():
    _stn_cand = DERIVED_DIR / "stations.csv"
if not _stn_cand.exists():
    _stn_cand = DATA_DIR / "stations.csv"
STATIONS_CSV_PATH = str(Path(os.environ.get("MC26_STATIONS_CSV", str(_stn_cand))).resolve())
OUT_DIR = str(Path(os.environ.get("MC26_VIEWSHEDS_DIR", str(DATA_DIR / "viewsheds"))).resolve())


def write_byte_geotiff(path, arr, ref_ds):
    """Write a 2D uint8 array as a DEFLATE-compressed Byte GeoTIFF matching ref_ds."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    driver = gdal.GetDriverByName("GTiff")
    rows, cols = arr.shape
    ds = driver.Create(
        path,
        cols,
        rows,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256"],
    )
    ds.SetGeoTransform(ref_ds.GetGeoTransform())
    ds.SetProjection(ref_ds.GetProjection())
    band = ds.GetRasterBand(1)
    band.WriteArray(arr.astype(np.uint8))
    band.FlushCache()
    ds = None


def write_float_geotiff(path, arr, ref_ds):
    """Write a 2D float32 array as a GeoTIFF matching ref_ds."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    driver = gdal.GetDriverByName("GTiff")
    rows, cols = arr.shape
    ds = driver.Create(
        path,
        cols,
        rows,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
    )
    ds.SetGeoTransform(ref_ds.GetGeoTransform())
    ds.SetProjection(ref_ds.GetProjection())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32767.0)
    band.WriteArray(arr.astype(np.float32))
    band.FlushCache()
    ds = None


def read_geotiff(path):
    ds = gdal.Open(path)
    arr = ds.GetRasterBand(1).ReadAsArray()
    return arr, ds


def load_station_specs(dem_arr, gt):
    """Parse in/stations.csv and build main + variant definitions per station."""
    with open(STATIONS_CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def xy_to_rc(x, y):
        c = int((x - gt[0]) / gt[1])
        r = int((y - gt[3]) / gt[5])
        return r, c

    def rc_to_xy(r, c):
        x = gt[0] + (c + 0.5) * gt[1]
        y = gt[3] + (r + 0.5) * gt[5]
        return x, y

    specs = {}
    for stn in ALL_STATIONS:
        srows = [r for r in rows if r["station_num"] == stn]
        r0 = srows[0]
        sx = float(r0["station_x_epsg3979"])
        sy = float(r0["station_y_epsg3979"])
        sr, sc = xy_to_rc(sx, sy)
        sdem = float(dem_arr[sr, sc])

        # 3x3 window around (sr, sc)
        win3 = dem_arr[sr - 1 : sr + 2, sc - 1 : sc + 2]
        max3_val = float(np.max(win3))
        drow, dcol = np.unravel_index(np.argmax(win3), win3.shape)
        max3_r = int(sr + drow - 1)
        max3_c = int(sc + dcol - 1)
        max3_x, max3_y = rc_to_xy(max3_r, max3_c)
        is_local_max_3x3 = (max3_r == sr and max3_c == sc) or (sdem >= max3_val)

        # 5x5 window around (sr, sc)
        win5 = dem_arr[sr - 2 : sr + 3, sc - 2 : sc + 3]
        max5_val = float(np.max(win5))

        # Variants list
        variants = []
        skipped_elevs = []

        # (a) Main point with observer raised so absolute height = recorded_elevation + 1.6m
        rec_elevs = set()
        for r in srows:
            if r["recorded_elevation_m"].strip():
                rec_elevs.add(float(r["recorded_elevation_m"]))
            if r["station_elev_m"].strip():
                rec_elevs.add(float(r["station_elev_m"]))

        for rec_el in sorted(rec_elevs):
            abs_h = rec_el + 1.6
            if abs_h < sdem + 1.6 - 1e-6:
                skipped_elevs.append(
                    {
                        "recorded_elevation_m": rec_el,
                        "abs_height_m": abs_h,
                        "main_dem_plus_1_6_m": sdem + 1.6,
                    }
                )
                continue
            obs_off = abs_h - sdem
            variants.append(
                {
                    "station": stn,
                    "variant_id": f"elev_{int(round(rec_el))}",
                    "variant_type": "recorded_elevation",
                    "x": sx,
                    "y": sy,
                    "row": sr,
                    "col": sc,
                    "dem_value": sdem,
                    "obs_elev": obs_off,
                    "abs_observer_height": abs_h,
                    "notes": f"Main point raised to recorded elevation {rec_el:.0f}m + 1.6m",
                }
            )

        # (b) 3x3-maximum cell at DEM + 1.6
        variants.append(
            {
                "station": stn,
                "variant_id": "max_3x3",
                "variant_type": "max_3x3_cell",
                "x": max3_x,
                "y": max3_y,
                "row": max3_r,
                "col": max3_c,
                "dem_value": max3_val,
                "obs_elev": 1.6,
                "abs_observer_height": max3_val + 1.6,
                "notes": f"3x3 max cell (dcol={max3_c-sc}, drow={max3_r-sr})",
            }
        )

        # (c) Each credible (non-excluded) location record with coordinates at DEM + 1.6
        for r in srows:
            use_val = r["use"].strip()
            if use_val.startswith("excluded") or use_val == "no_coords":
                continue
            if not r["x_epsg3979"].strip() or not r["y_epsg3979"].strip():
                continue
            lx = float(r["x_epsg3979"])
            ly = float(r["y_epsg3979"])
            lr, lc = xy_to_rc(lx, ly)
            ldem = float(dem_arr[lr, lc])
            loc_id = r["location_id"].strip()
            variants.append(
                {
                    "station": stn,
                    "variant_id": f"loc_{loc_id}",
                    "variant_type": f"location_{use_val}",
                    "x": lx,
                    "y": ly,
                    "row": lr,
                    "col": lc,
                    "dem_value": ldem,
                    "obs_elev": 1.6,
                    "abs_observer_height": ldem + 1.6,
                    "dist_from_station_m": float(r["dist_from_station_m"])
                    if r["dist_from_station_m"].strip()
                    else 0.0,
                    "same_cell_as_main": (lr == sr and lc == sc),
                    "notes": f"visit {r['visit_year']} loc_id={loc_id} ({use_val})",
                }
            )

        specs[stn] = {
            "station": stn,
            "mlp_station_id": r0["mlp_station_id"],
            "station_name": r0["station_name"],
            "x": sx,
            "y": sy,
            "row": sr,
            "col": sc,
            "dem_m": sdem,
            "max_3x3_m": max3_val,
            "max_3x3_dcol": max3_c - sc,
            "max_3x3_drow": max3_r - sr,
            "max_5x5_m": max5_val,
            "is_3x3_local_max": is_local_max_3x3,
            "variants": variants,
            "skipped_elevations": skipped_elevs,
        }
    return specs


def run_grass_batch_worker(worker_args):
    """
    Executes a list of viewshed jobs sharing a single input DEM inside one GRASS --tmp-project.
    worker_args: (dem_path, jobs_list, tmp_root)
    Each job in jobs_list: dict with keys:
      job_id, x, y, obs_elev, target_elev, max_dist, out_tif (optional)
    Returns dict mapping job_id -> (out_tif_or_bytes, elapsed_sec)
    """
    dem_path, jobs, tmp_root = worker_args
    os.makedirs(tmp_root, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="grass_worker_", dir=tmp_root)
    env = os.environ.copy()
    env["PATH"] = f"/usr/bin:{env.get('PATH', '')}"
    env["TMPDIR"] = work_dir
    env["GRASS_VERBOSE"] = "0"

    script_lines = [
        "set -e",
        f"r.external input='{dem_path}' output=dem --quiet",
    ]
    for j in jobs:
        jid = j["job_id"]
        x, y = j["x"], j["y"]
        obs_elev = j["obs_elev"]
        target_elev = j.get("target_elev", 0.0)
        max_dist = j.get("max_dist", 30000)
        out_tif = j["out_tif"]
        script_lines.append(
            f"t0=$(date +%s%3N)\n"
            f"r.viewshed -c -r -b input=dem output=vs_{jid} "
            f"coordinates={x:.4f},{y:.4f} observer_elevation={obs_elev:.6f} "
            f"target_elevation={target_elev:.6f} max_distance={max_dist} "
            f"refraction_coeff=0.13 memory=300 --overwrite --quiet\n"
            f"r.out.gdal -c input=vs_{jid} output='{out_tif}' type=Byte "
            f"createopt='COMPRESS=DEFLATE,TILED=YES,BLOCKXSIZE=256,BLOCKYSIZE=256' --overwrite --quiet\n"
            f"t1=$(date +%s%3N)\n"
            f"echo \"TIMING:{jid}:$((t1-t0))\""
        )

    sh_path = os.path.join(work_dir, "batch.sh")
    with open(sh_path, "w", encoding="utf-8") as f:
        f.write("\n".join(script_lines) + "\n")

    grass_bin = shutil.which("grass") or "grass"
    cmd = [grass_bin, "--tmp-project", dem_path, "--exec", "bash", sh_path]
    t_start = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    t_total = time.time() - t_start
    shutil.rmtree(work_dir, ignore_errors=True)

    if proc.returncode != 0:
        raise RuntimeError(
            f"GRASS worker failed (rc={proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    timings = {}
    for line in proc.stdout.splitlines():
        if line.startswith("TIMING:"):
            parts = line.strip().split(":")
            timings[parts[1]] = float(parts[2]) / 1000.0
    return {"timings": timings, "wall_sec": t_total}


def run_gdal_crosscheck(stn_spec, ref_ds, grass_main_arr, tmp_root):
    """Run gdal_viewshed for a station's main parameters and compare against GRASS."""
    stn = stn_spec["station"]
    sx, sy = stn_spec["x"], stn_spec["y"]
    tmp_gdal_tif = os.path.join(tmp_root, f"gdal_{stn}_main.tif")
    cmd = [
        "gdal_viewshed",
        "-q",
        "-b",
        "1",
        "-ox",
        f"{sx:.4f}",
        "-oy",
        f"{sy:.4f}",
        "-oz",
        "1.6",
        "-tz",
        "0.0",
        "-md",
        "30000",
        "-cc",
        "0.87",
        "-vv",
        "1",
        "-iv",
        "0",
        "-ov",
        "0",
        "-co",
        "COMPRESS=DEFLATE",
        DEM_PATH,
        tmp_gdal_tif,
    ]
    t0 = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - t0

    gt_full = ref_ds.GetGeoTransform()
    ds_sub = gdal.Open(tmp_gdal_tif)
    gt_sub = ds_sub.GetGeoTransform()
    sub_arr = ds_sub.GetRasterBand(1).ReadAsArray()
    ds_sub = None
    if os.path.exists(tmp_gdal_tif):
        os.remove(tmp_gdal_tif)

    gdal_arr = np.zeros_like(grass_main_arr, dtype=np.uint8)
    c0 = int(round((gt_sub[0] - gt_full[0]) / gt_full[1]))
    r0 = int(round((gt_sub[3] - gt_full[3]) / gt_full[5]))
    r1 = min(gdal_arr.shape[0], r0 + sub_arr.shape[0])
    c1 = min(gdal_arr.shape[1], c0 + sub_arr.shape[1])
    sr0 = max(0, -r0)
    sc0 = max(0, -c0)
    dr0 = max(0, r0)
    dc0 = max(0, c0)
    gdal_arr[dr0:r1, dc0:c1] = sub_arr[sr0 : sr0 + (r1 - dr0), sc0 : sc0 + (c1 - dc0)]

    # Compute agreement metrics
    g1 = grass_main_arr == 1
    g2 = gdal_arr == 1
    grass_vis = int(np.sum(g1))
    gdal_vis = int(np.sum(g2))
    both_vis = int(np.sum(g1 & g2))
    either_vis = int(np.sum(g1 | g2))
    jaccard = both_vis / either_vis if either_vis > 0 else 1.0

    agree_full = float(np.mean(g1 == g2))
    diff_mask = g1 != g2
    diff_count = int(np.sum(diff_mask))
    grass_only = int(np.sum(g1 & ~g2))
    gdal_only = int(np.sum(~g1 & g2))

    # Distance from station for each cell
    yy, xx = np.indices(grass_main_arr.shape)
    xs = gt_full[0] + (xx + 0.5) * gt_full[1]
    ys = gt_full[3] + (yy + 0.5) * gt_full[5]
    dist = np.hypot(xs - sx, ys - sy)
    in30k = dist <= 30000.0
    agree_30k = float(np.mean(g1[in30k] == g2[in30k]))

    # Where do they disagree? Boundary vs interior & distance bands
    edge_1px = binary_dilation(g1, iterations=1) ^ binary_erosion(g1, iterations=1)
    edge_2px = binary_dilation(g1, iterations=2) ^ binary_erosion(g1, iterations=2)
    share_on_1px_edge = float(np.mean(edge_1px[diff_mask])) if diff_count > 0 else 0.0
    share_on_2px_edge = float(np.mean(edge_2px[diff_mask])) if diff_count > 0 else 0.0

    near_share = float(np.mean(dist[diff_mask] < 5000.0)) if diff_count > 0 else 0.0
    mid_share = (
        float(np.mean((dist[diff_mask] >= 5000.0) & (dist[diff_mask] < 15000.0)))
        if diff_count > 0
        else 0.0
    )
    far_share = float(np.mean(dist[diff_mask] >= 15000.0)) if diff_count > 0 else 0.0
    median_dist_m = float(np.median(dist[diff_mask])) if diff_count > 0 else 0.0

    return {
        "station": stn,
        "grass_visible_cells": grass_vis,
        "gdal_visible_cells": gdal_vis,
        "both_visible_cells": both_vis,
        "grass_only_cells": grass_only,
        "gdal_only_cells": gdal_only,
        "differing_cells": diff_count,
        "agreement_full_grid_pct": agree_full * 100.0,
        "agreement_within_30km_pct": agree_30k * 100.0,
        "jaccard": jaccard,
        "share_on_1px_ridge_edge_pct": share_on_1px_edge * 100.0,
        "share_on_2px_ridge_edge_pct": share_on_2px_edge * 100.0,
        "disagree_near_lt5km_pct": near_share * 100.0,
        "disagree_mid_5to15km_pct": mid_share * 100.0,
        "disagree_far_gt15km_pct": far_share * 100.0,
        "disagree_median_dist_m": median_dist_m,
        "gdal_elapsed_sec": elapsed,
    }


def main():
    global OUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", nargs="+", default=ALL_STATIONS)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--out-dir", default=OUT_DIR)
    # D93 (GW, 11-05): "station" puts each observer on the MLP station point, as recorded;
    # "highpoint" moves it to the highest 30 m DEM cell of the 3x3 window around that point
    # (at most 42 m away), still 1.6 m above the cell. Highpoint runs go to their own folder.
    parser.add_argument("--position", choices=["station", "highpoint"], default="station")
    args = parser.parse_args()
    if args.out_dir:
        OUT_DIR = args.out_dir
    if args.position == "highpoint" and args.out_dir == parser.get_default("out_dir"):
        OUT_DIR = os.environ.get("MC26_VIEWSHEDS_HP_DIR", str(DATA_DIR / "viewsheds_highpoint"))

    t_script_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp_root = os.path.join(OUT_DIR, ".tmp_viewsheds")
    os.makedirs(tmp_root, exist_ok=True)

    dem_arr, dem_ds = read_geotiff(DEM_PATH)
    fmask_arr, _ = read_geotiff(FOREST_MASK_PATH)
    gt = dem_ds.GetGeoTransform()
    specs = load_station_specs(dem_arr, gt)
    if args.position == "highpoint":
        for sp in specs.values():
            r = sp["row"] + sp["max_3x3_drow"]
            c = sp["col"] + sp["max_3x3_dcol"]
            sp.update(row=r, col=c, dem_m=float(dem_arr[r, c]),
                      x=gt[0] + (c + 0.5) * gt[1], y=gt[3] + (r + 0.5) * gt[5])
            print(f"highpoint {sp['station']}: cell ({r},{c}) DEM {sp['dem_m']:.2f} m")

    selected_stations = [s for s in args.stations if s in specs]
    print(f"Running deterministic viewsheds for stations: {selected_stations}")

    # Prepare forest canopy DEMs (10m, 20m, 30m added to forested cells where fmask == 1).
    # Note: All 6 station main cells have fmask == 0 (bare alpine ridge/summit).
    # Even if any station cell were forested, we keep observer on bare DEM + 1.6m.
    forest_dem_paths = {}
    for h in (10, 20, 30):
        f_dem = dem_arr.astype(np.float32) + np.where(fmask_arr == 1, float(h), 0.0).astype(
            np.float32
        )
        # Ensure all station main cells remain at bare DEM height so observer is at bare DEM + 1.6m
        for stn in ALL_STATIONS:
            sr, sc = specs[stn]["row"], specs[stn]["col"]
            f_dem[sr, sc] = dem_arr[sr, sc]
        fpath = os.path.join(tmp_root, f"dem_forest{h}.tif")
        write_float_geotiff(fpath, f_dem, dem_ds)
        forest_dem_paths[h] = fpath

    # Build GRASS viewshed jobs
    # Group jobs by input DEM and distribute across worker batches
    bare_jobs = []
    forest_jobs = {10: [], 20: [], 30: []}

    for stn in selected_stations:
        sp = specs[stn]
        # 1. Main viewshed
        bare_jobs.append(
            {
                "job_id": f"main_{stn}",
                "x": sp["x"],
                "y": sp["y"],
                "obs_elev": 1.6,
                "target_elev": 0.0,
                "max_dist": 30000,
                "out_tif": os.path.join(OUT_DIR, f"vs_{stn}_main.tif"),
            }
        )
        # 2. Variants
        for v in sp["variants"]:
            vid = v["variant_id"]
            bare_jobs.append(
                {
                    "job_id": f"var_{stn}_{vid}",
                    "x": v["x"],
                    "y": v["y"],
                    "obs_elev": v["obs_elev"],
                    "target_elev": 0.0,
                    "max_dist": 30000,
                    "out_tif": os.path.join(tmp_root, f"vs_{stn}_var_{vid}.tif"),
                }
            )
        # 6. Drone viewshed (120m above DEM)
        bare_jobs.append(
            {
                "job_id": f"drone_{stn}",
                "x": sp["x"],
                "y": sp["y"],
                "obs_elev": 120.0,
                "target_elev": 0.0,
                "max_dist": 30000,
                "out_tif": os.path.join(OUT_DIR, f"vs_{stn}_drone.tif"),
            }
        )
        # 5. Forest scenarios (10m, 20m, 30m)
        for h in (10, 20, 30):
            forest_jobs[h].append(
                {
                    "job_id": f"forest{h}_{stn}",
                    "x": sp["x"],
                    "y": sp["y"],
                    "obs_elev": 1.6,
                    "target_elev": 0.0,
                    "max_dist": 30000,
                    "out_tif": os.path.join(OUT_DIR, f"vs_{stn}_forest{h}.tif"),
                }
            )

    # Chunk jobs so up to args.workers GRASS instances run concurrently
    worker_tasks = []
    # Split bare_jobs into chunks of ~2-3 jobs per worker for high parallelism
    chunk_size = max(1, (len(bare_jobs) + args.workers - 1) // args.workers)
    for i in range(0, len(bare_jobs), chunk_size):
        worker_tasks.append((DEM_PATH, bare_jobs[i : i + chunk_size], tmp_root))
    for h in (10, 20, 30):
        for j in forest_jobs[h]:
            worker_tasks.append((forest_dem_paths[h], [j], tmp_root))

    print(
        f"Dispatching {len(bare_jobs) + sum(len(v) for v in forest_jobs.values())} GRASS r.viewshed runs across {len(worker_tasks)} worker batches (max_workers={args.workers})..."
    )
    t_grass0 = time.time()
    all_timings = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_grass_batch_worker, wt) for wt in worker_tasks]
        for fut in as_completed(futs):
            res = fut.result()
            all_timings.update(res["timings"])
    t_grass_wall = time.time() - t_grass0
    print(f"GRASS viewsheds completed in {t_grass_wall:.2f}s wall time.")

    # Process variants, position-uncertainty rasters, and GDAL cross-checks
    # Load existing metrics if partial station run so we merge cleanly
    metrics_path = os.path.join(OUT_DIR, "deterministic_metrics.json")
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                saved_metrics = json.load(f)
        except Exception:
            saved_metrics = {}
    else:
        saved_metrics = {}

    stations_data = saved_metrics.get("stations", {})
    timings_data = saved_metrics.get("timings", {})
    timings_data.update(all_timings)

    CELL_AREA_KM2 = (30.0 * 30.0) / 1e6  # 0.0009 km2 per cell

    for stn in selected_stations:
        sp = specs[stn]
        main_tif = os.path.join(OUT_DIR, f"vs_{stn}_main.tif")
        main_arr, _ = read_geotiff(main_tif)
        main_bool = main_arr == 1
        main_vis = int(np.sum(main_bool))

        # Variants evaluation & uncertainty sum raster
        unc_arr = np.zeros_like(main_arr, dtype=np.uint8)
        var_records = []
        for v in sp["variants"]:
            vid = v["variant_id"]
            vtif = os.path.join(tmp_root, f"vs_{stn}_var_{vid}.tif")
            var_arr, _ = read_geotiff(vtif)
            var_bool = var_arr == 1
            unc_arr += var_arr.astype(np.uint8)
            vis_cnt = int(np.sum(var_bool))
            inter = int(np.sum(main_bool & var_bool))
            union = int(np.sum(main_bool | var_bool))
            jacc = inter / union if union > 0 else 1.0
            var_records.append(
                {
                    "station": stn,
                    "variant_id": vid,
                    "variant_type": v["variant_type"],
                    "x": round(v["x"], 2),
                    "y": round(v["y"], 2),
                    "dem_value": round(v["dem_value"], 2),
                    "abs_observer_height": round(v["abs_observer_height"], 2),
                    "visible_cell_count": vis_cnt,
                    "visible_area_km2": round(vis_cnt * CELL_AREA_KM2, 4),
                    "jaccard_main": round(jacc, 6),
                    "notes": v.get("notes", ""),
                }
            )
            if os.path.exists(vtif):
                os.remove(vtif)

        unc_tif = os.path.join(OUT_DIR, f"vs_{stn}_unc.tif")
        write_byte_geotiff(unc_tif, unc_arr, dem_ds)

        # GDAL cross-check
        gdal_info = run_gdal_crosscheck(sp, dem_ds, main_arr, tmp_root)

        # Forest & Drone counts
        forest_counts = {}
        for h in (10, 20, 30):
            f_arr, _ = read_geotiff(os.path.join(OUT_DIR, f"vs_{stn}_forest{h}.tif"))
            fcnt = int(np.sum(f_arr == 1))
            forest_counts[str(h)] = {
                "visible_cells": fcnt,
                "visible_area_km2": round(fcnt * CELL_AREA_KM2, 4),
            }

        drone_arr, _ = read_geotiff(os.path.join(OUT_DIR, f"vs_{stn}_drone.tif"))
        drone_cnt = int(np.sum(drone_arr == 1))

        # Uncertainty summary
        unc_vals, unc_cnts = np.unique(unc_arr, return_counts=True)
        unc_hist = {int(k): int(v) for k, v in zip(unc_vals, unc_cnts)}

        stations_data[stn] = {
            "station": stn,
            "station_name": sp["station_name"],
            "mlp_station_id": sp["mlp_station_id"],
            "x": sp["x"],
            "y": sp["y"],
            "row": sp["row"],
            "col": sp["col"],
            "dem_m": round(sp["dem_m"], 2),
            "max_3x3_m": round(sp["max_3x3_m"], 2),
            "max_3x3_dcol": sp["max_3x3_dcol"],
            "max_3x3_drow": sp["max_3x3_drow"],
            "max_5x5_m": round(sp["max_5x5_m"], 2),
            "is_3x3_local_max": sp["is_3x3_local_max"],
            "skipped_elevations": sp["skipped_elevations"],
            "main_visible_cells": main_vis,
            "main_visible_area_km2": round(main_vis * CELL_AREA_KM2, 4),
            "drone_visible_cells": drone_cnt,
            "drone_visible_area_km2": round(drone_cnt * CELL_AREA_KM2, 4),
            "forest": forest_counts,
            "variants": var_records,
            "num_variants": len(var_records),
            "uncertainty_histogram": unc_hist,
            "gdal_crosscheck": gdal_info,
        }

    # Write out/variants.csv across all processed stations in canonical order
    variants_csv_path = os.path.join(OUT_DIR, "variants.csv")
    with open(variants_csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "station",
            "variant_id",
            "x",
            "y",
            "dem_value",
            "abs_observer_height",
            "visible_cell_count",
            "jaccard_main",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for stn in ALL_STATIONS:
            if stn in stations_data:
                for v in stations_data[stn]["variants"]:
                    writer.writerow({k: v[k] for k in fieldnames})

    # If all 6 stations have outputs, build cumulative rasters:
    # cum_main.tif, cum_forest10.tif, cum_forest20.tif, cum_forest30.tif, cum_drone.tif
    cum_metrics = saved_metrics.get("cumulative", {})
    if all(
        os.path.exists(os.path.join(OUT_DIR, f"vs_{s}_main.tif")) for s in ALL_STATIONS
    ):
        print("Computing cumulative viewshed rasters across all 6 stations...")
        cum_defs = [
            ("main", "cum_main.tif", lambda s: f"vs_{s}_main.tif"),
            ("forest10", "cum_forest10.tif", lambda s: f"vs_{s}_forest10.tif"),
            ("forest20", "cum_forest20.tif", lambda s: f"vs_{s}_forest20.tif"),
            ("forest30", "cum_forest30.tif", lambda s: f"vs_{s}_forest30.tif"),
            ("drone", "cum_drone.tif", lambda s: f"vs_{s}_drone.tif"),
        ]
        for cname, out_name, fn_pat in cum_defs:
            acc = np.zeros_like(dem_arr, dtype=np.uint8)
            for s in ALL_STATIONS:
                a, _ = read_geotiff(os.path.join(OUT_DIR, fn_pat(s)))
                acc += (a == 1).astype(np.uint8)
            out_path = os.path.join(OUT_DIR, out_name)
            write_byte_geotiff(out_path, acc, dem_ds)
            vals, cnts = np.unique(acc, return_counts=True)
            hist = {int(k): int(v) for k, v in zip(vals, cnts)}
            for k in range(7):
                hist.setdefault(k, 0)
            vis_any = int(np.sum(acc >= 1))
            cum_metrics[cname] = {
                "file": out_name,
                "histogram_cells": {str(k): hist[k] for k in range(7)},
                "histogram_area_km2": {
                    str(k): round(hist[k] * CELL_AREA_KM2, 4) for k in range(7)
                },
                "any_visible_cells": vis_any,
                "any_visible_area_km2": round(vis_any * CELL_AREA_KM2, 4),
            }

    shutil.rmtree(tmp_root, ignore_errors=True)
    total_wall = time.time() - t_script_start

    out_json = {
        "stations": stations_data,
        "cumulative": cum_metrics,
        "timings": timings_data,
        "last_run_stations": selected_stations,
        "last_run_grass_wall_sec": round(t_grass_wall, 3),
        "last_run_total_wall_sec": round(total_wall, 3),
    }
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2)

    print(f"Done in {total_wall:.2f}s. Metrics saved to {metrics_path}.")


if __name__ == "__main__":
    main()
