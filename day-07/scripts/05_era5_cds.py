"""Day 7: ERA5 hourly wind for April 1962 near Duluth, then a double wind rose.

Fetch: 10 m u/v (single levels) and 700 hPa u/v (pressure levels), hourly,
1962-04-01..30, box N 47.75 W -93.25 S 46.5 E -91.5, NetCDF. Needs a CDS key in
~/.cdsapirc (never printed). Existing files are skipped.
Rose: ERA5 cell nearest Duluth (46.784 N, -92.105 W), 16 sectors, meteorological
direction (from). Writes derived/wind_rose_double.csv.

Environments: the fetch needs `cdsapi`, the rose needs `xarray`+`netCDF4`+`pandas`.
If no one Python has both, run the script with each (as run_day07.sh does):
  $PY_CDS 05_era5_cds.py   (fetch; the rose is skipped if xarray is missing)
  $PY_NC 05_era5_cds.py    (rose; the fetch is skipped if the files exist)
Data dir: $MC26_DAY07_DATA (required).
"""
import os
import sys
from pathlib import Path

if not os.environ.get("MC26_DAY07_DATA"):
    sys.exit("Set MC26_DAY07_DATA: the working folder for Day 7 data, outside the repo")
D = Path(os.environ["MC26_DAY07_DATA"]).expanduser()
RAW, DER = D / "raw", D / "derived"
RAW.mkdir(parents=True, exist_ok=True); DER.mkdir(parents=True, exist_ok=True)
SL, PL, OUT = RAW / "era5_1962_04_sl.nc", RAW / "era5_1962_04_pl700.nc", DER / "wind_rose_double.csv"
AREA = [47.75, -93.25, 46.5, -91.5]  # N, W, S, E
DULUTH = (46.784, -92.105)
COMMON = {"product_type": ["reanalysis"], "year": ["1962"], "month": ["04"],
          "day": [f"{d:02d}" for d in range(1, 31)], "time": [f"{h:02d}:00" for h in range(24)],
          "area": AREA, "data_format": "netcdf", "download_format": "unarchived"}


def fetch():
    todo = [(SL, "reanalysis-era5-single-levels", {"variable": ["10m_u_component_of_wind", "10m_v_component_of_wind"]}),
            (PL, "reanalysis-era5-pressure-levels", {"variable": ["u_component_of_wind", "v_component_of_wind"], "pressure_level": ["700"]})]
    todo = [t for t in todo if not t[0].exists()]
    if not todo:
        return
    import cdsapi
    c = cdsapi.Client(quiet=True)
    for f, ds, extra in todo:
        tmp = f.with_suffix(".part")
        c.retrieve(ds, {**COMMON, **extra}, str(tmp))  # blocks while queued
        tmp.rename(f)


def direction_from(u, v):
    """Meteorological direction the wind blows FROM, degrees, 0 = north."""
    import numpy as np
    return np.degrees(np.arctan2(-u, -v)) % 360


def check_formula():
    # known cases: westerly (u>0, v=0) is FROM 270; southerly (u=0, v>0) FROM 180; wind to NE (u=v=1) FROM 225
    import numpy as np
    got = direction_from(np.array([5., 0, 1, 0, -3]), np.array([0., 5, 1, -2, 0]))
    assert np.allclose(got, [270, 180, 225, 0, 90]), got
    print("direction check passed: u=5,v=0 -> 270; u=0,v=5 -> 180; u=v=1 -> 225; v=-2 -> 0; u=-3 -> 90")


def rose():
    import numpy as np, pandas as pd, xarray as xr
    check_formula()
    rows = []
    for level, f, un, vn in [("10m", SL, "u10", "v10"), ("700hPa", PL, "u", "v")]:
        with xr.open_dataset(f) as whole:
            ds = whole.sel(latitude=DULUTH[0], longitude=DULUTH[1], method="nearest").load()
        if "pressure_level" in ds.dims:
            ds = ds.squeeze("pressure_level", drop=True)
        u, v = ds[un].values.astype(float), ds[vn].values.astype(float)
        n = u.size
        sp, dr = np.hypot(u, v), direction_from(u, v)
        sec = (np.round(dr / 22.5).astype(int) % 16) * 22.5
        for s in np.arange(16) * 22.5:
            m = sec == s
            rows.append(dict(level=level, sector_from_deg=s, hours=int(m.sum()), share=m.sum() / n,
                             mean_speed_ms=float(sp[m].mean()) if m.any() else float("nan")))
        print(f"{level}: cell lat {float(ds.latitude):.2f} lon {float(ds.longitude):.2f}, n={n} h, "
              f"scalar mean {sp.mean():.2f} m/s, vector mean {np.hypot(u.mean(), v.mean()):.2f} m/s "
              f"from {direction_from(u.mean(), v.mean()):.0f} deg")
    pd.DataFrame(rows).to_csv(OUT, index=False, float_format="%.4f")
    print("wrote", OUT)


if __name__ == "__main__":
    fetch()
    if SL.exists() and PL.exists():
        if not OUT.exists():
            try:
                rose()
            except ImportError as e:
                print("rose skipped (", e, "); rerun with the geospatial venv")
        else:
            print(OUT, "exists; skipped")
