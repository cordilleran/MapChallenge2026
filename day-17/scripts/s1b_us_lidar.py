"""Day 17 S1b (D348): 2 m DSM and DEM south of the border from USGS 3DEP WA_NorthEast_1_B22 (EPT, flown
2022-07-11 to 2022-08-31), on the BC near grid's columns, from the border (BC grid's south edge) to N 5,422,000.
DSM = max of all returns except noise (7, 18); DEM = mean of ground (2), holes filled later.
Output CRS: NAD83(CSRS) / UTM 11N (EPSG:2955), as the BC LiDAR. Vertical: as delivered (NAVD88); aligned in s1."""
import json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _need(var):
    """A path from the environment (see day-17/env.example)."""
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"set {var} (see day-17/env.example)")
    return Path(v).expanduser()


US = _need("MC26_DAY17_DATA") / "us"
EPT = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/WA_NorthEast_1_B22/ept.json"
X0, X1 = 388445, 388445 + 5551 * 2          # BC near grid columns
Y1 = 5436893 - 4271 * 2                       # BC near grid south edge (the border)
NY = (Y1 - 5422000 + 1) // 2 + 1
Y0 = Y1 - NY * 2
NXT, NYT = 6, 3
env = dict(os.environ, PROJ_NETWORK="ON")
PDAL = os.environ.get("MC26_PDAL", "pdal")


def tile(i, j):
    cw, ch = (5551 // NXT + 1) * 2, (NY // NYT + 1) * 2
    x0, y0 = X0 + i * cw, Y0 + j * ch
    x1, y1 = min(x0 + cw, X1), min(y0 + ch, Y1)
    b = f"([{x0},{x1}],[{y0},{y1}])"
    poly = f"POLYGON(({x0 - 10} {y0 - 10}, {x1 + 10} {y0 - 10}, {x1 + 10} {y1 + 10}, {x0 - 10} {y1 + 10}, {x0 - 10} {y0 - 10}))/EPSG:2955"
    tag = f"t{i}{j}"
    p = [
        {"type": "readers.ept", "filename": EPT, "polygon": poly, "tag": "r"},
        {"type": "filters.range", "limits": "Classification![7:7],Classification![18:18]", "inputs": ["r"], "tag": "c"},
        {"type": "filters.reprojection", "out_srs": "EPSG:2955", "inputs": ["c"], "tag": "p"},
        {"type": "writers.gdal", "filename": str(US / f"dsm_{tag}.tif"), "resolution": 2, "output_type": "max",
         "bounds": b, "data_type": "float32", "nodata": -9999, "inputs": ["p"]},
        {"type": "filters.range", "limits": "Classification[2:2]", "inputs": ["p"], "tag": "g"},
        {"type": "writers.gdal", "filename": str(US / f"dem_{tag}.tif"), "resolution": 2, "output_type": "mean",
         "bounds": b, "data_type": "float32", "nodata": -9999, "inputs": ["g"]},
    ]
    f = US / f"{tag}.json"; f.write_text(json.dumps(p))
    r = subprocess.run([PDAL, "pipeline", str(f)], env=env, capture_output=True, text=True)
    return tag, r.returncode, r.stderr.strip()[-300:]


with ThreadPoolExecutor(8) as ex:
    for tag, rc, err in ex.map(lambda ij: tile(*ij), [(i, j) for i in range(NXT) for j in range(NYT)]):
        print(tag, rc, err, flush=True)
print("grid", X0, X1, Y0, Y1, NY)
