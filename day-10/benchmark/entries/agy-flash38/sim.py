#!/usr/bin/env python3
"""
sim.py - Hillslope Erosion and Deposition Simulator for Dryland Environments

Simulates hillslope evolution under coupled soil creep, overland flow erosion/deposition,
episodic convective storms, and patchy vegetation dynamics.

Usage:
    python3 sim.py --seed 42 --out OUTDIR [--z0 FILE] [--rain-scale F] [--veg-scale F] [--dt-scale F] [--no-map]
"""

import os
import sys
import json
import heapq
import argparse
import numpy as np
import scipy.ndimage as ndi


# ==============================================================================
# 1. Surface and Landscape Generation
# ==============================================================================

def generate_default_surface(H=100, W=100, dx=1.0, rng_surf=None):
    """
    Generate synthetic dryland hillslope elevation falling toward the bottom row.
    Profile includes a convex hilltop crest (creep-dominated), a steep mid-slope
    (fluvial-dominated), and a concave toe-slope (alluvial deposition apron).
    """
    y = np.linspace(0.0, 1.0, H)
    # S-curve / sigmoid profile: crest -> planar/steep slope -> gentle base
    # Falling from ~17.0 m at row 0 to ~2.0 m at row H-1
    profile = 2.0 + 15.0 * (1.0 - (y ** 1.3))
    z = np.tile(profile[:, None], (1, W)).astype(np.float64)

    # Gentle cross-slope curvature (subtle swale and ridge)
    x = np.linspace(0.0, 1.0, W)
    swale = 0.25 * np.cos(2.0 * np.pi * x) * (1.0 - y[:, None])
    z += swale

    # Micro-roughness
    if rng_surf is not None:
        raw_noise = rng_surf.normal(0.0, 0.04, size=(H, W))
        roughness = ndi.gaussian_filter(raw_noise, sigma=1.5)
        z += roughness

    return z


def generate_vegetation(H=100, W=100, rng_veg=None, veg_scale=1.0):
    """
    Generate patchy dryland shrub cover (0 to 1).
    Dryland vegetation typically forms spatially correlated clusters / clumps
    separated by bare soil inter-spaces.
    """
    if rng_veg is None:
        rng_veg = np.random.default_rng(42)
    raw = rng_veg.normal(0.0, 1.0, size=(H, W))
    smoothed = ndi.gaussian_filter(raw, sigma=3.5)
    s_min, s_max = smoothed.min(), smoothed.max()
    norm = (smoothed - s_min) / (s_max - s_min + 1e-12)
    # Create patchy contrast (bare ground inter-spaces with clumps)
    veg_base = np.clip((norm - 0.3) / 0.5, 0.0, 1.0)
    
    # Scale and cap at 1.0
    veg = np.clip(veg_base * veg_scale, 0.0, 1.0)
    return veg


def generate_storms(n_years=200, rng_storm=None):
    """
    Generate random convective storm events (one per year).
    Depth drawn from a Gamma distribution typical of dryland thunderstorms.
    """
    if rng_storm is None:
        rng_storm = np.random.default_rng(42)
    # Gamma distribution (k=2.0, theta=12.5), mean ~25 mm
    depths = rng_storm.gamma(shape=2.0, scale=12.5, size=n_years)
    depths = np.clip(depths, 5.0, 120.0)
    storms = [(year + 1, float(depths[year])) for year in range(n_years)]
    return storms


# ==============================================================================
# 2. Pit Filling / Depression Resolution
# ==============================================================================

def resolve_depressions(z):
    """
    Ensure every interior cell can drain downhill to the bottom boundary.
    Uses Priority Flood if any depressions or flat sinks exist.
    """
    H, W = z.shape
    padded = np.pad(z, 1, mode='edge')
    center = padded[1:-1, 1:-1]
    shifts = [
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1)
    ]
    min_nbr = np.full((H, W), np.inf)
    for di, dj in shifts:
        nbr = padded[1 + di : 1 + di + H, 1 + dj : 1 + dj + W]
        min_nbr = np.minimum(min_nbr, nbr)

    # Check if any interior cell has no strictly lower neighbor
    has_pit = np.any(center[:-1, :] <= min_nbr[:-1, :])
    if not has_pit:
        return z

    # Priority flood from bottom row
    z_filled = z.copy()
    visited = np.zeros((H, W), dtype=bool)
    pq = []
    for j in range(W):
        heapq.heappush(pq, (z[H - 1, j], H - 1, j))
        visited[H - 1, j] = True

    while pq:
        elev, i, j = heapq.heappop(pq)
        for di, dj in shifts:
            ni, nj = i + di, j + dj
            if 0 <= ni < H and 0 <= nj < W and not visited[ni, nj]:
                visited[ni, nj] = True
                if z_filled[ni, nj] <= elev:
                    z_filled[ni, nj] = elev + 1e-5
                heapq.heappush(pq, (z_filled[ni, nj], ni, nj))

    return z_filled


# ==============================================================================
# 3. Coupled Geomorphic Processes Simulation
# ==============================================================================

