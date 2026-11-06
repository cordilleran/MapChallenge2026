#!/usr/bin/env python3
"""
Probable viewshed (Monte Carlo DEM error propagation, Spec item 7):
- Stated accuracy of NRCan MRDEM-30:
  NRCan National Elevation Data Strategy / CanElevation MRDEM documentation
  (https://geo.ca/initiatives/national-elevation-data-strategy/ and Open Government
  record https://open.canada.ca/data/en/dataset/18752265-bda3-498c-a4ba-9dfe68cb98da):
  "Vertical accuracy (on bare-earth surface): ~1.6 m when the source is HRDEM and
   ~2.6 m when the source is GLO-30."
  We use RMSE = 2.6 m by default (the stated bare-earth accuracy for Copernicus GLO-30 source,
  applicable to the Rocky Mountain alpine terrain of Waterton Lakes), and --rmse 8 for a
  pessimistic second run written to $MC26_DAY05_DIR/viewsheds_rmse8. The 150 m correlation
  length is an assumed value, not measured for this terrain.
- Generates spatially correlated Gaussian error fields with RMSE = 2.6 m and correlation
  length L = 150 m (Gaussian covariance C(r) = sigma^2 * exp(-(r/L)^2) via 2D FFT with
  fixed deterministic seeds `seed = int(stn) * 1000 + run_idx`).
- Adds each error field to the DEM and runs r.viewshed (-c -r -b, refraction_coeff=0.13,
  observer_elevation=1.6, target_elevation=0.0, max_distance=30000).
- Outputs prob_<stn>.tif in the output folder (viewsheds/, or viewsheds_rmse8/ for the 8 m run) as the share of runs (0 to 100, Byte) in which each cell is seen.

Usage:
  /usr/bin/python3 day-05/scripts/10_probable_viewsheds.py --stations 84 --n-runs 3
  /usr/bin/python3 day-05/scripts/10_probable_viewsheds.py --stations 84 85 86 87 88 89 --n-runs 50
"""

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from osgeo import gdal

gdal.DontUseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
DERIVED_DIR = SLICE_A_DIR / "derived"

