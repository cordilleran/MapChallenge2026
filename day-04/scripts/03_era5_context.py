"""Day 4: storm-environment context from ERA5 at the flashes, hour by hour.

For each hour (20 to 09 UTC) take ERA5 at the location of every flash within
30 minutes of the hour (bilinear), and average: so each value is weighted by
where the lightning was. Quantities:
  steering wind: mean of the 850, 700, 500 and 300 hPa winds (a common
    proxy for the motion of a convective cell), rotated into BC Albers
    grid east and north, in km/h;
  bulk shear 925 to 500 hPa (m/s); lapse rate 850 to 500 hPa (deg C/km);
  CAPE (J/kg), CIN (J/kg; ERA5 leaves it empty where there is no CAPE, so
  the mean is over the flashes where it is defined), total column water vapour (kg/m2).
The night value of each quantity is weighted by flashes over the hours where
it is defined.
Inputs: MC26_ERA5_DIR holding the files from 01_fetch_era5.py;
day-04/data/flashes.parquet.
Outputs: day-04/data/era5_hourly.csv, site/data/day04_era5.js.
"""
import glob, json, os
from pathlib import Path
import numpy as np, pandas as pd, xarray as xr
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
E = Path(os.environ["MC26_ERA5_DIR"])
F = pd.read_parquet(ROOT / "day-04/data/flashes.parquet")
T0 = np.datetime64("2021-06-30T20:00:00")
low = xr.open_mfdataset(sorted(glob.glob(str(E / "era5_pl925_700_*.nc"))), combine="by_coords").load()
up = xr.open_mfdataset(sorted(glob.glob(str(E / "era5_pl500_300_*.nc"))), combine="by_coords").load()
sl = xr.open_mfdataset(sorted(glob.glob(str(E / "era5_sl_*.nc"))), combine="by_coords").load()
tr = Transformer.from_crs(4326, 3005, always_xy=True)

def at(da, lat, lon):
    # bilinear; the clip only guards against a point on the grid edge
    lon = np.clip(lon, float(da.longitude.min()), float(da.longitude.max()))
    lat = np.clip(lat, float(da.latitude.min()), float(da.latitude.max()))
    return da.interp(latitude=xr.DataArray(lat, dims="p"), longitude=xr.DataArray(lon, dims="p")).values

rows = []
for h in range(0, 14):  # 20Z to 09Z
    vt = T0 + np.timedelta64(h, "h")
    sel = F[np.abs(F.ts - h * 3600) <= 1800]
    if len(sel) < 5:
        continue
    la, lo = sel.lat.values, sel.lon.values
    L = low.sel(valid_time=vt); U = up.sel(valid_time=vt); S = sl.sel(valid_time=vt)
    u = np.mean([at(L.u.sel(pressure_level=850), la, lo), at(L.u.sel(pressure_level=700), la, lo),
                 at(U.u.sel(pressure_level=500), la, lo), at(U.u.sel(pressure_level=300), la, lo)], 0)
    v = np.mean([at(L.v.sel(pressure_level=850), la, lo), at(L.v.sel(pressure_level=700), la, lo),
                 at(U.v.sel(pressure_level=500), la, lo), at(U.v.sel(pressure_level=300), la, lo)], 0)
    # rotate (east, north) m/s into BC Albers grid axes by projecting a 1 km step
    x0, y0 = tr.transform(lo, la)
    xe, ye = tr.transform(lo + 1 / (111.32 * np.cos(np.radians(la))), la)
    ang = np.arctan2(ye - y0, xe - x0)  # grid rotation of local east
    ug = (u * np.cos(ang) - v * np.sin(ang)) * 3.6
    vg = (u * np.sin(ang) + v * np.cos(ang)) * 3.6
    du = at(U.u.sel(pressure_level=500), la, lo) - at(L.u.sel(pressure_level=925), la, lo)
    dv = at(U.v.sel(pressure_level=500), la, lo) - at(L.v.sel(pressure_level=925), la, lo)
    z850 = at(L.z.sel(pressure_level=850), la, lo) / 9.80665
    t850 = at(L.t.sel(pressure_level=850), la, lo)
    t500 = at(U.t.sel(pressure_level=500), la, lo)
    # 500 hPa geopotential is not in the upper file: estimate thickness hypsometrically (mean layer T)
    z500 = z850 + 287.05 * (t850 + t500) / 2 / 9.80665 * np.log(850 / 500)
    rows.append(dict(hour_utc=(20 + h) % 24, h=h, n=len(sel), u_kmh=ug.mean(), v_kmh=vg.mean(),
                     speed_kmh=np.hypot(ug.mean(), vg.mean()),
                     dir_to_deg=(np.degrees(np.arctan2(ug.mean(), vg.mean())) + 360) % 360,
                     shear_ms=np.hypot(du, dv).mean(), lapse_ckm=((t850 - t500) / ((z500 - z850) / 1000)).mean(),
                     cape=at(S.cape, la, lo).mean(), cin=np.nanmean(at(S.cin, la, lo)), cin_share=float(np.isfinite(at(S.cin, la, lo)).mean()), tcwv=at(S.tcwv, la, lo).mean()))
H = pd.DataFrame(rows)
def wmean(k, wt):
    ok = np.isfinite(H[k]) & (wt > 0)
    return float((H[k][ok] * wt[ok]).sum() / wt[ok].sum())
night = {k: wmean(k, H.n) for k in ["u_kmh", "v_kmh", "shear_ms", "lapse_ckm", "cape", "tcwv"]}
night["cin"] = wmean("cin", H.n * H.cin_share)  # weight by the flashes where CIN is defined
night["speed_kmh"] = float(np.hypot(night["u_kmh"], night["v_kmh"]))
night["dir_to_deg"] = float((np.degrees(np.arctan2(night["u_kmh"], night["v_kmh"])) + 360) % 360)
H.to_csv(ROOT / "day-04/data/era5_hourly.csv", index=False, float_format="%.3f")
out = dict(note="ERA5 (Copernicus Climate Change Service), at flashes within 30 min of each hour, flash-weighted. Steering = mean of 850/700/500/300 hPa wind in BC Albers grid axes. 500 hPa height estimated hypsometrically.",
           hourly=H.round(3).to_dict(orient="list"), night={k: round(v, 3) for k, v in night.items()})
(ROOT / "site/data/day04_era5.js").write_text("/* Day 4 ERA5 context. Generated by day-04/scripts/03_era5_context.py; do not edit. */\nwindow.D4ERA5 = " + json.dumps(out, separators=(",", ":")) + ";\n")
print(H.round(1).to_string(index=False)); print(night)
