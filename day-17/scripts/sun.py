"""Sun positions for 2026 at Grand Forks (D340): pvlib SPA, 5-minute steps, apparent elevation > 0.

Azimuths are converted to grid azimuth (UTM 11N) by adding the grid azimuth of true north
(+1.087 deg at the site, s2_checks.json). Positions are binned to 1-degree grid-azimuth bins;
for each bin and layer the sorted elevations and cumulative minute counts let a cell's shaded
minutes be read with one searchsorted on its horizon angle.
"""
import numpy as np
import pandas as pd
import pvlib

LAT, LON, ALT = 49.03, -118.44, 520
GRID_CONV = 1.087
STEP_MIN = 5
LAYERS = ("year", "dec", "jun")


def positions():
    t = pd.date_range("2026-01-01 00:02:30", "2026-12-31 23:57:30", freq=f"{STEP_MIN}min", tz="UTC")
    sp = pvlib.solarposition.get_solarposition(t, LAT, LON, altitude=ALT)
    up = sp.apparent_elevation > 0
    sp = sp[up]
    local = sp.index.tz_convert("Etc/GMT+8")  # PST, month assignment only
    return pd.DataFrame({
        "az": (sp.azimuth.values + GRID_CONV) % 360,
        "el": np.radians(sp.apparent_elevation.values),
        "month": local.month,
        "doy": local.dayofyear,
    })


def binned(df):
    """dict bin_center_deg -> {layer: (sorted elev radians, cumulative minutes incl. 0)}; totals per layer."""
    df = df.assign(b=np.floor(df.az).astype(int))
    masks = {"year": np.ones(len(df), bool), "dec": (df.month == 12).values, "jun": (df.month == 6).values}
    totals = {k: float(m.sum() * STEP_MIN) for k, m in masks.items()}
    bins = {}
    for b, g in df.groupby("b"):
        entry = {}
        for k in LAYERS:
            e = np.sort(g.el.values[masks[k][g.index]])
            entry[k] = (e.astype(np.float32), np.arange(len(e) + 1, dtype=np.float32) * STEP_MIN)
        bins[b + 0.5] = entry
    return bins, totals


N_WEEKS = 27


def week_buckets(df_index_days):
    """Declination-week bucket 0..26 for each day of year: the reference day (21 Dec + 7k) with the
    nearest declination (D343). Returns (bucket per position, reference dates, day lists per bucket)."""
    ref = pd.Timestamp("2025-12-21") + pd.to_timedelta(7 * np.arange(N_WEEKS), unit="D")
    dref = pvlib.solarposition.declination_spencer71(ref.dayofyear.values)
    days = pd.date_range("2026-01-01", "2026-12-31", freq="D")
    dday = pvlib.solarposition.declination_spencer71(days.dayofyear.values)
    b_of_doy = np.abs(dday[:, None] - dref[None, :]).argmin(axis=1)
    return b_of_doy[df_index_days - 1], ref, b_of_doy


def weekly_bins(df):
    """dict bin_center -> (sorted elev radians, bucket ids in that order); per-bucket daylight minutes;
    bucket of every day of year."""
    doy = df["doy"].values
    bucket, ref, b_of_doy = week_buckets(doy)
    df = df.assign(wk=bucket, b=np.floor(df.az).astype(int))
    out = {}
    for b, g in df.groupby("b"):
        o = np.argsort(g.el.values)
        out[b + 0.5] = (g.el.values[o].astype(np.float32), g.wk.values[o].astype(np.int64))
    minutes = np.bincount(bucket, minlength=N_WEEKS) * STEP_MIN
    return out, minutes, b_of_doy