ALL_STATIONS = ["84", "85", "86", "87", "88", "89"]
DEM_PATH = str(Path(os.environ.get("MC26_DEM_PATH", str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif"))).resolve())
_stn_cand = SLICE_A_DIR / "stations.csv"
if not _stn_cand.exists():
    _stn_cand = DERIVED_DIR / "stations.csv"
if not _stn_cand.exists():
    _stn_cand = DATA_DIR / "stations.csv"
STATIONS_CSV_PATH = str(Path(os.environ.get("MC26_STATIONS_CSV", str(_stn_cand))).resolve())
OUT_DIR = str(Path(os.environ.get("MC26_VIEWSHEDS_DIR", str(DATA_DIR / "viewsheds"))).resolve())

DEFAULT_RMSE_M = 2.6
DEFAULT_CORR_LEN_M = 150.0


def read_geotiff(path):
    ds = gdal.Open(path)
    arr = ds.GetRasterBand(1).ReadAsArray()
    return arr, ds


def write_byte_geotiff(path, arr, ref_ds):
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


def load_station_coords():
    with open(STATIONS_CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    coords = {}
    for stn in ALL_STATIONS:
        r0 = [r for r in rows if r["station_num"] == stn][0]
        coords[stn] = (
            float(r0["station_x_epsg3979"]),
            float(r0["station_y_epsg3979"]),
        )
    return coords


# The error-field code (FFT amplitude, seeded field, rescale to the RMSE) lives in the generated
# script below, which runs inside GRASS; it was also kept here as unused copies until D97.


def run_probable_chunk_worker(worker_args):
    """
    Runs a chunk of Monte Carlo probable viewshed realizations for a single station
    inside one GRASS --tmp-project session and returns the accumulated visibility count array.
    """
    (
        stn,
        sx,
        sy,
        run_indices,
        rmse_m,
        corr_len_m,
        max_dist,
        tmp_root,
    ) = worker_args

    t0 = time.time()

    os.makedirs(tmp_root, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix=f"prob_{stn}_", dir=tmp_root)
    env = os.environ.copy()
    env["PATH"] = f"/usr/bin:{env.get('PATH', '')}"
    env["TMPDIR"] = work_dir
    env["GRASS_VERBOSE"] = "0"

    # Write a python runner to execute inside `grass --tmp-project` so we only start GRASS once
    inner_py = os.path.join(work_dir, "inner_runner.py")
    acc_npy = os.path.join(work_dir, "acc.npy")
    timings_json = os.path.join(work_dir, "timings.json")

    # Pre-generate perturbed DEMs or generate on the fly inside the inner script
    inner_code = f"""import json, os, subprocess, time
import numpy as np
from osgeo import gdal
gdal.DontUseExceptions()

dem_ds = gdal.Open({DEM_PATH!r})
dem_arr = dem_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
gt = dem_ds.GetGeoTransform()
proj = dem_ds.GetProjection()
dem_ds = None
rows, cols = dem_arr.shape
dx = abs(gt[1])

ky = np.minimum(np.arange(rows), rows - np.arange(rows)) * dx
kx = np.minimum(np.arange(cols), cols - np.arange(cols)) * dx
dist2 = ky[:, None] ** 2 + kx[None, :] ** 2
cov = np.exp(-dist2 / ({corr_len_m!r} ** 2))
amp = np.sqrt(np.maximum(np.fft.rfft2(cov).real, 0.0))

acc = np.zeros((rows, cols), dtype=np.uint16)
run_times = []
work_dir = {work_dir!r}
stn = {stn!r}
sx, sy = {sx!r}, {sy!r}
rmse_m = {rmse_m!r}
max_dist = {max_dist!r}
run_indices = {run_indices!r}

driver = gdal.GetDriverByName("GTiff")

for ridx in run_indices:
    t_r0 = time.time()
    seed = int(stn) * 1000 + int(ridx)
    rng = np.random.default_rng(seed)
    w = rng.standard_normal((rows, cols), dtype=np.float64)
    field = np.fft.irfft2(np.fft.rfft2(w) * amp, s=(rows, cols))
    field -= field.mean()
    field *= (rmse_m / field.std())
    pert_dem = dem_arr + field.astype(np.float32)

    dem_tif = os.path.join(work_dir, f"pert_{{ridx}}.tif")
    vs_tif = os.path.join(work_dir, f"vs_{{ridx}}.tif")
    ds_out = driver.Create(dem_tif, cols, rows, 1, gdal.GDT_Float32)
    ds_out.SetGeoTransform(gt)
    ds_out.SetProjection(proj)
    ds_out.GetRasterBand(1).WriteArray(pert_dem)
    ds_out.FlushCache()
    ds_out = None

    subprocess.run(["r.external", f"input={{dem_tif}}", f"output=dem_{{ridx}}", "--overwrite", "--quiet"], check=True)
    subprocess.run([
        "r.viewshed", "-c", "-r", "-b",
        f"input=dem_{{ridx}}",
        f"output=vs_{{ridx}}",
        f"coordinates={{sx:.4f}},{{sy:.4f}}",
        "observer_elevation=1.6",
        "target_elevation=0.0",
        f"max_distance={{max_dist}}",
        "refraction_coeff=0.13",
        "memory=300",
        "--overwrite", "--quiet"
    ], check=True)
    subprocess.run([
        "r.out.gdal", "-c",
        f"input=vs_{{ridx}}",
        f"output={{vs_tif}}",
        "type=Byte",
        "--overwrite", "--quiet"
    ], check=True)

    ds_vs = gdal.Open(vs_tif)
    vs_arr = ds_vs.GetRasterBand(1).ReadAsArray()
    ds_vs = None
    acc += (vs_arr == 1).astype(np.uint16)

    os.remove(dem_tif)
    os.remove(vs_tif)
    run_times.append(time.time() - t_r0)

np.save({acc_npy!r}, acc)
with open({timings_json!r}, "w") as f:
    json.dump(run_times, f)
"""
    with open(inner_py, "w", encoding="utf-8") as f:
        f.write(inner_code)

    grass_bin = shutil.which("grass") or "grass"
    py_bin = sys.executable or "python3"
    cmd = [grass_bin, "--tmp-project", DEM_PATH, "--exec", py_bin, inner_py]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(
            f"Probable viewshed worker failed for stn {stn} (rc={proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    acc = np.load(acc_npy)
    with open(timings_json, "r", encoding="utf-8") as f:
        run_times = json.load(f)
    shutil.rmtree(work_dir, ignore_errors=True)
    return {
        "station": stn,
        "acc": acc,
        "n_runs": len(run_indices),
        "run_times": run_times,
        "worker_wall_sec": time.time() - t0,
    }


def main():
    global OUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", nargs="+", default=ALL_STATIONS)
    parser.add_argument("--n-runs", type=int, default=50)
    parser.add_argument("--rmse", type=float, default=DEFAULT_RMSE_M)
    parser.add_argument("--corr-len", type=float, default=DEFAULT_CORR_LEN_M)
    parser.add_argument("--max-distance", type=int, default=30000)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    if args.out_dir:
        OUT_DIR = args.out_dir
    elif abs(args.rmse - 8.0) < 1e-4:
        OUT_DIR = os.environ.get("MC26_VIEWSHEDS_RMSE8_DIR", str(DATA_DIR / "viewsheds_rmse8"))

    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp_root = os.path.join(OUT_DIR, ".tmp_probable")
    os.makedirs(tmp_root, exist_ok=True)

    dem_arr, dem_ds = read_geotiff(DEM_PATH)
    coords = load_station_coords()
    selected_stations = [s for s in args.stations if s in coords]

    # Build worker tasks across (station, run_indices)
    total_runs = len(selected_stations) * args.n_runs
    target_workers = min(args.workers, total_runs)
    tasks = []
    for stn in selected_stations:
        sx, sy = coords[stn]
        # How many workers to allocate to this station
        stn_workers = max(1, round(target_workers / len(selected_stations)))
        stn_workers = min(stn_workers, args.n_runs)
        indices = list(range(args.n_runs))
        chunks = np.array_split(indices, stn_workers)
        for ch in chunks:
            if len(ch) > 0:
                tasks.append(
                    (
                        stn,
                        sx,
                        sy,
                        [int(x) for x in ch],
                        args.rmse,
                        args.corr_len,
                        args.max_distance,
                        tmp_root,
                    )
                )

    print(
        f"Running probable viewshed: stations={selected_stations}, n_runs={args.n_runs}/stn "
        f"(total={total_runs}), RMSE={args.rmse}m, corr_len={args.corr_len}m, "
        f"max_dist={args.max_distance}m across {len(tasks)} worker processes..."
    )

    acc_by_stn = {
        stn: np.zeros(dem_arr.shape, dtype=np.uint16) for stn in selected_stations
    }
    times_by_stn = {stn: [] for stn in selected_stations}

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run_probable_chunk_worker, t) for t in tasks]
        for fut in as_completed(futs):
            res = fut.result()
            stn = res["station"]
            acc_by_stn[stn] += res["acc"]
            times_by_stn[stn].extend(res["run_times"])

    shutil.rmtree(tmp_root, ignore_errors=True)
    wall_sec = time.time() - t_start

    # Load existing probable metrics if present
    prob_metrics_path = os.path.join(OUT_DIR, "probable_metrics.json")
    if os.path.exists(prob_metrics_path):
        try:
            with open(prob_metrics_path, "r", encoding="utf-8") as f:
                prob_metrics = json.load(f)
        except Exception:
            prob_metrics = {}
    else:
        prob_metrics = {}

    stn_prob_stats = prob_metrics.get("stations", {})
    CELL_AREA_KM2 = (30.0 * 30.0) / 1e6

    for stn in selected_stations:
        cnt = acc_by_stn[stn]
        prob_pct = np.rint(cnt.astype(np.float64) * (100.0 / args.n_runs)).astype(
            np.uint8
        )
        out_tif = os.path.join(OUT_DIR, f"prob_{stn}.tif")
        write_byte_geotiff(out_tif, prob_pct, dem_ds)

        c_any = int(np.sum(prob_pct > 0))
        c_ge50 = int(np.sum(prob_pct >= 50))
        c_ge90 = int(np.sum(prob_pct >= 90))
        c_100 = int(np.sum(prob_pct == 100))
        expected_cells = float(np.sum(cnt.astype(np.float64) / args.n_runs))

        stn_prob_stats[stn] = {
            "station": stn,
            "file": f"prob_{stn}.tif",
            "n_runs": args.n_runs,
            "rmse_m": args.rmse,
            "corr_len_m": args.corr_len,
            "max_distance_m": args.max_distance,
            "expected_visible_cells": round(expected_cells, 1),
            "expected_visible_area_km2": round(expected_cells * CELL_AREA_KM2, 4),
            "cells_prob_gt_0": c_any,
            "area_prob_gt_0_km2": round(c_any * CELL_AREA_KM2, 4),
            "cells_prob_ge_50": c_ge50,
            "area_prob_ge_50_km2": round(c_ge50 * CELL_AREA_KM2, 4),
            "cells_prob_ge_90": c_ge90,
            "area_prob_ge_90_km2": round(c_ge90 * CELL_AREA_KM2, 4),
            "cells_prob_eq_100": c_100,
            "area_prob_eq_100_km2": round(c_100 * CELL_AREA_KM2, 4),
            "mean_single_run_cpu_sec": round(float(np.mean(times_by_stn[stn])), 3),
        }

    prob_metrics.update(
        {
            "rmse_m": args.rmse,
            "rmse_source_quote": "Vertical accuracy (on bare-earth surface): ~1.6 m when the source is HRDEM and ~2.6 m when the source is GLO-30.",
            "rmse_source_url": "https://geo.ca/initiatives/national-elevation-data-strategy/",
            "rmse_dataset_url": "https://open.canada.ca/data/en/dataset/18752265-bda3-498c-a4ba-9dfe68cb98da",
            "corr_len_m": args.corr_len,
            "covariance_model": "Gaussian C(r) = sigma^2 * exp(-(r/L)^2) via 2D FFT, L = 150 m",
            "max_distance_m": args.max_distance,
            "stations": stn_prob_stats,
            "last_run_n_runs": args.n_runs,
            "last_run_wall_sec": round(wall_sec, 3),
        }
    )

    with open(prob_metrics_path, "w", encoding="utf-8") as f:
        json.dump(prob_metrics, f, indent=2)

    print(
        f"Probable viewsheds completed in {wall_sec:.2f}s wall time. Saved to {prob_metrics_path}."
    )


if __name__ == "__main__":
    main()
