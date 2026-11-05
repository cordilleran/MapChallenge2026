"""Day 4: fetch ERA5 for the storm night (30 Jun 18Z to 1 Jul 09Z 2021, UTC).

Pressure levels 925, 850 and 700 hPa (low-level winds, temperature and
geopotential) and 500 and 300 hPa (steering and upper winds), plus single-level
storm covariates (CAPE, CIN, K index, total column water vapour), over a box
that covers every flash. Needs a CDS key in ~/.cdsapirc. Output goes to
$MC26_ERA5_DIR (or the folder given as argv[1]); raw files are never
overwritten (an existing file is skipped).
"""
import os, sys
import cdsapi

out = sys.argv[1] if len(sys.argv) > 1 else os.environ["MC26_ERA5_DIR"]
area = [57, -130, 49, -115]  # N, W, S, E: covers every flash (51.2-55.2 N, 127.9-119.6 W) with margin
days = {"2021-06-30": [f"{h:02d}:00" for h in range(18, 24)],
        "2021-07-01": [f"{h:02d}:00" for h in range(0, 10)]}
c = cdsapi.Client(quiet=True)
for d, hours in days.items():
    y, m, dd = d.split("-")
    f = os.path.join(out, f"era5_pl925_700_{d}.nc")
    if not os.path.exists(f):
        c.retrieve("reanalysis-era5-pressure-levels", {
            "product_type": ["reanalysis"], "variable": ["u_component_of_wind", "v_component_of_wind", "temperature", "geopotential"],
            "pressure_level": ["925", "850", "700"], "year": [y], "month": [m], "day": [dd], "time": hours,
            "area": area, "data_format": "netcdf", "download_format": "unarchived"}, f)
    f = os.path.join(out, f"era5_pl500_300_{d}.nc")
    if not os.path.exists(f):
        c.retrieve("reanalysis-era5-pressure-levels", {
            "product_type": ["reanalysis"], "variable": ["u_component_of_wind", "v_component_of_wind", "temperature", "relative_humidity"],
            "pressure_level": ["500", "300"], "year": [y], "month": [m], "day": [dd], "time": hours,
            "area": area, "data_format": "netcdf", "download_format": "unarchived"}, f)
    f = os.path.join(out, f"era5_sl_{d}.nc")
    if not os.path.exists(f):
        c.retrieve("reanalysis-era5-single-levels", {
            "product_type": ["reanalysis"], "variable": ["convective_available_potential_energy", "convective_inhibition", "k_index", "total_column_water_vapour"],
            "year": [y], "month": [m], "day": [dd], "time": hours,
            "area": area, "data_format": "netcdf", "download_format": "unarchived"}, f)
print("done")
