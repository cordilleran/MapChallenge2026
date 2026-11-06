"""Pick 60 profile targets (10 per station, half seen and half hidden in r.viewshed) inside the core box.
Usage: python3 -I make_los_cases.py <viewshed_dir> <stations.csv> <out.json>"""
import csv, json, sys
import numpy as np
from osgeo import gdal
gdal.UseExceptions()
vdir, scsv, out = sys.argv[1:4]
x0c, y1c, x1c, y0c = -1381680.0, 231690.0, -1359630.0, 211380.0   # core box bounds, EPSG:3979
st = {}
for r in csv.DictReader(open(scsv)):
    if r["station_x_epsg3979"] and r["station_num"] in ("84", "85", "86", "87", "88", "89"):
        st.setdefault(r["station_num"], (float(r["station_x_epsg3979"]), float(r["station_y_epsg3979"])))
rng = np.random.default_rng(20261105)
cases = []
for s, (sx, sy) in sorted(st.items()):
    ds = gdal.Open(f"{vdir}/vs_{s}_main.tif"); a = ds.ReadAsArray(); g = ds.GetGeoTransform()
    for want in (1, 0):
        n = 0
        while n < 5:
            x = rng.uniform(x0c + 300, x1c - 300); y = rng.uniform(y0c + 300, y1c - 300)
            c, r = int((x - g[0]) / g[1]), int((y - g[3]) / g[5])
            if a[r, c] != want or np.hypot(x - sx, y - sy) < 1000: continue
            cx, cy = g[0] + (c + .5) * g[1], g[3] + (r + .5) * g[5]   # target at a cell centre
            cases.append({"station": int(s), "sx": sx, "sy": sy, "tx": cx, "ty": cy, "rv": int(want)}); n += 1
json.dump({"seed": 20261105, "cases": cases}, open(out, "w"), indent=0)
print(len(cases), "cases")
