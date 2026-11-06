#!/usr/bin/env python3
"""
Task 8: Quick looks — one PNG per layer, small (under 1500 px):
1. ql_01_dem_viewshed_hillshade_stations.png: Hillshade of viewshed-box DEM clip with primary stations & core box outline
2. ql_02_dem_core_hillshade_stations.png: Hillshade of core-box DEM clip with primary stations
3. ql_03_s2_tci_core.png: Sentinel-2 L2A (2025-08-25) TCI (true colour) mosaic for the core box + B04/B08 false-colour inset
4. ql_04_forest_mask_viewshed.png: ESA WorldCover 2021 v200 forest mask (fraction >= 0.5) & fraction over hillshade (viewshed & core)
5. ql_05_names_over_hillshade.png: Named peaks and passes (CGNDB + GNIS) over hillshade (viewshed + core closeup)
6. ql_06_vectors_overview.png: Vectors (Waterton Lakes NP boundary, 2017 Kenow fire perimeter, Red Rock Parkway, trails in core box)

Environment:
  MC26_DAY05_DIR    input data root directory (defaults to <repo_root>/../in if unset)
  MC26_SLICE_A_DIR  slice_a data directory (defaults to $MC26_DAY05_DIR/slice_a)
"""
import csv
import json
import os
from pathlib import Path
import subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import Patch, Rectangle
from matplotlib.lines import Line2D
from osgeo import gdal, osr
from PIL import Image

gdal.UseExceptions()
osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
DERIVED_DIR = SLICE_A_DIR / "derived"
QL_DIR = SLICE_A_DIR / "quicklooks"

VS_BOUNDS = (-1405890.0, 187590.0, -1335630.0, 256050.0)
CORE_BOUNDS = (-1381680.0, 211380.0, -1359630.0, 231690.0)