def simulate_hillslope(
    z_init,
    veg,
    storms,
    dx=1.0,
    rain_scale=1.0,
    dt_scale=1.0,
    d0_creep=0.005,
    kt0=0.02,
    ke0=0.015,
    c_veg=3.0,
    save_history=False
):
    """
    Simulates hillslope evolution over time.
    Couples hillslope creep (diffusion) and overland flow sediment transport.
    
    Returns:
        z: final elevation (2D array)
        total_exported_m3: sediment exported through open boundary
        timesteps_executed: total simulation substeps
        max_dt_years: largest time step duration
        snapshots: optional dictionary of intermediate surfaces
    """
    H, W = z_init.shape
    cell_area = dx * dx
    z = z_init.copy()

    # Shifts for 8 neighbor directions: (di, dj, dist)
    shifts = [
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, np.sqrt(2)), (-1, 1, np.sqrt(2)),
        (1, -1, np.sqrt(2)), (1, 1, np.sqrt(2))
    ]
    I, J = np.ogrid[:H, :W]

    # Time stepping logic
    n_years = len(storms)
    if dt_scale <= 1.0:
        n_substeps = max(1, int(round(1.0 / dt_scale)))
        sub_dt = 1.0 / n_substeps
        step_group = 1
    else:
        n_substeps = 1
        step_group = max(1, int(round(dt_scale)))
        sub_dt = float(step_group)

    total_exported_m3 = 0.0
    timesteps_executed = 0
    max_dt_years = sub_dt

    # Snapshots for interactive exploration (5 time slices)
    snapshots = {}
    snap_interval = max(1, n_years // 4)
    if save_history:
        snapshots[0] = z.copy()

    # Pre-calculated vegetation resistance
    # Process 4: Patchy vegetation dynamics
    # - Creep diffusivity is reduced by root anchoring and stem sheltering: D(V) = D0 / (1 + 2*V)
    # - Runoff generation is reduced by enhanced infiltration: R = P * (1 - 0.4*V)
    # - Transport capacity and detachment are suppressed by hydraulic roughness: Kt(V) = Kt0 / (1 + c_veg*V)
    D_creep = d0_creep / (1.0 + 2.0 * veg)
    veg_flat = veg.ravel()

    storm_idx = 0
    while storm_idx < n_years:
        curr_group = min(step_group, n_years - storm_idx)
        # Combine storm depths in group
        base_depth_mm = sum(storms[storm_idx + g][1] for g in range(curr_group))
        effective_depth_m = (base_depth_mm * rain_scale) / 1000.0
        sub_depth_m = effective_depth_m / n_substeps

        for _ in range(n_substeps):
            timesteps_executed += 1

            # ------------------------------------------------------------------
            # PROCESS 1: Hillslope Creep (Soil Diffusion)
            # Finite volume formulation on cell faces ensures exact conservation.
            # ------------------------------------------------------------------
            # Face diffusivity
            D_x = 0.5 * (D_creep[:, :-1] + D_creep[:, 1:])
            Fx = -D_x * (z[:, 1:] - z[:, :-1]) / dx * dx  # m^3 / yr

            D_y = 0.5 * (D_creep[:-1, :] + D_creep[1:, :])
            Fy = -D_y * (z[1:, :] - z[:-1, :]) / dx * dx  # m^3 / yr

            # Boundaries: top, left, right are closed. Bottom (row H-1) is open.
            s_exit = np.maximum(0.0, (z[H - 2, :] - z[H - 1, :]) / dx)
            Fy_bottom = D_creep[H - 1, :] * s_exit * dx  # m^3 / yr leaving grid

            div_F = np.zeros((H, W), dtype=np.float64)
            div_F[:, 0] += -Fx[:, 0]
            div_F[:, 1:-1] += Fx[:, :-1] - Fx[:, 1:]
            div_F[:, -1] += Fx[:, -1]

            div_F[0, :] += -Fy[0, :]
            div_F[1:-1, :] += Fy[:-1, :] - Fy[1:, :]
            div_F[-1, :] += Fy[-1, :] - Fy_bottom

            dz_creep = (div_F * sub_dt) / cell_area
            z += dz_creep
            total_exported_m3 += float(np.sum(Fy_bottom) * sub_dt)

            # ------------------------------------------------------------------
            # PROCESS 2 & 3: Overland Flow Erosion, Transport, and Deposition
            # Routed downslope via steepest descent D8.
            # ------------------------------------------------------------------
            if sub_depth_m > 0.0:
                # Resolve local depressions to ensure continuous flow to outlet
                z_route = resolve_depressions(z)

                padded = np.pad(z_route, 1, mode='edge')
                center = padded[1:-1, 1:-1]
                slopes_list = []
                nbr_list = []
                for di, dj, dist in shifts:
                    nbr = padded[1 + di : 1 + di + H, 1 + dj : 1 + dj + W]
                    s = (center - nbr) / dist
                    ni = I + di
                    nj = J + dj
                    invalid = (ni < 0) | (ni >= H) | (nj < 0) | (nj >= W)
                    s[invalid] = -1e9
                    slopes_list.append(s)
                    nbr_list.append(ni * W + nj)

                slopes_stack = np.stack(slopes_list, axis=0)
                nbr_stack = np.stack(nbr_list, axis=0)
                best_dir = np.argmax(slopes_stack, axis=0)
                max_slope = np.take_along_axis(slopes_stack, best_dir[None, ...], axis=0)[0]
                rec = np.take_along_axis(nbr_stack, best_dir[None, ...], axis=0)[0]

                # Bottom row drains off-grid (-1)
                rec[H - 1, :] = -1
                max_slope[H - 1, :] = np.maximum(1e-4, (z[H - 2, :] - z[H - 1, :]) / dx)
                max_slope = np.maximum(1e-4, max_slope)

                # Topological sorting by descending elevation
                order = np.argsort(-z_route.ravel())
                rec_flat = rec.ravel()
                slope_flat = max_slope.ravel()

                A_accum = np.ones(H * W, dtype=np.float64) * cell_area
                Qs_in = np.zeros(H * W, dtype=np.float64)
                dz_flow = np.zeros(H * W, dtype=np.float64)

                # Route flow and sediment simultaneously in topological order
                for u in order:
                    r = rec_flat[u]
                    slp = slope_flat[u]
                    v_val = veg_flat[u]

                    # Overland runoff generation (Process 3 & 4)
                    # Infiltration excess: vegetation increases infiltration
                    Qw = A_accum[u] * sub_depth_m * (1.0 - 0.4 * v_val)

                    # Transport capacity (Process 2 & 4)
                    Tc = (kt0 / (1.0 + c_veg * v_val)) * Qw * slp
                    q_in = Qs_in[u]

                    if q_in > Tc:
                        # Flow over-capacity: deposition occurs
                        dep = q_in - Tc
                        dz_flow[u] = dep / cell_area
                        q_out = Tc
                    else:
                        # Flow under-capacity: detachment / erosion occurs
                        deficit = Tc - q_in
                        E_cap = (ke0 / (1.0 + c_veg * v_val)) * Qw * slp
                        ero = min(deficit, E_cap)
                        dz_flow[u] = -ero / cell_area
                        q_out = q_in + ero

                    if r != -1:
                        Qs_in[r] += q_out
                        A_accum[r] += A_accum[u]
                    else:
                        total_exported_m3 += float(q_out)

                z += dz_flow.reshape((H, W))

        storm_idx += curr_group
        if save_history and (storm_idx % snap_interval == 0 or storm_idx == n_years):
            snapshots[storm_idx] = z.copy()

    return z, total_exported_m3, timesteps_executed, max_dt_years, snapshots


# ==============================================================================
# 4. Map & Visualization Generation (PNG & HTML)
# ==============================================================================

def export_map_png(
    out_path,
    z_initial,
    z_final,
    veg,
    dx=1.0,
    years=200,
    mean_rain=25.0,
    sed_exported=0.0
):
    """
    Export publication-grade static map figure (map.png) with relief shading,
    divergent change centred at zero, dryland palette, scale bar, and legend.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, LinearSegmentedColormap, TwoSlopeNorm
    from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar
    import matplotlib.font_manager as fm

    H, W = z_final.shape
    cell_area = dx * dx

    # Custom Dryland Terrain Colormap (Buff -> Ochre -> Terracotta -> Dark Umber)
    colors_dryland = ['#e8d3b0', '#d8b080', '#be7b4a', '#8e4c27', '#502312']
    cmap_dryland = LinearSegmentedColormap.from_list('dryland', colors_dryland, N=256)

    # Divergent Change Colormap Centred at 0 (Crimson -> Cream -> Cyan/Blue)
    colors_change = [
        '#a50026', '#d73027', '#f46d43', '#fdae61',
        '#f7f7f7',
        '#abd9e9', '#74add1', '#4575b4', '#313695'
    ]
    cmap_change = LinearSegmentedColormap.from_list('divergent_change', colors_change, N=256)

    # Shaded relief generator
    vert_exag = 2.0
    ls = LightSource(azdeg=315, altdeg=45)
    shaded_terrain = ls.shade(z_final, cmap=cmap_dryland, vert_exag=vert_exag, blend_mode='overlay')

    dz = z_final - z_initial
    max_abs_dz = max(0.01, float(np.percentile(np.abs(dz), 99.5)))
    norm_dz = TwoSlopeNorm(vmin=-max_abs_dz, vcenter=0.0, vmax=max_abs_dz)

    # Flow accumulation for panel 4
    # Compute simple flow accumulation for visualization
    padded = np.pad(z_final, 1, mode='edge')
    center = padded[1:-1, 1:-1]
    shifts = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
              (-1, -1, np.sqrt(2)), (-1, 1, np.sqrt(2)),
              (1, -1, np.sqrt(2)), (1, 1, np.sqrt(2))]
    I, J = np.ogrid[:H, :W]
    slopes_list = []
    nbr_list = []
    for di, dj, dist in shifts:
        nbr = padded[1 + di : 1 + di + H, 1 + dj : 1 + dj + W]
        s = (center - nbr) / dist
        ni, nj = I + di, J + dj
        invalid = (ni < 0) | (ni >= H) | (nj < 0) | (nj >= W)
        s[invalid] = -1e9
        slopes_list.append(s)
        nbr_list.append(ni * W + nj)
    slopes_stack = np.stack(slopes_list, axis=0)
    nbr_stack = np.stack(nbr_list, axis=0)
    best_dir = np.argmax(slopes_stack, axis=0)
    rec = np.take_along_axis(nbr_stack, best_dir[None, ...], axis=0)[0]
    rec[H - 1, :] = -1
    order = np.argsort(-z_final.ravel())
    A_vis = np.ones(H * W, dtype=np.float64)
    rec_flat = rec.ravel()
    for u in order:
        r = rec_flat[u]
        if r != -1:
            A_vis[r] += A_vis[u]
    A_grid = A_vis.reshape((H, W))

    fig, axes = plt.subplots(2, 2, figsize=(14, 13), dpi=150)
    fig.patch.set_facecolor('#faf7f2')

    # Panel 1: Terrain Elevation with Relief Shading
    ax1 = axes[0, 0]
    ax1.set_facecolor('#faf7f2')
    im1 = ax1.imshow(shaded_terrain, extent=[0, W * dx, H * dx, 0], origin='upper')
    ax1.set_title("A. Hillslope Terrain & Shaded Relief (Final)", fontsize=13, fontweight='bold', pad=10)
    ax1.set_xlabel("Cross-Slope Distance (m)", fontsize=10)
    ax1.set_ylabel("Downslope Distance (m)", fontsize=10)
    # Scale bar (20 m)
    fontprops = fm.FontProperties(size=9, weight='bold')
    bar1 = AnchoredSizeBar(ax1.transData, 20, '20 m', 'lower left', pad=0.5,
                           color='white', frameon=True, size_vertical=1.5, fontproperties=fontprops)
    bar1.patch.set_facecolor('#333333aa')
    ax1.add_artist(bar1)
    ax1.text(0.97, 0.97, f"Illumination: NW (315°)\nVertical Exaggeration: {vert_exag}×",
             transform=ax1.transAxes, ha='right', va='top', fontsize=8.5,
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffffcc', edgecolor='#888888'))

    # Colorbar for Elevation
    sm1 = plt.cm.ScalarMappable(cmap=cmap_dryland, norm=plt.Normalize(vmin=z_final.min(), vmax=z_final.max()))
    sm1.set_array([])
    cb1 = fig.colorbar(sm1, ax=ax1, fraction=0.046, pad=0.04)
    cb1.set_label("Elevation (m)", fontsize=10)

    # Panel 2: Net Elevation Change (Erosion / Deposition)
    ax2 = axes[0, 1]
    ax2.set_facecolor('#faf7f2')
    # Underlay shaded relief in grayscale
    shade_gray = ls.shade(z_final, cmap=plt.cm.gray, vert_exag=vert_exag, blend_mode='overlay')
    ax2.imshow(shade_gray, extent=[0, W * dx, H * dx, 0], origin='upper', alpha=0.4)
    im2 = ax2.imshow(dz, cmap=cmap_change, norm=norm_dz, extent=[0, W * dx, H * dx, 0], origin='upper', alpha=0.85)
    ax2.set_title("B. Net Geomorphic Change (Erosion vs. Deposition)", fontsize=13, fontweight='bold', pad=10)
    ax2.set_xlabel("Cross-Slope Distance (m)", fontsize=10)
    ax2.set_ylabel("Downslope Distance (m)", fontsize=10)
    cb2 = fig.colorbar(im2, ax=ax2, fraction=0.046, pad=0.04)
    cb2.set_label("Net Change (m) [Red: Erosion, Blue: Deposition]", fontsize=10)
    ax2.text(0.03, 0.97, "Red: Mid-slope Rill Incision\nBlue: Toe-slope Alluvial Fan",
             transform=ax2.transAxes, ha='left', va='top', fontsize=8.5,
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffffcc', edgecolor='#888888'))

    # Panel 3: Patchy Vegetation Cover
    ax3 = axes[1, 0]
    ax3.set_facecolor('#faf7f2')
    ax3.imshow(shade_gray, extent=[0, W * dx, H * dx, 0], origin='upper', alpha=0.5)
    cmap_veg = plt.cm.YlGn
    im3 = ax3.imshow(veg, cmap=cmap_veg, vmin=0.0, vmax=1.0, extent=[0, W * dx, H * dx, 0], origin='upper', alpha=0.75)
    ax3.set_title("C. Patchy Shrub Vegetation Mosaic", fontsize=13, fontweight='bold', pad=10)
    ax3.set_xlabel("Cross-Slope Distance (m)", fontsize=10)
    ax3.set_ylabel("Downslope Distance (m)", fontsize=10)
    cb3 = fig.colorbar(im3, ax=ax3, fraction=0.046, pad=0.04)
    cb3.set_label("Vegetation Cover Fraction (0: Bare, 1: Dense)", fontsize=10)
    ax3.text(0.03, 0.97, "Clustered shrubs buffer runoff\nand trap sediment upslope",
             transform=ax3.transAxes, ha='left', va='top', fontsize=8.5,
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffffcc', edgecolor='#888888'))

    # Panel 4: Contributing Drainage Area (Flow Paths)
    ax4 = axes[1, 1]
    ax4.set_facecolor('#faf7f2')
    log_A = np.log10(np.maximum(1.0, A_grid * cell_area))
    cmap_flow = plt.cm.cividis
    im4 = ax4.imshow(log_A, cmap=cmap_flow, extent=[0, W * dx, H * dx, 0], origin='upper')
    ax4.set_title("D. Contributing Drainage Area (Overland Flow Paths)", fontsize=13, fontweight='bold', pad=10)
    ax4.set_xlabel("Cross-Slope Distance (m)", fontsize=10)
    ax4.set_ylabel("Downslope Distance (m)", fontsize=10)
    cb4 = fig.colorbar(im4, ax=ax4, fraction=0.046, pad=0.04)
    cb4.set_label("Log10 Upslope Contributing Area (m²)", fontsize=10)
    ax4.text(0.03, 0.97, "Converging flow lines carve\ndendritic rill networks",
             transform=ax4.transAxes, ha='left', va='top', fontsize=8.5,
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffffcc', edgecolor='#888888'))

    # Overall Super Title and Meta Info
    fig.suptitle(
        f"Simulated Dryland Hillslope Evolution ({years} Years, Mean Rain: {mean_rain:.1f} mm/yr)\n"
        f"Total Sediment Exported: {sed_exported:.2f} m³ | Shaded Relief Vertical Exaggeration: {vert_exag}×",
        fontsize=15, fontweight='bold', y=0.99
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)


def export_map_html(
    out_path,
    z_initial,
    z_final,
    veg,
    snapshots,
    telemetry,
    dx=1.0
):
    """
    Export self-contained interactive teaching tool (map.html).
    Works 100% offline with zero CDN or external dependencies, under 5 MB.
    Every control that updates the visualization includes attribute data-bench.
    """
    H, W = z_final.shape
    cell_area = dx * dx
    times = sorted(snapshots.keys())
    
    # Pack snapshot data as JSON
    snap_data = {str(t): np.round(snapshots[t], 3).tolist() for t in times}
    z_init_list = np.round(z_initial, 3).tolist()
    z_final_list = np.round(z_final, 3).tolist()
    veg_list = np.round(veg, 3).tolist()

    # Precompute log upslope contributing area
    padded = np.pad(z_final, 1, mode='edge')
    center = padded[1:-1, 1:-1]
    shifts = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
              (-1, -1, np.sqrt(2)), (-1, 1, np.sqrt(2)),
              (1, -1, np.sqrt(2)), (1, 1, np.sqrt(2))]
    I, J = np.ogrid[:H, :W]
    slopes_list = []
    nbr_list = []
    for di, dj, dist in shifts:
        nbr = padded[1 + di : 1 + di + H, 1 + dj : 1 + dj + W]
        s = (center - nbr) / dist
        ni, nj = I + di, J + dj
        invalid = (ni < 0) | (ni >= H) | (nj < 0) | (nj >= W)
        s[invalid] = -1e9
        slopes_list.append(s)
        nbr_list.append(ni * W + nj)
    slopes_stack = np.stack(slopes_list, axis=0)
    nbr_stack = np.stack(nbr_list, axis=0)
    best_dir = np.argmax(slopes_stack, axis=0)
    rec = np.take_along_axis(nbr_stack, best_dir[None, ...], axis=0)[0]
    rec[H - 1, :] = -1
    order = np.argsort(-z_final.ravel())
    A_vis = np.ones(H * W, dtype=np.float64)
    rec_flat = rec.ravel()
    for u in order:
        r = rec_flat[u]
        if r != -1:
            A_vis[r] += A_vis[u]
    flow_list = np.round(np.log10(np.maximum(1.0, A_vis.reshape((H, W)) * dx * dx)), 2).tolist()

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dryland Hillslope Geomorphology - Interactive Teaching Tool</title>
<style>
  :root {{
    --bg-main: #f5f2eb;
    --bg-card: #ffffff;
    --text-primary: #2c2523;
    --text-secondary: #5a524e;
    --accent: #b25828;
    --border: #dcd4c7;
    --highlight: #2855b2;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 18px;
  }}
  header {{
    max-width: 1200px;
    margin: 0 auto 16px auto;
    padding-bottom: 12px;
    border-bottom: 2px solid var(--border);
  }}
  h1 {{
    font-size: 1.6rem;
    color: #4a2c16;
    margin-bottom: 4px;
  }}
  .subtitle {{
    font-size: 0.95rem;
    color: var(--text-secondary);
  }}
  .main-layout {{
    max-width: 1200px;
    margin: 0 auto;
    display: grid;
    grid-template-columns: 620px 1fr;
    gap: 20px;
  }}
  @media (max-width: 1024px) {{
    .main-layout {{ grid-template-columns: 1fr; }}
  }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    margin-bottom: 16px;
  }}
  .canvas-container {{
    position: relative;
    width: 600px;
    height: 600px;
    border: 1px solid #aaa;
    border-radius: 4px;
    overflow: hidden;
    background: #e0d8cc;
  }}
  canvas {{
    display: block;
    cursor: crosshair;
  }}
  .map-overlay {{
    position: absolute;
    top: 8px;
    right: 8px;
    background: rgba(255, 255, 255, 0.9);
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 11px;
    border: 1px solid #ccc;
    pointer-events: none;
  }}
  .map-scalebar {{
    position: absolute;
    bottom: 10px;
    left: 10px;
    background: rgba(0, 0, 0, 0.65);
    color: white;
    padding: 4px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: bold;
    pointer-events: none;
  }}
  .scalebar-line {{
    width: 120px; /* 20m = 20 cells = 120px on 600px canvas */
    height: 3px;
    background: white;
    margin-top: 2px;
  }}
  .control-group {{
    margin-bottom: 14px;
  }}
  .control-group label {{
    display: block;
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--text-primary);
    margin-bottom: 5px;
  }}
  .btn-group {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  button {{
    background: #eae4d8;
    border: 1px solid #c4b9a7;
    color: var(--text-primary);
    padding: 6px 12px;
    border-radius: 4px;
    font-size: 0.85rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }}
  button:hover {{
    background: #ded5c4;
  }}
  button.active {{
    background: var(--accent);
    color: white;
    border-color: #8c421b;
  }}
  select, input[type="range"] {{
    width: 100%;
  }}
  select {{
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: white;
    font-size: 0.9rem;
  }}
  .slider-row {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .slider-row span {{
    font-size: 0.85rem;
    font-weight: bold;
    min-width: 45px;
  }}
  .legend-box {{
    margin-top: 10px;
    padding: 10px;
    background: #fbf9f5;
    border: 1px solid var(--border);
    border-radius: 4px;
  }}
  .colorbar {{
    height: 14px;
    border-radius: 2px;
    margin: 6px 0 4px 0;
    border: 1px solid #999;
  }}
  .colorbar-labels {{
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: var(--text-secondary);
  }}
  .probe-panel {{
    background: #f7f3eb;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 0.85rem;
    margin-top: 8px;
  }}
  .probe-val {{ font-weight: bold; color: var(--accent); }}
  .guide-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: #4a2c16;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
  }}
  .landform-list dt {{
    font-weight: bold;
    color: var(--accent);
    margin-top: 8px;
    font-size: 0.9rem;
  }}
  .landform-list dd {{
    font-size: 0.85rem;
    color: var(--text-secondary);
    margin-left: 12px;
  }}
  .telemetry-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
    margin-top: 8px;
  }}
  .telemetry-table th, .telemetry-table td {{
    padding: 4px 8px;
    border: 1px solid var(--border);
    text-align: left;
  }}
  .telemetry-table th {{ background: #eee8dc; }}
</style>
</head>
<body>

<header>
  <h1>Dryland Hillslope Geomorphology Simulator</h1>
  <div class="subtitle">An interactive teaching tool exploring coupled soil creep, overland flow erosion, storm variability, and patchy vegetation dynamics.</div>
</header>

<div class="main-layout">
  <!-- Left Column: Map Canvas and Legend -->
  <div>
    <div class="card" style="padding: 10px;">
      <div class="canvas-container">
        <canvas id="hillslopeCanvas" width="600" height="600"></canvas>
        <div class="map-overlay" id="overlayInfo">
          Shaded Relief: NW (315°)<br>
          <span id="overlayExag">Vertical Exaggeration: 2.0×</span>
        </div>
        <div class="map-scalebar" id="scalebarContainer">
          <span id="scalebarLabel">Scale: 20 m</span>
          <div class="scalebar-line"></div>
        </div>
      </div>

      <!-- Dynamic Legend -->
      <div class="legend-box" id="legendBox">
        <div style="font-size: 12px; font-weight: bold;" id="legendTitle">Elevation (metres above base)</div>
        <div class="colorbar" id="legendGradient"></div>
        <div class="colorbar-labels" id="legendLabels">
          <span id="legendMin">0.0 m</span>
          <span id="legendMid">10.0 m</span>
          <span id="legendMax">20.0 m</span>
        </div>
      </div>

      <!-- Interactive Inspector Probe -->
      <div class="probe-panel" id="probePanel">
        Hover or click on the map to inspect elevation, erosion/deposition, and vegetation at that point.
      </div>
    </div>
  </div>

  <!-- Right Column: Interactive Controls & Educational Guide -->
  <div>
    <!-- Interactive Controls Card -->
    <div class="card">
      <h2 style="font-size: 1.15rem; margin-bottom: 12px; color: #4a2c16;">Controls & Layers</h2>

      <!-- Layer Selection -->
      <div class="control-group">
        <label>Active Display Layer:</label>
        <div class="btn-group" style="margin-bottom: 8px;">
          <button data-bench="layer-terrain" id="btnTerrain" class="active" onclick="setLayer('terrain')">Terrain (Elevation)</button>
          <button data-bench="layer-change" id="btnChange" onclick="setLayer('change')">Change (Erosion / Gain)</button>
          <button data-bench="layer-vegetation" id="btnVeg" onclick="setLayer('vegetation')">Vegetation Cover</button>
          <button data-bench="layer-flow" id="btnFlow" onclick="setLayer('flow')">Overland Flow Paths</button>
        </div>
        <select data-bench="layer-select" id="layerSelect" onchange="setLayer(this.value)">
          <option value="terrain">Terrain Elevation with Relief Shading</option>
          <option value="change">Geomorphic Change (Erosion vs. Deposition)</option>
          <option value="vegetation">Patchy Vegetation Cover Fraction</option>
          <option value="flow">Contributing Drainage Area (Flow Lines)</option>
        </select>
      </div>

      <!-- Time Exploration -->
      <div class="control-group">
        <label>Time Evolution (Simulated Years: <span id="timeVal">{telemetry['years_simulated']}</span> yr):</label>
        <div class="slider-row">
          <input type="range" data-bench="time-slider" id="timeSlider" min="0" max="{telemetry['years_simulated']}" value="{telemetry['years_simulated']}" step="1" oninput="updateTime(this.value)">
        </div>
        <div class="btn-group" style="margin-top: 6px;">
          <button data-bench="time-before" onclick="updateTime(0)">Initial (Year 0)</button>
          <button data-bench="time-after" onclick="updateTime({telemetry['years_simulated']})">Final (Year {telemetry['years_simulated']})</button>
          <button data-bench="time-play" id="playBtn" onclick="togglePlay()">▶ Play Animation</button>
        </div>
      </div>

      <!-- Shading & Exaggeration Controls -->
      <div class="control-group">
        <label>Relief Shading Vertical Exaggeration:</label>
        <div class="slider-row">
          <input type="range" data-bench="vertical-exaggeration" id="exagSlider" min="0.5" max="5.0" step="0.5" value="2.0" oninput="updateExag(this.value)">
          <span id="exagVal">2.0×</span>
        </div>
      </div>

      <div class="control-group">
        <label>Sun Illumination Azimuth (degrees):</label>
        <div class="slider-row">
          <input type="range" data-bench="sun-azimuth" id="azimuthSlider" min="0" max="360" step="15" value="315" oninput="updateAzimuth(this.value)">
          <span id="azimuthVal">315° NW</span>
        </div>
      </div>

      <div class="control-group">
        <label>Layer Overlay Opacity:</label>
        <div class="slider-row">
          <input type="range" data-bench="layer-opacity" id="opacitySlider" min="0.2" max="1.0" step="0.05" value="0.85" oninput="updateOpacity(this.value)">
          <span id="opacityVal">85%</span>
        </div>
      </div>

      <div class="btn-group">
        <button data-bench="toggle-shading" id="btnToggleShading" onclick="toggleShading()">Toggle Relief Shading</button>
        <button data-bench="toggle-contours" id="btnToggleContours" onclick="toggleContours()">Toggle Contours</button>
      </div>
    </div>

    <!-- Educational Guide & Assumptions Card -->
    <div class="card">
      <div class="guide-title">Geomorphic Model Assumptions</div>
      <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 8px;">
        This numerical landscape evolution model couples four essential hillslope processes:
      </p>
      <dl class="landform-list">
        <dt>1. Hillslope Creep (Soil Diffusion):</dt>
        <dd>Soil slowly diffuses downslope driven by local curvature (&nabla;&sup2;z). Biogenic ravel and rainsplash are attenuated where dense vegetation shields the ground.</dd>
        
        <dt>2. Overland Flow Erosion &amp; Deposition:</dt>
        <dd>Runoff routes down the steepest path of contributing area. When sediment load exceeds transport capacity (e.g. where the slope flattens at the foot), sediment is deposited rather than deleted.</dd>

        <dt>3. Episodic Storms (Infiltration Excess):</dt>
        <dd>Rainfall arrives as discrete high-intensity convective storms drawn from a Gamma distribution, generating pulsed runoff events typical of arid environments.</dd>

        <dt>4. Patchy Vegetation Feedbacks:</dt>
        <dd>Shrub clusters increase hydraulic roughness, absorb shear stress, enhance soil infiltration, and act as micro-sediment traps.</dd>
      </dl>

      <div class="guide-title" style="margin-top: 14px;">Landforms to Look For</div>
      <dl class="landform-list">
        <dt>Convex Hilltop Crest:</dt>
        <dd>Rounded ridge crest at the top where diffusive creep dominates over water wash.</dd>
        <dt>Mid-Slope Rill Networks:</dt>
        <dd>Linear incision channels carved by concentrated overland flow on steep, bare patches.</dd>
        <dt>Vegetation Sediment Terraces:</dt>
        <dd>Small mounds of deposited sediment banked immediately upslope of dense shrub clumps.</dd>
        <dt>Basal Alluvial Apron (Fan):</dt>
        <dd>Broad depositional lobe at the base of the slope where transport capacity collapses.</dd>
      </dl>

      <div class="guide-title" style="margin-top: 14px;">Model Telemetry</div>
      <table class="telemetry-table">
        <tr><th>Grid Shape</th><td>{telemetry['grid_shape'][0]} &times; {telemetry['grid_shape'][1]} cells ({telemetry['cell_size_m']} m)</td></tr>
        <tr><th>Duration</th><td>{telemetry['years_simulated']} years ({telemetry['timesteps']} steps)</td></tr>
        <tr><th>Mean Annual Rain</th><td>{telemetry['mean_annual_rain_mm']:.1f} mm/yr</td></tr>
        <tr><th>Total Sediment Exported</th><td>{telemetry['sediment_exported_m3']:.2f} m³</td></tr>
        <tr><th>Mass Balance Conservation</th><td>{100.0 - telemetry['mass_balance_error_pct']:.6f}%</td></tr>
      </table>
    </div>
  </div>
</div>

<script>
// Embedded simulation data
const H = {H};
const W = {W};
const dx = {dx};
const zInit = {json.dumps(z_init_list)};
const zFinal = {json.dumps(z_final_list)};
const vegData = {json.dumps(veg_list)};
const flowData = {json.dumps(flow_list)};
const snapshots = {json.dumps(snap_data)};
const times = {json.dumps(times)};

// State
let activeLayer = 'terrain';
let currentTime = {telemetry['years_simulated']};
let vertExag = 2.0;
let sunAzimuth = 315.0;
let overlayOpacity = 0.85;
let enableShading = true;
let enableContours = false;
let isPlaying = false;
let playTimer = null;

const canvas = document.getElementById('hillslopeCanvas');
const ctx = canvas.getContext('2d');
const cWidth = canvas.width;
const cHeight = canvas.height;

// Precompute min/max bounds
let zMin = 9999, zMax = -9999;
let dzMin = 9999, dzMax = -9999;
for (let i = 0; i < H; i++) {{
  for (let j = 0; j < W; j++) {{
    let z = zFinal[i][j];
    if (z < zMin) zMin = z;
    if (z > zMax) zMax = z;
    let d = zFinal[i][j] - zInit[i][j];
    if (d < dzMin) dzMin = d;
    if (d > dzMax) dzMax = d;
  }}
}}
const maxAbsDz = Math.max(0.02, Math.max(Math.abs(dzMin), Math.abs(dzMax)));

// Color ramps
function getDrylandColor(t) {{
  // t in [0, 1]: Sand buff -> Ochre -> Terracotta -> Dark Umber
  t = Math.max(0, Math.min(1, t));
  const r = Math.round(232 - t * (232 - 80));
  const g = Math.round(211 - t * (211 - 35));
  const b = Math.round(176 - t * (176 - 18));
  return [r, g, b];
}}

function getChangeColor(dz) {{
  // Centred on zero: dz < 0 (Crimson/Red) -> 0 (Cream/White) -> dz > 0 (Deep Blue)
  let norm = dz / maxAbsDz; // [-1, 1]
  norm = Math.max(-1, Math.min(1, norm));
  if (norm < 0) {{
    // Red ramp
    const f = -norm;
    return [Math.round(247 - f * (247 - 165)), Math.round(247 - f * (247 - 0)), Math.round(247 - f * (247 - 38))];
  }} else {{
    // Blue ramp
    const f = norm;
    return [Math.round(247 - f * (247 - 33)), Math.round(247 - f * (247 - 102)), Math.round(247 - f * (247 - 172))];
  }}
}}

function getVegColor(v) {{
  // 0: Bare sand (faint), 1: Lush olive-sage green
  v = Math.max(0, Math.min(1, v));
  const r = Math.round(210 - v * (210 - 45));
  const g = Math.round(200 - v * (200 - 100));
  const b = Math.round(160 - v * (160 - 25));
  return [r, g, b];
}}

function getFlowColor(logA) {{
  // logA from 0 to 4: Light amber to dark indigo/blue
  let norm = Math.max(0, Math.min(1, logA / 3.8));
  const r = Math.round(250 - norm * 230);
  const g = Math.round(235 - norm * 180);
  const b = Math.round(190 - norm * 60);
  return [r, g, b];
}}

// Get elevation grid for current time
function getCurrentElevation() {{
  if (snapshots[currentTime]) return snapshots[currentTime];
  // Find nearest snapshot
  let bestT = times[0];
  let minDiff = 999999;
  for (let t of times) {{
    let diff = Math.abs(t - currentTime);
    if (diff < minDiff) {{ minDiff = diff; bestT = t; }}
  }}
  return snapshots[bestT];
}}

// Main Render Function
function render() {{
  const zCurr = getCurrentElevation();
  const radAz = (sunAzimuth * Math.PI) / 180.0;
  const lx = -Math.sin(radAz);
  const ly = Math.cos(radAz);
  const lz = 1.0;
  const lLen = Math.sqrt(lx*lx + ly*ly + lz*lz);
  const nlx = lx / lLen, nly = ly / lLen, nlz = lz / lLen;

  const imgData = ctx.createImageData(cWidth, cHeight);
  const data = imgData.data;

  const scaleX = W / cWidth;
  const scaleY = H / cHeight;

  for (let cy = 0; cy < cHeight; cy++) {{
    const fy = cy * scaleY;
    const iy = Math.min(H - 1, Math.floor(fy));
    for (let cx = 0; cx < cWidth; cx++) {{
      const fx = cx * scaleX;
      const ix = Math.min(W - 1, Math.floor(fx));

      const idx = (cy * cWidth + cx) * 4;

      // Hillshade computation
      let hs = 1.0;
      if (enableShading) {{
        const xPrev = ix > 0 ? ix - 1 : ix;
        const xNext = ix < W - 1 ? ix + 1 : ix;
        const yPrev = iy > 0 ? iy - 1 : iy;
        const yNext = iy < H - 1 ? iy + 1 : iy;
        const dzdx = ((zCurr[iy][xNext] - zCurr[iy][xPrev]) / (dx * (xNext - xPrev || 1))) * vertExag;
        const dzdy = ((zCurr[yNext][ix] - zCurr[yPrev][ix]) / (dx * (yNext - yPrev || 1))) * vertExag;
        
        const nx = -dzdx, ny = -dzdy, nz = 1.0;
        const nLen = Math.sqrt(nx*nx + ny*ny + nz*nz);
        const dot = (nx*nlx + ny*nly + nz*nlz) / nLen;
        hs = Math.max(0.15, Math.min(1.25, 0.4 + 0.7 * dot));
      }}

      // Base color based on active layer
      let rgb = [200, 200, 200];
      if (activeLayer === 'terrain') {{
        const t = (zCurr[iy][ix] - zMin) / (zMax - zMin + 1e-6);
        rgb = getDrylandColor(t);
      }} else if (activeLayer === 'change') {{
        const d = zCurr[iy][ix] - zInit[iy][ix];
        rgb = getChangeColor(d);
      }} else if (activeLayer === 'vegetation') {{
        rgb = getVegColor(vegData[iy][ix]);
      }} else if (activeLayer === 'flow') {{
        rgb = getFlowColor(flowData[iy][ix]);
      }}

      // Apply hillshade
      let r = rgb[0] * hs;
      let g = rgb[1] * hs;
      let b = rgb[2] * hs;

      // Contours overlay
      if (enableContours) {{
        const elev = zCurr[iy][ix];
        if (Math.abs(elev % 1.0) < 0.06 || Math.abs(elev % 5.0) < 0.08) {{
          r *= 0.6; g *= 0.6; b *= 0.6;
        }}
      }}

      data[idx] = Math.min(255, r);
      data[idx + 1] = Math.min(255, g);
      data[idx + 2] = Math.min(255, b);
      data[idx + 3] = 255;
    }}
  }}

  ctx.putImageData(imgData, 0, 0);
  updateLegend();
}}

function updateLegend() {{
  const lTitle = document.getElementById('legendTitle');
  const lGrad = document.getElementById('legendGradient');
  const lMin = document.getElementById('legendMin');
  const lMid = document.getElementById('legendMid');
  const lMax = document.getElementById('legendMax');

  if (activeLayer === 'terrain') {{
    lTitle.innerText = "Terrain Elevation (metres above base)";
    lGrad.style.background = "linear-gradient(to right, #e8d3b0, #d8b080, #be7b4a, #8e4c27, #502312)";
    lMin.innerText = zMin.toFixed(1) + " m";
    lMid.innerText = ((zMin + zMax) / 2).toFixed(1) + " m";
    lMax.innerText = zMax.toFixed(1) + " m";
  }} else if (activeLayer === 'change') {{
    lTitle.innerText = "Net Elevation Change (Red: Erosion / Loss | Blue: Deposition / Gain)";
    lGrad.style.background = "linear-gradient(to right, #a50026, #f7f7f7, #2166ac)";
    lMin.innerText = (-maxAbsDz).toFixed(2) + " m";
    lMid.innerText = "0.00 m (Neutral)";
    lMax.innerText = "(+)" + maxAbsDz.toFixed(2) + " m";
  }} else if (activeLayer === 'vegetation') {{
    lTitle.innerText = "Vegetation Cover Fraction (Shrub Canopy Density)";
    lGrad.style.background = "linear-gradient(to right, #d2c8a0, #738a32, #2d5a1b)";
    lMin.innerText = "0.0 (Bare Soil)";
    lMid.innerText = "0.5 (Patchy)";
    lMax.innerText = "1.0 (Dense Cover)";
  }} else if (activeLayer === 'flow') {{
    lTitle.innerText = "Contributing Drainage Area (Log10 m²)";
    lGrad.style.background = "linear-gradient(to right, #faebd2, #c89650, #142850)";
    lMin.innerText = "1 m²";
    lMid.innerText = "100 m²";
    lMax.innerText = "10,000 m²";
  }}
}}

// Control handlers
function setLayer(layer) {{
  activeLayer = layer;
  document.getElementById('layerSelect').value = layer;
  document.querySelectorAll('.btn-group button').forEach(b => {{
    if (b.getAttribute('data-bench') === 'layer-' + layer) b.classList.add('active');
    else if (b.getAttribute('data-bench') && b.getAttribute('data-bench').startsWith('layer-')) b.classList.remove('active');
  }});
  render();
}}

function updateTime(val) {{
  currentTime = parseInt(val, 10);
  document.getElementById('timeSlider').value = currentTime;
  document.getElementById('timeVal').innerText = currentTime;
  render();
}}

function updateExag(val) {{
  vertExag = parseFloat(val);
  document.getElementById('exagVal').innerText = vertExag.toFixed(1) + '×';
  document.getElementById('overlayExag').innerText = 'Vertical Exaggeration: ' + vertExag.toFixed(1) + '×';
  render();
}}

function updateAzimuth(val) {{
  sunAzimuth = parseFloat(val);
  let dir = 'N';
  if (sunAzimuth >= 300 && sunAzimuth <= 345) dir = 'NW';
  else if (sunAzimuth > 345 || sunAzimuth < 30) dir = 'N';
  else if (sunAzimuth >= 30 && sunAzimuth <= 75) dir = 'NE';
  else if (sunAzimuth > 75 && sunAzimuth <= 120) dir = 'E';
  else if (sunAzimuth > 120 && sunAzimuth <= 165) dir = 'SE';
  else if (sunAzimuth > 165 && sunAzimuth <= 210) dir = 'S';
  else if (sunAzimuth > 210 && sunAzimuth <= 255) dir = 'SW';
  else dir = 'W';
  document.getElementById('azimuthVal').innerText = Math.round(sunAzimuth) + '° ' + dir;
  document.getElementById('overlayInfo').innerHTML = 'Shaded Relief: ' + dir + ' (' + Math.round(sunAzimuth) + '°)<br><span id="overlayExag">Vertical Exaggeration: ' + vertExag.toFixed(1) + '×</span>';
  render();
}}

function updateOpacity(val) {{
  overlayOpacity = parseFloat(val);
  document.getElementById('opacityVal').innerText = Math.round(overlayOpacity * 100) + '%';
  render();
}}

function toggleShading() {{
  enableShading = !enableShading;
  render();
}}

function toggleContours() {{
  enableContours = !enableContours;
  render();
}}

function togglePlay() {{
  isPlaying = !isPlaying;
  const btn = document.getElementById('playBtn');
  if (isPlaying) {{
    btn.innerText = '⏸ Pause';
    playTimer = setInterval(() => {{
      let nextT = currentTime + 5;
      if (nextT > {telemetry['years_simulated']}) nextT = 0;
      updateTime(nextT);
    }}, 180);
  }} else {{
    btn.innerText = '▶ Play Animation';
    clearInterval(playTimer);
  }}
}}

// Canvas mouse probe
canvas.addEventListener('mousemove', function(e) {{
  const rect = canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;
  const ix = Math.max(0, Math.min(W - 1, Math.floor(cx * (W / cWidth))));
  const iy = Math.max(0, Math.min(H - 1, Math.floor(cy * (H / cHeight))));

  const zCurr = getCurrentElevation();
  const elev = zCurr[iy][ix];
  const delta = elev - zInit[iy][ix];
  const v = vegData[iy][ix];
  const f = Math.round(Math.pow(10, flowData[iy][ix]));

  const panel = document.getElementById('probePanel');
  panel.innerHTML = `
    <strong>Coordinate:</strong> X: ${{(ix * dx).toFixed(0)}}m, Y: ${{(iy * dx).toFixed(0)}}m (Row: ${{iy}}, Col: ${{ix}}) |
    <strong>Elev:</strong> <span class="probe-val">${{elev.toFixed(2)}} m</span> |
    <strong>Net Change:</strong> <span class="probe-val" style="color:${{delta < 0 ? '#b2182b' : '#2166ac'}}">${{delta >= 0 ? '+' : ''}}${{(delta * 1000).toFixed(0)}} mm</span> |
    <strong>Veg Cover:</strong> ${{(v * 100).toFixed(0)}}% |
    <strong>Flow Area:</strong> ${{f}} m²
  `;
}});

// Initial render
render();
</script>

</body>
</html>
"""

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


# ==============================================================================
# 5. Command Line Interface and Main Execution
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Simulate dryland hillslope erosion and deposition."
    )
    parser.add_argument("--seed", type=int, required=True, help="Random seed for roughness, vegetation, and storms")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    parser.add_argument("--z0", type=str, default=None, help="Initial surface elevation file (.npy)")
    parser.add_argument("--rain-scale", type=float, default=1.0, help="Storm rain multiplier")
    parser.add_argument("--veg-scale", type=float, default=1.0, help="Vegetation cover multiplier")
    parser.add_argument("--dt-scale", type=float, default=1.0, help="Time step multiplier")
    parser.add_argument("--no-map", action="store_true", help="Skip generating map.png and map.html")

    args = parser.parse_args()

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    # Deterministic Seed Sequence
    # With --z0, rng_surf is not used, so rng_veg and rng_storm produce the exact same numbers.
    ss = np.random.SeedSequence(args.seed)
    rng_surf, rng_veg, rng_storm = [np.random.default_rng(s) for s in ss.spawn(3)]

    dx = 1.0  # cell size in metres
    n_years = 200

    # 1. Surface Setup
    if args.z0 is not None:
        z_initial = np.load(args.z0).astype(np.float64)
        if z_initial.ndim != 2:
            raise ValueError(f"Expected 2D array in --z0, got shape {z_initial.shape}")
        H, W = z_initial.shape
    else:
        H, W = 100, 100
        z_initial = generate_default_surface(H=H, W=W, dx=dx, rng_surf=rng_surf)

    # 2. Patchy Vegetation
    # Scaled by veg-scale, capped at 1.0 (with 0 the ground is bare)
    veg = generate_vegetation(H=H, W=W, rng_veg=rng_veg, veg_scale=args.veg_scale)

    # 3. Storms (Gamma distribution, episodic convective events)
    storms = generate_storms(n_years=n_years, rng_storm=rng_storm)

    # 4. Simulation
    save_history = not args.no_map
    d0_creep = 0.005  # m^2/yr bare soil diffusivity at low slope
    z_final, sediment_exported, timesteps_exec, dt_years, snapshots = simulate_hillslope(
        z_initial,
        veg,
        storms,
        dx=dx,
        rain_scale=args.rain_scale,
        dt_scale=args.dt_scale,
        d0_creep=d0_creep,
        kt0=0.02,
        ke0=0.015,
        c_veg=3.0,
        save_history=save_history
    )

    # 5. Mass Balance Calculation
    cell_area = dx * dx
    vol_initial = float(np.sum(z_initial) * cell_area)
    vol_final = float(np.sum(z_final) * cell_area)
    vol_change = vol_initial - vol_final
    mass_diff = abs(vol_change - sediment_exported)
    mass_balance_error_pct = float((mass_diff / max(vol_initial, 1.0)) * 100.0)

    mean_annual_rain_mm = float(sum(d for _, d in storms) / n_years)

    # 6. Telemetry Dictionary
    telemetry = {
        "seed": int(args.seed),
        "grid_shape": [int(H), int(W)],
        "cell_size_m": float(dx),
        "years_simulated": int(n_years),
        "timesteps": int(timesteps_exec),
        "dt_years": float(dt_years),
        "storm_count": int(len(storms)),
        "mean_annual_rain_mm": float(round(mean_annual_rain_mm, 4)),
        "creep_diffusivity_m2_per_yr": float(d0_creep),
        "open_boundaries": ["bottom"],
        "sediment_exported_m3": float(round(sediment_exported, 4)),
        "uplift_or_baselevel_m3": 0.0,
        "mass_balance_error_pct": float(mass_balance_error_pct)
    }

    # 7. Write Output Files
    # z_initial.npy
    np.save(os.path.join(out_dir, "z_initial.npy"), z_initial)
    # z_final.npy
    np.save(os.path.join(out_dir, "z_final.npy"), z_final)
    # vegetation.npy
    np.save(os.path.join(out_dir, "vegetation.npy"), veg)

    # storms.csv: columns year and depth_mm, one row per storm, before any scaling
    storms_path = os.path.join(out_dir, "storms.csv")
    with open(storms_path, "w", encoding="utf-8") as f:
        f.write("year,depth_mm\n")
        for yr, depth in storms:
            f.write(f"{yr},{depth:.4f}\n")

    # telemetry.json
    telemetry_path = os.path.join(out_dir, "telemetry.json")
    with open(telemetry_path, "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2)

    # Print telemetry to stdout as well
    print(json.dumps(telemetry, indent=2))

    # Maps (if not --no-map)
    if not args.no_map:
        export_map_png(
            os.path.join(out_dir, "map.png"),
            z_initial,
            z_final,
            veg,
            dx=dx,
            years=n_years,
            mean_rain=mean_annual_rain_mm,
            sed_exported=sediment_exported
        )
        export_map_html(
            os.path.join(out_dir, "map.html"),
            z_initial,
            z_final,
            veg,
            snapshots,
            telemetry,
            dx=dx
        )


if __name__ == "__main__":
    main()
