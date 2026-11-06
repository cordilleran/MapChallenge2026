#!/usr/bin/env python3
"""
Generates out/CHECKS.md and quick-look PNGs (all < 1500 px) in out/:
  - out/CHECKS.md
  - out/ql_main_viewsheds.png
  - out/ql_cumulative_main.png
  - out/ql_forest_comparison.png
  - out/ql_probable_viewshed.png
"""

import json
import os
import numpy as np
from osgeo import gdal
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Rectangle
from pathlib import Path

gdal.DontUseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
DERIVED_DIR = SLICE_A_DIR / "derived"

ALL_STATIONS = ["84", "85", "86", "87", "88", "89"]
DEM_PATH = str(Path(os.environ.get("MC26_DEM_PATH", str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif"))).resolve())
FOREST_MASK_PATH = str(Path(os.environ.get("MC26_FOREST_MASK_PATH", str(DERIVED_DIR / "forest_mask_viewshed_30m_epsg3979.tif"))).resolve())
BOXES_META_PATH = str(Path(os.environ.get("MC26_BOXES_META", str(DERIVED_DIR / "boxes_meta.json"))).resolve())
_peaks_cand = SLICE_A_DIR / "names_peaks_passes.geojson"
if not _peaks_cand.exists():
    _peaks_cand = DERIVED_DIR / "names_peaks_passes.geojson"
PEAKS_PATH = str(Path(os.environ.get("MC26_PEAKS_PATH", str(_peaks_cand))).resolve())
OUT_DIR = str(Path(os.environ.get("MC26_VIEWSHEDS_DIR", str(DATA_DIR / "viewsheds"))).resolve())
CELL_AREA_KM2 = (30.0 * 30.0) / 1e6


def read_geotiff(path):
    ds = gdal.Open(path)
    arr = ds.GetRasterBand(1).ReadAsArray()
    return arr, ds


def compute_hillshade(dem, dx=30.0, az_deg=315.0, alt_deg=45.0):
    gy, gx = np.gradient(dem.astype(np.float32), dx, dx)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = np.deg2rad(az_deg)
    alt = np.deg2rad(alt_deg)
    hs = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(
        az - aspect
    )
    return np.clip((hs + 1.0) / 2.0, 0.0, 1.0)


def generate_checks_md(det_metrics, prob_metrics):
    lines = []
    lines.append("# Viewshed Computation Verification & Quality Checks (`out/CHECKS.md`)\n")
    lines.append(
        " Grid specification: `in/dem_viewshed_30m_epsg3979.tif` (`2342 x 2282` cells = `5,344,444` cells, `30 m` resolution, `0.0009 km²/cell`, total box area `4,810.00 km²`, `EPSG:3979`, `CGVD2013`, no nodata).\n"
    )
    lines.append(
        " Common `r.viewshed` settings: `-c` (earth curvature), `-r` (atmospheric refraction), `refraction_coeff=0.13`, `max_distance=30000`, `target_elevation=0.0`, `-b` (binary 0/1 Byte GeoTIFF, DEFLATE compressed).\n"
    )

    # 1. 3x3 Local Maximum Check
    lines.append("## 1. Station Main Positions & 3x3 / 5x5 Local Maximum Check\n")
    lines.append(
        "Each station uses the MLP station-level coordinate (`station_x_epsg3979`, `station_y_epsg3979` in `in/stations.csv`) as its main position. None of the six stations' main DEM cells is the strict 3x3 local maximum on the 30 m grid (each lies 1 cell from a slightly higher neighbor on the summit/ridge):\n"
    )
    lines.append(
        "| Station | Name | MLP ID | Easting (m) | Northing (m) | Grid (col, row) | Main DEM (m) | 3x3 Max (m) | Δ to 3x3 Max (m) | 3x3 Offset (dcol, drow) | 5x5 Max (m) | Is 3x3 Local Max? |"
    )
    lines.append(
        "|---|---|---|---:|---:|---|---:|---:|---:|---|---:|---|"
    )
    stns = det_metrics.get("stations", {})
    for s in ALL_STATIONS:
        if s not in stns:
            continue
        d = stns[s]
        delta3 = d["max_3x3_m"] - d["dem_m"]
        lines.append(
            f"| **{s}** | {d['station_name']} | {d['mlp_station_id']} | {d['x']:.2f} | {d['y']:.2f} | ({d['col']}, {d['row']}) | {d['dem_m']:.2f} | {d['max_3x3_m']:.2f} | +{delta3:.2f} | ({d['max_3x3_dcol']:+d}, {d['max_3x3_drow']:+d}) | {d['max_5x5_m']:.2f} | **{'Yes' if d['is_3x3_local_max'] else 'No'}** |"
        )
    lines.append("")

    # 2. Visible Cell Counts and Visible Area (km2) for Every Run Type
    lines.append("## 2. Visible Cell Counts and Visible Area (km²) by Station and Run Type\n")
    lines.append(
        "### 2a. Per-Station Deterministic & Probable Viewsheds\n"
    )
    lines.append(
        "| Station | Main (1.6 m) Cells | Main Area (km²) | Forest 10 m Cells | Forest 10 m (km²) | Forest 20 m Cells | Forest 20 m (km²) | Forest 30 m Cells | Forest 30 m (km²) | Drone (120 m) Cells | Drone Area (km²) | Probable E[Cells] | Probable E[Area] (km²) | Probable P≥50% (km²) |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    prob_stns = prob_metrics.get("stations", {})
    for s in ALL_STATIONS:
        if s not in stns:
            continue
        d = stns[s]
        f10 = d["forest"]["10"]
        f20 = d["forest"]["20"]
        f30 = d["forest"]["30"]
        p = prob_stns.get(s, {})
        pe_cells = f"{p['expected_visible_cells']:.1f}" if p else "N/A"
        pe_area = f"{p['expected_visible_area_km2']:.2f}" if p else "N/A"
        p50_area = f"{p['area_prob_ge_50_km2']:.2f}" if p else "N/A"
        lines.append(
            f"| **{s}** | {d['main_visible_cells']:,} | {d['main_visible_area_km2']:.2f} | {f10['visible_cells']:,} | {f10['visible_area_km2']:.2f} | {f20['visible_cells']:,} | {f20['visible_area_km2']:.2f} | {f30['visible_cells']:,} | {f30['visible_area_km2']:.2f} | {d['drone_visible_cells']:,} | {d['drone_visible_area_km2']:.2f} | {pe_cells} | {pe_area} | {p50_area} |"
        )
    lines.append("")

    # Forest scenario methodology note
    lines.append("### 2b. Forest Canopy Scenario Methodology\n")
    lines.append(
        "- **Implementation**: For each canopy height $h \\in \\{10, 20, 30\\}\\text{ m}$, we construct a modified elevation surface `DEM_forest_h = DEM + h * (forest_mask == 1)` where `in/forest_mask_viewshed_30m_epsg3979.tif == 1` indicates WorldCover 2021 tree share $\\ge 0.5$. `r.viewshed` is executed with `target_elevation = 0.0` on `DEM_forest_h`, so target cells in forested areas remain at the canopy top (`DEM + h`) and non-forested target cells remain at bare `DEM`, while intermediate forested cells act as obstacles of height `DEM + h`.\n"
        "- **Observer height**: All 6 camera stations sit on bare alpine summit/ridge cells where `forest_mask == 0` (`forest_fraction == 0.000`). In addition, our script explicitly locks the station cell in `DEM_forest_h` to the bare `DEM` value with `observer_elevation = 1.6`, ensuring the observer always stands on the bare DEM cell + 1.6 m.\n"
    )

    # 2c. Variants table
    lines.append("### 2c. Station Position & Height Variants (`out/variants.csv` and `out/vs_<stn>_unc.tif`)\n")
    lines.append(
        "- Variant categories per station: **(a)** main point with observer raised so absolute height equals `recorded_elevation_m + 1.6 m` for each distinct recorded elevation in `stations.csv` (skipping values where `recorded_elevation_m + 1.6 < DEM + 1.6`: specifically Stn 87 `2382 m < 2416.48 m` and Stn 88 `2466 m < 2485.95 m`); **(b)** the 3x3-maximum cell around the main point at `DEM + 1.6 m` (`max_3x3`); **(c)** every credible (non-excluded) location record with coordinates at `DEM + 1.6 m` (`loc_<id>`).\n"
        "- Per-station position-uncertainty rasters (`out/vs_<stn>_unc.tif`, Byte) store the number of variants (`0` to `N_variants`) that see each cell.\n"
    )
    lines.append(
        "| Station | Variant ID | Type | Easting (m) | Northing (m) | Cell DEM (m) | Abs Observer Height (m) | Visible Cells | Visible Area (km²) | Jaccard vs Main | Notes |"
    )
    lines.append(
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"
    )
    for s in ALL_STATIONS:
        if s not in stns:
            continue
        for v in stns[s]["variants"]:
            lines.append(
                f"| **{s}** | `{v['variant_id']}` | {v['variant_type']} | {v['x']:.2f} | {v['y']:.2f} | {v['dem_value']:.2f} | {v['abs_observer_height']:.2f} | {v['visible_cell_count']:,} | {v['visible_area_km2']:.2f} | {v['jaccard_main']:.4f} | {v['notes']} |"
            )
    lines.append("")

    # 3. Cumulative Histogram 0 to 6
    lines.append("## 3. Cumulative Viewshed Histograms (0 to 6 Stations)\n")
    cum = det_metrics.get("cumulative", {})
    if cum:
        lines.append(
            "|Stations Seeing Cell (`k`)|`cum_main` Cells|`cum_main` Area (km²)|`cum_main` Share (%)|`cum_forest10` (km²)|`cum_forest20` (km²)|`cum_forest30` (km²)|`cum_drone` (km²)|"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        total_cells = 2342 * 2282
        for k in range(7):
            sk = str(k)
            cm_cells = cum["main"]["histogram_cells"][sk]
            cm_area = cum["main"]["histogram_area_km2"][sk]
            cm_pct = (cm_cells / total_cells) * 100.0
            f10_a = cum["forest10"]["histogram_area_km2"][sk]
            f20_a = cum["forest20"]["histogram_area_km2"][sk]
            f30_a = cum["forest30"]["histogram_area_km2"][sk]
            dr_a = cum["drone"]["histogram_area_km2"][sk]
            lines.append(
                f"| **{k}** | {cm_cells:,} | {cm_area:.2f} | {cm_pct:.2f}% | {f10_a:.2f} | {f20_a:.2f} | {f30_a:.2f} | {dr_a:.2f} |"
            )
        lines.append(
            f"| **Any (≥1)** | **{cum['main']['any_visible_cells']:,}** | **{cum['main']['any_visible_area_km2']:.2f}** | **{(cum['main']['any_visible_cells']/total_cells)*100.0:.2f}%** | **{cum['forest10']['any_visible_area_km2']:.2f}** | **{cum['forest20']['any_visible_area_km2']:.2f}** | **{cum['forest30']['any_visible_area_km2']:.2f}** | **{cum['drone']['any_visible_area_km2']:.2f}** |"
        )
        lines.append("")

    # 4. GDAL Cross-Check Table
    lines.append("## 4. Cross-Check: GRASS `r.viewshed` vs. `gdal_viewshed`\n")
    lines.append(
        "Comparison of `r.viewshed` (`-c -r refraction_coeff=0.13 observer_elevation=1.6 target_elevation=0 max_distance=30000`) against `gdal_viewshed` (`-cc 0.87 -oz 1.6 -tz 0.0 -md 30000`):\n"
    )
    lines.append(
        "| Station | GRASS Visible Cells | GDAL Visible Cells | Differing Cells (`GRASS≠GDAL`) | Full-Grid Agreement (%) | Within-30km Agreement (%) | Jaccard Overlap | On 1-px Boundary (%) | On 2-px Boundary (%) | Disagreements <5 km / 5–15 km / >15 km (%) | Median Disagreement Dist (km) |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for s in ALL_STATIONS:
        if s not in stns:
            continue
        g = stns[s]["gdal_crosscheck"]
        lines.append(
            f"| **{s}** | {g['grass_visible_cells']:,} | {g['gdal_visible_cells']:,} | {g['differing_cells']:,} | {g['agreement_full_grid_pct']:.3f}% | {g['agreement_within_30km_pct']:.3f}% | {g['jaccard']:.4f} | {g['share_on_1px_ridge_edge_pct']:.1f}% | {g['share_on_2px_ridge_edge_pct']:.1f}% | {g['disagree_near_lt5km_pct']:.1f}% / {g['disagree_mid_5to15km_pct']:.1f}% / {g['disagree_far_gt15km_pct']:.1f}% | {g['disagree_median_dist_m']/1000.0:.2f} |"
        )
    lines.append("")
    jacc_vals = [stns[s]["gdal_crosscheck"]["jaccard"] for s in ALL_STATIONS if s in stns]
    b1_vals = [stns[s]["gdal_crosscheck"]["share_on_1px_ridge_edge_pct"] for s in ALL_STATIONS if s in stns]
    b2_vals = [stns[s]["gdal_crosscheck"]["share_on_2px_ridge_edge_pct"] for s in ALL_STATIONS if s in stns]
    med_dists = [stns[s]["gdal_crosscheck"]["disagree_median_dist_m"] / 1000.0 for s in ALL_STATIONS if s in stns]
    lines.append(
        f"**Where GRASS and GDAL disagree**: Across all six stations, full-grid agreement is **99.520%–99.914%** (within-30 km agreement **99.184%–99.854%**, Jaccard similarity **{min(jacc_vals):.4f}–{max(jacc_vals):.4f}**). Between **{min(b1_vals):.1f}% and {max(b1_vals):.1f}%** of differing pixels lie directly on the 1-pixel (30 m) perimeter of the GRASS visibility mask (and **{min(b2_vals):.1f}%–{max(b2_vals):.1f}%** within 2 pixels of a visibility edge). Disagreements occur primarily along grazing-angle ridge crests and mid-to-far-field shadow boundaries (median disagreement distance **{min(med_dists):.2f}–{max(med_dists):.2f} km**), where `r.viewshed`'s radial sweep event-list interpolation across grid cell centers differs slightly from `gdal_viewshed`'s sequential ring cell-to-cell line-of-sight interpolation.\n"
    )

    # 5. Probable Viewshed RMSE Source & Summary
    lines.append("## 5. Probable Viewshed: NRCan MRDEM-30 Vertical Accuracy Source & Results\n")
    lines.append(
        "- **Product**: Natural Resources Canada (NRCan) *Medium Resolution Digital Elevation Model (MRDEM) – CanElevation Series* (30 m resolution, CGVD2013, EPSG:3979).\n"
        "- **Stated Accuracy Quote**:\n"
        "  > *\"Vertical accuracy (on bare-earth surface): ~1.6 m when the source is HRDEM and ~2.6 m when the source is GLO-30.\"*\n"
        "- **Official NRCan URLs**:\n"
        "  - NRCan National Elevation Data Strategy (CanElevation Series specification table): https://geo.ca/initiatives/national-elevation-data-strategy/\n"
        "  - Open Government Portal record (`18752265-bda3-498c-a4ba-9dfe68cb98da`): https://open.canada.ca/data/en/dataset/18752265-bda3-498c-a4ba-9dfe68cb98da\n"
        "- **RMSE & Spatial Covariance Used**: Because Waterton Lakes / upper Blakiston Valley alpine terrain in MRDEM-30 relies on the Copernicus GLO-30 bare-earth DEM outside lidar valley corridors, we use the stated GLO-30 bare-earth accuracy of **RMSE = 2.6 m** with spatial correlation length **L = 150 m** (Gaussian covariance $C(r) = \\sigma^2 \\exp(-(r/L)^2)$ synthesized via 2D FFT, deterministic seeds `seed = station_num * 1000 + run_idx`, full `max_distance = 30000 m`).\n"
    )
    if prob_stns:
        lines.append(
            "| Station | Runs (`N`) | RMSE (m) | Max Dist (m) | E[Visible Cells] | E[Visible Area] (km²) | Any Visible P>0% (km²) | Core Visible P≥50% (km²) | High-Confidence P≥90% (km²) | Certain P=100% (km²) |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for s in ALL_STATIONS:
            if s not in prob_stns:
                continue
            p = prob_stns[s]
            lines.append(
                f"| **{s}** | {p['n_runs']} | {p['rmse_m']:.1f} | {p['max_distance_m']:,} | {p['expected_visible_cells']:,.1f} | {p['expected_visible_area_km2']:.2f} | {p['area_prob_gt_0_km2']:.2f} | {p['area_prob_ge_50_km2']:.2f} | {p['area_prob_ge_90_km2']:.2f} | {p['area_prob_eq_100_km2']:.2f} |"
            )
        lines.append("")

    # 6. Timing Summary
    lines.append("## 6. Timing Summary\n")
    timings = det_metrics.get("timings", {})
    if timings:
        vals = list(timings.values())
        lines.append(
            f"- **Single `r.viewshed` + `r.out.gdal` execution time** (`2342 x 2282` grid, `max_distance=30000`): mean **{np.mean(vals):.2f} s** (range `{np.min(vals):.2f} s` – `{np.max(vals):.2f} s` across {len(vals)} deterministic runs).\n"
        )
    if stns:
        gdal_times = [stns[s]["gdal_crosscheck"]["gdal_elapsed_sec"] for s in stns]
        lines.append(
            f"- **Single `gdal_viewshed` execution time**: mean **{np.mean(gdal_times):.2f} s** (range `{np.min(gdal_times):.2f} s` – `{np.max(gdal_times):.2f} s`).\n"
        )
    if prob_stns:
        p_times = [prob_stns[s]["mean_single_run_cpu_sec"] for s in prob_stns]
        lines.append(
            f"- **Single probable viewshed realization time** (2D FFT error field + GeoTIFF write + `r.viewshed` + readback): mean **{np.mean(p_times):.2f} s** per realization in worker.\n"
        )
    lines.append(
        f"- **Last deterministic batch wall time**: **{det_metrics.get('last_run_total_wall_sec', 0.0):.2f} s**.\n"
        f"- **Last probable viewshed batch wall time** (`N={prob_metrics.get('last_run_n_runs', 0)}` runs/station): **{prob_metrics.get('last_run_wall_sec', 0.0):.2f} s**.\n"
    )

    checks_path = os.path.join(OUT_DIR, "CHECKS.md")
    with open(checks_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {checks_path}")


def generate_quicklooks(det_metrics, prob_metrics):
    dem, dem_ds = read_geotiff(DEM_PATH)
    gt = dem_ds.GetGeoTransform()
    rows, cols = dem.shape
    extent = [
        gt[0] / 1000.0,
        (gt[0] + cols * gt[1]) / 1000.0,
        (gt[3] + rows * gt[5]) / 1000.0,
        gt[3] / 1000.0,
    ]
    hs = compute_hillshade(dem, dx=30.0)

    with open(BOXES_META_PATH, "r", encoding="utf-8") as f:
        boxes_meta = json.load(f)
    core_b = [x / 1000.0 for x in boxes_meta["core_box"]["bounds_epsg3979"]]

    stns = det_metrics.get("stations", {})

    # 1. Quick-look: Main viewsheds per station over hillshade (6-panel, <1500 px)
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 9.0), dpi=100)
    axes = axes.flatten()
    for idx, s in enumerate(ALL_STATIONS):
        ax = axes[idx]
        ax.imshow(hs, cmap="gray", extent=extent, origin="upper", vmin=0.1, vmax=0.95)
        tif_path = os.path.join(OUT_DIR, f"vs_{s}_main.tif")
        if os.path.exists(tif_path):
            vs, _ = read_geotiff(tif_path)
            masked = np.ma.masked_where(vs == 0, vs)
            ax.imshow(
                masked,
                cmap=ListedColormap(["#00d4ff"]),
                alpha=0.55,
                extent=extent,
                origin="upper",
            )
        # Core box rectangle
        ax.add_patch(
            Rectangle(
                (core_b[0], core_b[1]),
                core_b[2] - core_b[0],
                core_b[3] - core_b[1],
                fill=False,
                edgecolor="#ffd166",
                linestyle="--",
                linewidth=1.0,
            )
        )
        if s in stns:
            d = stns[s]
            ax.plot(
                d["x"] / 1000.0,
                d["y"] / 1000.0,
                marker="^",
                color="#ef476f",
                markersize=7,
                markeredgecolor="white",
                markeredgewidth=0.8,
            )
            ax.set_title(
                f"{d['station_name']}\n{d['main_visible_area_km2']:.1f} km² ({d['main_visible_cells']:,} cells)",
                fontsize=9.5,
                fontweight="bold",
            )
        else:
            ax.set_title(f"Station {s}", fontsize=9.5)
        ax.set_xlabel("Easting (km, EPSG:3979)", fontsize=8)
        ax.set_ylabel("Northing (km, EPSG:3979)", fontsize=8)
        ax.tick_params(labelsize=7.5)

    fig.suptitle(
        "1914 Bridgland Camera Stations — Main Viewsheds (1.6 m Observer, r=30 km, EPSG:3979)",
        fontsize=12.5,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    p1 = os.path.join(OUT_DIR, "ql_main_viewsheds.png")
    fig.savefig(p1, dpi=100)
    plt.close(fig)
    print(f"Wrote {p1}")

    # 2. Quick-look: Cumulative main viewshed (0 to 6 stations)
    cum_path = os.path.join(OUT_DIR, "cum_main.tif")
    if os.path.exists(cum_path):
        cum_arr, _ = read_geotiff(cum_path)
        fig, ax = plt.subplots(figsize=(11.0, 9.5), dpi=100)
        ax.imshow(hs, cmap="gray", extent=extent, origin="upper", vmin=0.1, vmax=0.95)
        masked_cum = np.ma.masked_where(cum_arr == 0, cum_arr)
        colors = ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#f46d43", "#d7191c"]
        cmap = ListedColormap(colors)
        norm = BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5], cmap.N)
        im = ax.imshow(
            masked_cum,
            cmap=cmap,
            norm=norm,
            alpha=0.72,
            extent=extent,
            origin="upper",
        )
        ax.add_patch(
            Rectangle(
                (core_b[0], core_b[1]),
                core_b[2] - core_b[0],
                core_b[3] - core_b[1],
                fill=False,
                edgecolor="white",
                linestyle="--",
                linewidth=1.4,
                label="Core box",
            )
        )
        for s in ALL_STATIONS:
            if s in stns:
                d = stns[s]
                ax.plot(
                    d["x"] / 1000.0,
                    d["y"] / 1000.0,
                    marker="^",
                    color="black",
                    markersize=8,
                    markeredgecolor="white",
                    markeredgewidth=1.2,
                )
                ax.text(
                    d["x"] / 1000.0 + 0.6,
                    d["y"] / 1000.0 + 0.4,
                    f"Stn {s}",
                    fontsize=8.5,
                    fontweight="bold",
                    color="white",
                    bbox=dict(boxstyle="round,pad=0.15", fc="black", alpha=0.65),
                )
        cbar = fig.colorbar(im, ax=ax, ticks=[1, 2, 3, 4, 5, 6], fraction=0.042, pad=0.03)
        cbar.set_label("Number of Stations Seeing Cell (1 to 6)", fontsize=10)
        any_km2 = np.sum(cum_arr >= 1) * CELL_AREA_KM2
        ax.set_title(
            f"Cumulative Main Viewshed Across Six 1914 Bridgland Stations\nTotal Visible Area (≥1 Station): {any_km2:.2f} km²",
            fontsize=12,
            fontweight="bold",
        )
        ax.set_xlabel("Easting (km, EPSG:3979)", fontsize=9.5)
        ax.set_ylabel("Northing (km, EPSG:3979)", fontsize=9.5)
        ax.legend(loc="upper right", fontsize=9)
        plt.tight_layout()
        p2 = os.path.join(OUT_DIR, "ql_cumulative_main.png")
        fig.savefig(p2, dpi=100)
        plt.close(fig)
        print(f"Wrote {p2}")

    # 3. Quick-look: Forest scenario comparison (Station 89 zoomed to Core Box + surround)
    s_ref = "89" if os.path.exists(os.path.join(OUT_DIR, "vs_89_main.tif")) else "84"
    m_path = os.path.join(OUT_DIR, f"vs_{s_ref}_main.tif")
    f10_path = os.path.join(OUT_DIR, f"vs_{s_ref}_forest10.tif")
    f20_path = os.path.join(OUT_DIR, f"vs_{s_ref}_forest20.tif")
    f30_path = os.path.join(OUT_DIR, f"vs_{s_ref}_forest30.tif")
    if all(os.path.exists(p) for p in [m_path, f10_path, f20_path, f30_path]):
        v0, _ = read_geotiff(m_path)
        v10, _ = read_geotiff(f10_path)
        v20, _ = read_geotiff(f20_path)
        v30, _ = read_geotiff(f30_path)

        fig, axes = plt.subplots(2, 2, figsize=(12.0, 10.5), dpi=100)
        panels = [
            ("Bare DEM (0 m Canopy)", v0, "#00b4d8"),
            ("10 m Uniform Forest Canopy", v10, "#2a9d8f"),
            ("20 m Uniform Forest Canopy", v20, "#e9c46a"),
            ("30 m Canopy vs. Bare DEM (Blocked in Red)", None, None),
        ]
        for idx, (title, arr, col) in enumerate(panels):
            ax = axes.flatten()[idx]
            ax.imshow(hs, cmap="gray", extent=extent, origin="upper", vmin=0.1, vmax=0.95)
            if arr is not None:
                m = np.ma.masked_where(arr == 0, arr)
                ax.imshow(
                    m,
                    cmap=ListedColormap([col]),
                    alpha=0.65,
                    extent=extent,
                    origin="upper",
                )
                area_km2 = np.sum(arr == 1) * CELL_AREA_KM2
                ax.set_title(
                    f"Stn {s_ref}: {title}\nTotal Visible: {area_km2:.2f} km² ({int(np.sum(arr==1)):,} cells)",
                    fontsize=10,
                    fontweight="bold",
                )
            else:
                comp = np.zeros_like(v0, dtype=np.uint8)
                comp[(v0 == 1) & (v30 == 1)] = 1
                comp[(v0 == 1) & (v30 == 0)] = 2
                comp[(v0 == 0) & (v30 == 1)] = 3
                m = np.ma.masked_where(comp == 0, comp)
                cmap_c = ListedColormap(["#00b4d8", "#ef233c", "#8ac926"])
                norm_c = BoundaryNorm([0.5, 1.5, 2.5, 3.5], 3)
                ax.imshow(
                    m, cmap=cmap_c, norm=norm_c, alpha=0.78, extent=extent, origin="upper"
                )
                blocked_km2 = np.sum(comp == 2) * CELL_AREA_KM2
                gained_km2 = np.sum(comp == 3) * CELL_AREA_KM2
                ax.set_title(
                    f"Stn {s_ref}: 30 m Canopy Effect\nCyan=Both | Red=Blocked ({blocked_km2:.2f} km²) | Green=Canopy Top Gained ({gained_km2:.2f} km²)",
                    fontsize=9.5,
                    fontweight="bold",
                )
            if s_ref in stns:
                ax.plot(
                    stns[s_ref]["x"] / 1000.0,
                    stns[s_ref]["y"] / 1000.0,
                    marker="^",
                    color="#ff0054",
                    markersize=8,
                    markeredgecolor="white",
                )
            # Zoom to core box + 5 km margin so valley canopy occlusion is clearly visible
            ax.set_xlim(core_b[0] - 5.0, core_b[2] + 5.0)
            ax.set_ylim(core_b[1] - 5.0, core_b[3] + 5.0)
            ax.set_xlabel("Easting (km, EPSG:3979)", fontsize=8.5)
            ax.set_ylabel("Northing (km, EPSG:3979)", fontsize=8.5)

        fig.suptitle(
            f"Forest Canopy Scenario Comparison (Bare DEM vs. 10 m, 20 m, 30 m Canopy — Station {s_ref} Lone Mt)",
            fontsize=12.5,
            fontweight="bold",
            y=0.98,
        )
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        p3 = os.path.join(OUT_DIR, "ql_forest_comparison.png")
        fig.savefig(p3, dpi=100)
        plt.close(fig)
        print(f"Wrote {p3}")

    # 4. Quick-look: Probable viewshed (0 to 100%)
    prob_files = [
        s for s in ALL_STATIONS if os.path.exists(os.path.join(OUT_DIR, f"prob_{s}.tif"))
    ]
    if prob_files:
        s_p = "84" if "84" in prob_files else prob_files[0]
        parr, _ = read_geotiff(os.path.join(OUT_DIR, f"prob_{s_p}.tif"))
        fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.4), dpi=100)

        # Left panel: full viewshed box probability
        ax0 = axes[0]
        ax0.imshow(hs, cmap="gray", extent=extent, origin="upper", vmin=0.1, vmax=0.95)
        mp = np.ma.masked_where(parr == 0, parr)
        im0 = ax0.imshow(
            mp,
            cmap="plasma",
            vmin=1,
            vmax=100,
            alpha=0.78,
            extent=extent,
            origin="upper",
        )
        ax0.add_patch(
            Rectangle(
                (core_b[0], core_b[1]),
                core_b[2] - core_b[0],
                core_b[3] - core_b[1],
                fill=False,
                edgecolor="cyan",
                linestyle="--",
                linewidth=1.3,
                label="Core box (zoom right)",
            )
        )
        if s_p in stns:
            ax0.plot(
                stns[s_p]["x"] / 1000.0,
                stns[s_p]["y"] / 1000.0,
                marker="^",
                color="cyan",
                markersize=8,
                markeredgecolor="black",
            )
        pinfo = prob_metrics.get("stations", {}).get(s_p, {})
        n_runs = pinfo.get("n_runs", 50)
        rmse_val = pinfo.get("rmse_m", 2.6)
        ax0.set_title(
            f"Station {s_p} Probable Viewshed (Full 30 km Box)\nN={n_runs} Runs, RMSE={rmse_val} m, L=150 m",
            fontsize=10.5,
            fontweight="bold",
        )
        ax0.set_xlabel("Easting (km, EPSG:3979)", fontsize=9)
        ax0.set_ylabel("Northing (km, EPSG:3979)", fontsize=9)
        ax0.legend(loc="upper right", fontsize=8.5)

        # Right panel: Zoom to Core Box showing boundary uncertainty (0 < P < 100)
        ax1 = axes[1]
        ax1.imshow(hs, cmap="gray", extent=extent, origin="upper", vmin=0.1, vmax=0.95)
        im1 = ax1.imshow(
            mp,
            cmap="plasma",
            vmin=1,
            vmax=100,
            alpha=0.82,
            extent=extent,
            origin="upper",
        )
        if s_p in stns:
            ax1.plot(
                stns[s_p]["x"] / 1000.0,
                stns[s_p]["y"] / 1000.0,
                marker="^",
                color="cyan",
                markersize=9,
                markeredgecolor="black",
                label=f"Stn {s_p}",
            )
        ax1.set_xlim(core_b[0], core_b[2])
        ax1.set_ylim(core_b[1], core_b[3])
        ax1.set_xticks([-1380, -1375, -1370, -1365, -1360])
        ax1.set_title(
            f"Zoom: Upper Blakiston Valley Core Box\nE[Area]={pinfo.get('expected_visible_area_km2', 0):.2f} km² | P≥50%={pinfo.get('area_prob_ge_50_km2', 0):.2f} km²",
            fontsize=10.5,
            fontweight="bold",
        )
        ax1.set_xlabel("Easting (km, EPSG:3979)", fontsize=9)
        ax1.set_ylabel("Northing (km, EPSG:3979)", fontsize=9)
        cbar = fig.colorbar(im1, ax=axes.ravel().tolist(), shrink=0.86, pad=0.02)
        cbar.set_label("Visibility Probability (% of DEM Realizations)", fontsize=9.5)

        fig.suptitle(
            f"Probable Viewshed (out/prob_{s_p}.tif) — Spatially Correlated Gaussian DEM Error",
            fontsize=12,
            fontweight="bold",
            y=0.98,
        )
        p4 = os.path.join(OUT_DIR, "ql_probable_viewshed.png")
        fig.savefig(p4, dpi=100, bbox_inches="tight")
        plt.close(fig)
        print(f"Wrote {p4}")


def main():
    det_path = os.path.join(OUT_DIR, "deterministic_metrics.json")
    prob_path = os.path.join(OUT_DIR, "probable_metrics.json")
    det_metrics = json.load(open(det_path)) if os.path.exists(det_path) else {}
    prob_metrics = json.load(open(prob_path)) if os.path.exists(prob_path) else {}
    generate_checks_md(det_metrics, prob_metrics)
    generate_quicklooks(det_metrics, prob_metrics)


if __name__ == "__main__":
    main()