def run_cmd(cmd):
    print("RUNNING:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def get_coord_transform():
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    epsg3979 = osr.SpatialReference()
    epsg3979.ImportFromEPSG(3979)
    epsg3979.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(wgs84, epsg3979)

def load_primary_stations():
    stations = []
    stn_dem_path = DERIVED_DIR / "station_dem.csv"
    if not stn_dem_path.exists():
        stn_dem_path = SLICE_A_DIR / "station_dem.csv"
    with open(stn_dem_path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            stations.append({
                "num": r["station_num"],
                "id": r["mlp_station_id"],
                "name": r["station_name"].replace("Stn. ", "").replace(" (Shoulder)", ""),
                "x": float(r["x_epsg3979"]),
                "y": float(r["y_epsg3979"]),
                "elev": float(r["dem_cell_m"]),
            })
    return stations

def plot_geojson_projected(ax, geojson_path, tx, color, lw=1.0, ls="-", alpha=0.9, facecolor=None, zorder=3):
    data = json.load(open(geojson_path, "r", encoding="utf-8"))
    for feat in data.get("features", []):
        geom = feat.get("geometry")
        if not geom:
            continue
        gtype = geom["type"]
        coords = geom["coordinates"]

        def draw_ring(ring_coords, is_poly=False):
            pts = [tx.TransformPoint(c[0], c[1])[:2] for c in ring_coords]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if is_poly and facecolor:
                ax.fill(xs, ys, facecolor=facecolor, edgecolor=color, linewidth=lw, linestyle=ls, alpha=alpha, zorder=zorder)
            else:
                ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, alpha=alpha, zorder=zorder)

        if gtype == "LineString":
            draw_ring(coords, False)
        elif gtype == "MultiLineString":
            for line in coords:
                draw_ring(line, False)
        elif gtype == "Polygon":
            draw_ring(coords[0], True)
        elif gtype == "MultiPolygon":
            for poly in coords:
                draw_ring(poly[0], True)

def style_axes_km(ax, bounds, title):
    xmin, ymin, xmax, ymax = bounds
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.set_xlabel("EPSG:3979 Easting (m)", fontsize=8)
    ax.set_ylabel("EPSG:3979 Northing (m)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.4, color="white")

def save_fig_checked(fig, out_path, dpi=120):
    fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight", facecolor="#f8f9fa")
    plt.close(fig)
    im = Image.open(str(out_path))
    w, h = im.size
    assert w < 1500 and h < 1500, f"{out_path} exceeds 1500 px: {w}x{h}"
    print(f"Saved quicklook {out_path} ({w}x{h} px)")

def read_band(path, band_idx=1):
    ds = gdal.Open(str(path))
    arr = ds.GetRasterBand(band_idx).ReadAsArray()
    ds = None
    return arr

def main():
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    QL_DIR.mkdir(parents=True, exist_ok=True)

    # Generate hillshade GeoTIFFs via gdaldem hillshade
    hs_vs_tif = str(DERIVED_DIR / "hillshade_viewshed_30m_epsg3979.tif")
    hs_core_tif = str(DERIVED_DIR / "hillshade_core_30m_epsg3979.tif")
    run_cmd(["gdaldem", "hillshade", "-z", "1.5", "-az", "315", "-alt", "45", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
             str(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif"), hs_vs_tif])
    run_cmd(["gdaldem", "hillshade", "-z", "1.5", "-az", "315", "-alt", "45", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
             str(DERIVED_DIR / "dem_core_30m_epsg3979.tif"), hs_core_tif])

    hs_vs = read_band(hs_vs_tif)
    dem_vs = read_band(DERIVED_DIR / "dem_viewshed_30m_epsg3979.tif")
    hs_core = read_band(hs_core_tif)
    dem_core = read_band(DERIVED_DIR / "dem_core_30m_epsg3979.tif")

    stations = load_primary_stations()
    tx = get_coord_transform()
    txt_halo = [pe.withStroke(linewidth=2.2, foreground="white")]
    dark_halo = [pe.withStroke(linewidth=2.2, foreground="black")]

    vs_extent = [VS_BOUNDS[0], VS_BOUNDS[2], VS_BOUNDS[1], VS_BOUNDS[3]]
    core_extent = [CORE_BOUNDS[0], CORE_BOUNDS[2], CORE_BOUNDS[1], CORE_BOUNDS[3]]

    # 1. Viewshed DEM + Hillshade + Stations
    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    ax.imshow(hs_vs, cmap="gray", extent=vs_extent, origin="upper", alpha=1.0)
    im = ax.imshow(dem_vs, cmap="terrain", extent=vs_extent, origin="upper", alpha=0.45, vmin=1068, vmax=3156)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Elevation (m, CGVD2013)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    # Core box rectangle
    rect = Rectangle((CORE_BOUNDS[0], CORE_BOUNDS[1]), CORE_BOUNDS[2] - CORE_BOUNDS[0], CORE_BOUNDS[3] - CORE_BOUNDS[1],
                     linewidth=1.5, edgecolor="#d90429", facecolor="none", linestyle="--", zorder=5, label="Core Box")
    ax.add_patch(rect)

    for s in stations:
        ax.scatter(s["x"], s["y"], c="#ffbe0b", edgecolor="black", s=65, linewidth=1.2, zorder=6)
        ax.text(s["x"] + 700, s["y"] + 400, f"{s['num']}", fontsize=7.5, fontweight="bold", color="black", path_effects=txt_halo, zorder=7)

    style_axes_km(ax, VS_BOUNDS, "Viewshed-Box DEM (NRCan MRDEM-30, 2342×2282 @ 30 m) & 1914 Camera Stations")
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", label="1914 Camera Stations (84–89)", markerfacecolor="#ffbe0b", markeredgecolor="k", markersize=8),
        Patch(edgecolor="#d90429", facecolor="none", linestyle="--", linewidth=1.5, label="Core Box (735×677 @ 30 m)")
    ], loc="lower right", fontsize=8, framealpha=0.9)
    save_fig_checked(fig, QL_DIR / "ql_01_dem_viewshed_hillshade_stations.png")

    # 2. Core DEM + Hillshade + Stations
    fig, ax = plt.subplots(figsize=(9.5, 8.2))
    ax.imshow(hs_core, cmap="gray", extent=core_extent, origin="upper", alpha=1.0)
    im = ax.imshow(dem_core, cmap="terrain", extent=core_extent, origin="upper", alpha=0.45, vmin=1290, vmax=2910)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Elevation (m, CGVD2013)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    for s in stations:
        ax.scatter(s["x"], s["y"], c="#ff0054", edgecolor="white", s=90, linewidth=1.5, zorder=6)
        ax.text(s["x"] + 250, s["y"] + 180, f"{s['name']} ({s['elev']:.0f} m)", fontsize=8, fontweight="bold",
                color="black", path_effects=txt_halo, zorder=7)

    style_axes_km(ax, CORE_BOUNDS, "Core-Box DEM & Hillshade (NRCan MRDEM-30, 735×677 @ 30 m) with Camera Stations")
    save_fig_checked(fig, QL_DIR / "ql_02_dem_core_hillshade_stations.png")

    # 3. Sentinel-2 TCI + B08/B04 Core Box
    tci_ds = gdal.Open(str(DERIVED_DIR / "s2_20250825_TCI_core_10m_epsg3979.tif"))
    tci_rgb = np.dstack([tci_ds.GetRasterBand(b).ReadAsArray() for b in (1, 2, 3)])
    tci_ds = None
    b04 = read_band(DERIVED_DIR / "s2_20250825_B04_core_10m_epsg3979.tif").astype(np.float32)
    b08 = read_band(DERIVED_DIR / "s2_20250825_B08_core_10m_epsg3979.tif").astype(np.float32)
    # Apply Sentinel-2 BOA offset (-1000 DN) for NDVI display
    red_sr = np.clip((b04 - 1000.0) / 10000.0, 0.0001, 1.0)
    nir_sr = np.clip((b08 - 1000.0) / 10000.0, 0.0001, 1.0)
    ndvi = (nir_sr - red_sr) / (nir_sr + red_sr)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.5))
    # Gamma boost TCI slightly for clear visual inspection of alpine valleys
    tci_disp = np.clip((tci_rgb / 255.0) ** 0.85, 0, 1)
    ax1.imshow(tci_disp, extent=core_extent, origin="upper")
    for s in stations:
        ax1.scatter(s["x"], s["y"], c="#ffbe0b", edgecolor="black", s=55, linewidth=1.0, zorder=6)
        ax1.text(s["x"] + 250, s["y"] + 150, s["num"], fontsize=7.5, fontweight="bold", color="white", path_effects=dark_halo, zorder=7)
    style_axes_km(ax1, CORE_BOUNDS, "Sentinel-2 L2A TCI True Colour (2025-08-25, 10 m)")

    im2 = ax2.imshow(ndvi, cmap="RdYlGn", vmin=-0.1, vmax=0.8, extent=core_extent, origin="upper")
    for s in stations:
        ax2.scatter(s["x"], s["y"], c="#ff0054", edgecolor="white", s=55, linewidth=1.0, zorder=6)
    style_axes_km(ax2, CORE_BOUNDS, "Derived NDVI from B08 & B04 (2025-08-25, 10 m)")
    cbar2 = fig.colorbar(im2, ax=ax2, fraction=0.042, pad=0.02)
    cbar2.set_label("NDVI ((B08 - B04) / (B08 + B04))", fontsize=8)
    cbar2.ax.tick_params(labelsize=7)
    fig.tight_layout()
    save_fig_checked(fig, QL_DIR / "ql_03_s2_tci_core.png")

    # 4. Forest Mask & Fraction (ESA WorldCover 2021 v200) over Hillshade
    fmask_vs = read_band(DERIVED_DIR / "forest_mask_viewshed_30m_epsg3979.tif")
    ffrac_core = read_band(DERIVED_DIR / "forest_fraction_core_30m_epsg3979.tif")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.6))
    ax1.imshow(hs_vs, cmap="gray", extent=vs_extent, origin="upper")
    mask_rgba = np.zeros((fmask_vs.shape[0], fmask_vs.shape[1], 4), dtype=np.float32)
    mask_rgba[fmask_vs == 1] = [0.08, 0.55, 0.18, 0.58]
    ax1.imshow(mask_rgba, extent=vs_extent, origin="upper")
    rect1 = Rectangle((CORE_BOUNDS[0], CORE_BOUNDS[1]), CORE_BOUNDS[2] - CORE_BOUNDS[0], CORE_BOUNDS[3] - CORE_BOUNDS[1],
                      linewidth=1.3, edgecolor="#d90429", facecolor="none", linestyle="--", zorder=5)
    ax1.add_patch(rect1)
    for s in stations:
        ax1.scatter(s["x"], s["y"], c="#ffbe0b", edgecolor="black", s=45, zorder=6)
    style_axes_km(ax1, VS_BOUNDS, "Viewshed Forest Mask (Fraction >= 0.5: 52.34% forested)")

    ax2.imshow(hs_core, cmap="gray", extent=core_extent, origin="upper")
    im_f = ax2.imshow(np.ma.masked_where(ffrac_core == 0, ffrac_core), cmap="Greens", vmin=0.0, vmax=1.0, alpha=0.72, extent=core_extent, origin="upper")
    kenow_path = DERIVED_DIR / "kenow_fire_2017_perimeter.geojson"
    if not kenow_path.exists():
        kenow_path = SLICE_A_DIR / "kenow_fire_2017_perimeter.geojson"
    plot_geojson_projected(ax2, kenow_path, tx, color="#e63946", lw=1.2, ls="--", zorder=5)
    for s in stations:
        ax2.scatter(s["x"], s["y"], c="#ffbe0b", edgecolor="black", s=55, zorder=6)
        ax2.text(s["x"] + 250, s["y"] + 150, s["num"], fontsize=7.5, fontweight="bold", color="black", path_effects=txt_halo, zorder=7)
    style_axes_km(ax2, CORE_BOUNDS, "Core Box Tree Fraction (38.39% >= 0.5) & 2017 Fire Perimeter")
    cbar_f = fig.colorbar(im_f, ax=ax2, fraction=0.042, pad=0.02)
    cbar_f.set_label("10 m Tree Cover Share per 30 m Cell", fontsize=8)
    cbar_f.ax.tick_params(labelsize=7)
    fig.tight_layout()
    save_fig_checked(fig, QL_DIR / "ql_04_forest_mask_viewshed.png")

    # 5. Names (Peaks & Passes from CGNDB + GNIS) over Hillshade
    names_path = DERIVED_DIR / "names_peaks_passes.geojson"
    if not names_path.exists():
        names_path = SLICE_A_DIR / "names_peaks_passes.geojson"
    names_data = json.load(open(names_path, "r", encoding="utf-8"))["features"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 5.8))
    ax1.imshow(hs_vs, cmap="gray", extent=vs_extent, origin="upper")
    ax2.imshow(hs_core, cmap="gray", extent=core_extent, origin="upper")

    # Custom label offsets (dx, dy) in metres for panel 2 to prevent any overlap with station labels
    peak_offsets_core = {
        "Mount Blakiston": (300, -900),
        "Lost Mountain": (-3100, -550),
        "Lone Mountain": (350, -750),
        "Anderson Peak": (250, 450),
        "Mount Hawkins": (-3200, -650),
        "Festubert Mountain": (300, -550),
        "Mount Lineham": (300, -350),
        "Mount Rowe": (300, -250),
        "Avion Ridge": (350, -750),
        "Kishinena Peak": (-3300, 450),
        "Sage Mountain": (300, -350),
        "South Kootenay Pass": (-4200, -750),
        "Newman Peak": (300, -300),
        "Mount Glendowan": (300, -350),
        "Mount Dungarvan": (-3600, 550),
    }

    for f in names_data:
        p = f["properties"]
        x, y = p["x_epsg3979"], p["y_epsg3979"]
        src = p["source"]
        ftype = p["feature_type"]
        col = "#2ec4b6" if src == "CGNDB" else "#ff9f1c"
        marker = "^" if ftype != "Pass" else "d"
        ax1.scatter(x, y, c=col, edgecolor="black", marker=marker, s=28, linewidth=0.5, zorder=5)
        if p["name"] in {"Mount Cleveland", "Kintla Peak", "Victoria Peak", "Sofa Mountain", "Mount Haig", "Mount Blakiston", "King Edward Peak"}:
            ax1.text(x + 600, y + 400, f"{p['name']} ({p['elevation']:.0f}m)", fontsize=6.5, fontweight="bold",
                     color="black", path_effects=txt_halo, zorder=7)

        if CORE_BOUNDS[0] <= x <= CORE_BOUNDS[2] and CORE_BOUNDS[1] <= y <= CORE_BOUNDS[3]:
            ax2.scatter(x, y, c=col, edgecolor="black", marker=marker, s=55, linewidth=0.8, zorder=5)
            if p["name"] in peak_offsets_core:
                dx_lbl, dy_lbl = peak_offsets_core[p["name"]]
                ax2.text(x + dx_lbl, y + dy_lbl, f"{p['name']} ({p['elevation']:.0f}m)", fontsize=6.5, fontweight="bold",
                         color="#0b3954", path_effects=txt_halo, zorder=7)

    stn_offsets_core = {
        "84": (250, 350),
        "85": (-1800, -750),
        "86": (250, 300),
        "87": (-2200, 350),
        "88": (250, 250),
        "89": (250, 350),
    }
    for s in stations:
        ax1.scatter(s["x"], s["y"], c="#ff0054", edgecolor="white", s=45, zorder=6)
        ax2.scatter(s["x"], s["y"], c="#ff0054", edgecolor="white", s=65, zorder=6)
        sdx, sdy = stn_offsets_core.get(s["num"], (250, 250))
        ax2.text(s["x"] + sdx, s["y"] + sdy, f"Stn {s['num']}", fontsize=7.5, fontweight="bold", color="#d90429", path_effects=txt_halo, zorder=8)

    style_axes_km(ax1, VS_BOUNDS, "Viewshed Peaks & Passes (108 CGNDB + 63 US GNIS = 171)")
    style_axes_km(ax2, CORE_BOUNDS, "Core Box Peaks, Passes & Camera Stations Over Hillshade")
    ax1.legend(handles=[
        Line2D([0], [0], marker="^", color="w", label="CGNDB Peak/Pass (Canada)", markerfacecolor="#2ec4b6", markeredgecolor="k", markersize=7),
        Line2D([0], [0], marker="^", color="w", label="GNIS Summit/Gap (USA)", markerfacecolor="#ff9f1c", markeredgecolor="k", markersize=7),
        Line2D([0], [0], marker="o", color="w", label="1914 Camera Stations", markerfacecolor="#ff0054", markeredgecolor="w", markersize=7),
    ], loc="lower left", fontsize=7.5, framealpha=0.9)
    fig.tight_layout()
    save_fig_checked(fig, QL_DIR / "ql_05_names_over_hillshade.png")

    # 6. Vectors Overview (Waterton NP Boundary, 2017 Kenow Fire Perimeter, Red Rock Parkway, Core Box Trails)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 5.8))
    ax1.imshow(hs_vs, cmap="gray", extent=vs_extent, origin="upper", alpha=0.85)

    wlnp_path = DERIVED_DIR / "waterton_lakes_np_boundary.geojson"
    if not wlnp_path.exists():
        wlnp_path = SLICE_A_DIR / "waterton_lakes_np_boundary.geojson"

    rr_path = DERIVED_DIR / "red_rock_parkway.geojson"
    if not rr_path.exists():
        rr_path = SLICE_A_DIR / "red_rock_parkway.geojson"

    trails_path = DERIVED_DIR / "trails_core.geojson"
    if not trails_path.exists():
        trails_path = SLICE_A_DIR / "trails_core.geojson"

    plot_geojson_projected(ax1, kenow_path, tx,
                           color="#d90429", lw=1.2, facecolor="#ef233c", alpha=0.35, zorder=4)
    plot_geojson_projected(ax1, wlnp_path, tx,
                           color="#00b4d8", lw=1.8, ls="-", facecolor=None, alpha=0.95, zorder=5)
    rect2 = Rectangle((CORE_BOUNDS[0], CORE_BOUNDS[1]), CORE_BOUNDS[2] - CORE_BOUNDS[0], CORE_BOUNDS[3] - CORE_BOUNDS[1],
                      linewidth=1.2, edgecolor="#ffbe0b", facecolor="none", linestyle="--", zorder=6)
    ax1.add_patch(rect2)
    for s in stations:
        ax1.scatter(s["x"], s["y"], c="#ffbe0b", edgecolor="black", s=45, zorder=7)
    style_axes_km(ax1, VS_BOUNDS, "Waterton Lakes NP Boundary & 2017 Kenow Fire (34,520.5 ha)")
    ax1.legend(handles=[
        Patch(edgecolor="#00b4d8", facecolor="none", linewidth=1.8, label="Waterton Lakes NP Boundary"),
        Patch(edgecolor="#d90429", facecolor="#ef233c", alpha=0.4, label="2017 Kenow Fire Perimeter (NBAC)"),
        Patch(edgecolor="#ffbe0b", facecolor="none", linestyle="--", label="Core Box"),
    ], loc="lower left", fontsize=7.5, framealpha=0.9)

    ax2.imshow(hs_core, cmap="gray", extent=core_extent, origin="upper", alpha=0.85)
    plot_geojson_projected(ax2, kenow_path, tx,
                           color="#d90429", lw=1.0, ls="--", facecolor="#ef233c", alpha=0.18, zorder=3)
    plot_geojson_projected(ax2, wlnp_path, tx,
                           color="#00b4d8", lw=1.8, ls="-", zorder=4)
    plot_geojson_projected(ax2, trails_path, tx,
                           color="#ff9f1c", lw=1.2, ls="-", zorder=5)
    plot_geojson_projected(ax2, rr_path, tx,
                           color="#7209b7", lw=2.4, ls="-", zorder=6)
    for s in stations:
        ax2.scatter(s["x"], s["y"], c="#ffbe0b", edgecolor="black", s=65, zorder=7)
        ax2.text(s["x"] + 250, s["y"] + 150, f"Stn {s['num']}", fontsize=7.5, fontweight="bold", color="black", path_effects=txt_halo, zorder=8)
    style_axes_km(ax2, CORE_BOUNDS, "Core Box: Red Rock Parkway & OSM Trails (125 segments)")
    ax2.legend(handles=[
        Line2D([0], [0], color="#7209b7", lw=2.4, label="Red Rock Parkway (OSM)"),
        Line2D([0], [0], color="#ff9f1c", lw=1.4, label="Core Box Trails & Routes (OSM)"),
        Line2D([0], [0], color="#00b4d8", lw=1.8, label="Waterton Lakes NP Boundary"),
        Line2D([0], [0], marker="o", color="w", label="1914 Camera Stations", markerfacecolor="#ffbe0b", markeredgecolor="k", markersize=7),
    ], loc="lower left", fontsize=7.5, framealpha=0.9)
    fig.tight_layout()
    save_fig_checked(fig, QL_DIR / "ql_06_vectors_overview.png")

if __name__ == "__main__":
    main()
