"""Peaks and other high points for a map: OSM summits, official names, checked against a terrain model.

Why: CanVec 50K spot heights are too sparse in the mountains (3 in the Sheet 16 window, none at
Waterton), and CGNDB name points sit tens to hundreds of metres off the summit. OSM summits
(natural=peak) are mostly placed on the top and carry an elevation tag. This script:

1. finds every summit of the terrain model and its prominence (height above the highest col that
   joins it to higher ground), by flooding the cells from the top down;
2. for each OSM summit: takes the official CGNDB name where one matches, the nearest model summit
   and its distance, and the elevation (the OSM tag where it agrees with the model, else the model);
3. flags what disagrees, for a look rather than a silent choice;
4. places official names that OSM lacks on the highest prominent model summit near the name point
   (height from the model, which cuts sharp tops: flagged);
5. adds unnamed high points: model summits above a prominence threshold with no OSM summit near.

Reusable: nothing here is specific to Day 6. Inputs are an Overpass JSON of natural=peak nodes, a
CGNDB geonames JSON (optional), and a terrain model in metres.

Writes a GeoPackage with layers
- peaks:       name, name_src, osm_id, cgndb_id, osm_ele_m, dem_ele_m, dem_dist_m, prominence_m,
               ele_m, ele_src, status ('ok', or why to look);
- high_points: ele_m, prominence_m, edge (1 when near the edge of the model, prominence uncertain).

Usage:
  python3 peaks.py --osm osm_peaks.json --names cgndb.json --dem dem.tif --crs EPSG:26911 --out peaks.gpkg
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

PEAK_CODES = {"MTN"}                     # CGNDB concise code for mountains, peaks, ridges, ranges
NO_ELEV_GENERICS = {"Range", "Ridge", "Spur", "Mountains", "Hill"}  # names of a mass, not of a top


def load_dem(path, crs, res):
    """The terrain model on a square grid in the map CRS, nodata as NaN."""
    ds = gdal.Warp("", str(path), format="MEM", dstSRS=crs, xRes=res, yRes=res, resampleAlg="bilinear")
    b = ds.GetRasterBand(1)
    z = b.ReadAsArray().astype(np.float64)
    nd = b.GetNoDataValue()
    if nd is not None:
        z[z == nd] = np.nan
    return z, ds.GetGeoTransform()


def summits(z):
    """Every summit of the grid and its prominence, by flooding from the top (union-find).

    Cells are added from highest to lowest. A cell with no added neighbour starts a new island
    (a summit). A cell that touches two islands is their col: the island with the lower summit
    ends there, and its prominence is its summit height minus the col height. The highest summit
    keeps the height above the lowest cell. Returns {flat index of summit: prominence}.
    """
    h, w = z.shape
    zp = np.full((h + 2, w + 2), -np.inf)
    zp[1:-1, 1:-1] = np.where(np.isnan(z), -np.inf, z)
    flat = zp.ravel()
    W = w + 2
    offs = (-W - 1, -W, -W + 1, -1, 1, W - 1, W, W + 1)
    parent = np.full(flat.size, -1, dtype=np.int64)
    top = {}   # root -> summit cell
    prom = {}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = np.argsort(-flat, kind="stable")
    order = order[np.isfinite(flat[order])]
    for i in order.tolist():
        roots = {find(i + o) for o in offs if parent[i + o] >= 0}
        if not roots:
            parent[i] = i
            top[i] = i
            continue
        roots = sorted(roots, key=lambda r: flat[top[r]], reverse=True)
        main = roots[0]
        for r in roots[1:]:
            prom[top[r]] = flat[top[r]] - flat[i]
            parent[r] = main
        parent[i] = main
    lowest = flat[order[-1]]
    for r, t in top.items():
        if parent[r] == r:
            prom[t] = flat[t] - lowest
    # Back to unpadded flat indices.
    out = {}
    for t, p in prom.items():
        r, c = divmod(t, W)
        out[(r - 1) * w + (c - 1)] = float(p)
    return out


def parse_ele(raw):
    """OSM ele tag to metres, and a note when there is no usable height. Accepts "3048", "3048 m", "10000 ft"."""
    if raw is None:
        return None, "no OSM height"
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(m|ft|')?\s*", raw)
    if not m:
        return None, f"OSM height unreadable ({raw!r})"
    v = float(m.group(1))
    return (v * 0.3048 if m.group(2) in ("ft", "'") else v), ""


def norm(name):
    s = name.lower().replace("’", "'")
    s = re.sub(r"^(mount|mt\.?)\s+", "mt ", s)
    s = re.sub(r"\b(mountain|mtn\.?)$", "mtn", s)
    return re.sub(r"[^a-z0-9 ]", "", s).strip()


def cgndb_mountains(path, tr):
    """CGNDB mountain names, one record per name (the AB and BC copies collapse to one)."""
    if not path:
        return []
    out = {}
    for it in sorted(json.loads(Path(path).read_text())["items"], key=lambda i: i["id"]):
        if it["concise"]["code"] not in PEAK_CODES:
            continue
        x, y = tr.TransformPoint(it["longitude"], it["latitude"])[:2]
        out.setdefault(it["name"], {"name": it["name"], "id": it["id"], "x": x, "y": y,
                                    "generic": it["name"].split()[-1]})  # the API gives a code only
    return list(out.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--osm", required=True, help="Overpass JSON of natural=peak nodes")
    ap.add_argument("--names", help="CGNDB geonames JSON (official names)")
    ap.add_argument("--dem", required=True, help="terrain model, metres")
    ap.add_argument("--crs", required=True, help="map CRS in metres, e.g. EPSG:26911")
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", type=float, default=30.0, help="grid of the model in the map CRS, m")
    ap.add_argument("--min-prom", type=float, default=5.0, help="smallest summit to match an OSM peak to, m")
    ap.add_argument("--high-prom", type=float, default=150.0, help="prominence for an unnamed high point, m")
    ap.add_argument("--agree-m", type=float, default=150.0, help="OSM summit to model summit, m, before a flag")
    ap.add_argument("--name-m", type=float, default=1500.0, help="search radius for the CGNDB name, m")
    ap.add_argument("--snap-m", type=float, default=500.0, help="CGNDB name to model summit, when OSM has none")
    ap.add_argument("--snap-prom", type=float, default=100.0)
    ap.add_argument("--edge-m", type=float, default=1000.0)
    a = ap.parse_args(argv)

    z, gt = load_dem(a.dem, a.crs, a.res)
    h, w = z.shape
    prom = summits(z)
    idx = np.array([k for k, p in prom.items() if p >= a.min_prom])
    pr, pc = np.divmod(idx, w)
    px, py = gt[0] + (pc + 0.5) * gt[1], gt[3] + (pr + 0.5) * gt[5]
    pz, pp = z.ravel()[idx], np.array([prom[k] for k in idx])

    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference()
    dst.SetFromUserInput(a.crs)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(wgs, dst)
    names = cgndb_mountains(a.names, tr)

    rows, used = [], set()
    for el in sorted(json.loads(Path(a.osm).read_text())["elements"], key=lambda e: e["id"]):
        tags = el.get("tags", {})
        if el.get("type") != "node" or tags.get("natural") != "peak":
            continue
        x, y = tr.TransformPoint(el["lon"], el["lat"])[:2]
        d = np.hypot(px - x, py - y)
        k = int(np.argmin(d))
        osm_ele, ele_note = parse_ele(tags.get("ele"))
        r = {"x": x, "y": y, "osm_id": el["id"], "osm_name": tags.get("name", ""), "osm_ele_m": osm_ele,
             "dem_ele_m": round(float(pz[k]), 1), "dem_dist_m": round(float(d[k])),
             "prominence_m": round(float(pp[k])), "_k": k}
        # Official name: the same name nearby, else the nearest mountain name close to the top.
        cand = [(np.hypot(n["x"] - x, n["y"] - y), n) for n in names]
        same = [c for c in cand if r["osm_name"] and norm(c[1]["name"]) == norm(r["osm_name"]) and c[0] < a.name_m]
        near = [c for c in cand if c[0] < 500 and c[1]["generic"] not in NO_ELEV_GENERICS]
        hit = min(same or near, key=lambda c: c[0], default=None)
        status = []
        if hit:
            r.update(name=hit[1]["name"], name_src="CGNDB", cgndb_id=hit[1]["id"], cgndb_dist_m=round(hit[0]))
            used.add(hit[1]["name"])
            if r["osm_name"] and norm(hit[1]["name"]) != norm(r["osm_name"]):
                status.append(f"name differs (OSM '{r['osm_name']}')")
        else:
            r.update(name=r["osm_name"], name_src="OSM" if r["osm_name"] else "", cgndb_id="", cgndb_dist_m=None)
        if r["dem_dist_m"] > a.agree_m:
            status.append(f"model summit {r['dem_dist_m']} m away")
        # The 30 m model cuts sharp tops: the OSM height may be higher by tens of metres, not lower.
        if osm_ele is not None and -25 <= osm_ele - r["dem_ele_m"] <= 150:
            r.update(ele_m=osm_ele, ele_src="OSM")
        else:
            r.update(ele_m=r["dem_ele_m"], ele_src="model")
            status.append(ele_note or f"OSM height {osm_ele:.0f} vs model {r['dem_ele_m']:.0f}")
        r["status"] = "; ".join(status) or "ok"
        rows.append(r)

    # Official names with no OSM summit: the highest prominent model summit near the name point.
    for n in names:
        if n["name"] in used or n["generic"] in NO_ELEV_GENERICS:
            continue
        d = np.hypot(px - n["x"], py - n["y"])
        ok = np.flatnonzero((d < a.snap_m) & (pp >= a.snap_prom))
        if not ok.size:
            continue
        k = int(ok[np.argmax(pz[ok])])
        used.add(n["name"])
        rows.append({"x": float(px[k]), "y": float(py[k]), "osm_id": None, "osm_name": "", "osm_ele_m": None,
                     "dem_ele_m": round(float(pz[k]), 1), "dem_dist_m": 0, "prominence_m": round(float(pp[k])),
                     "_k": k, "name": n["name"], "name_src": "CGNDB", "cgndb_id": n["id"],
                     "cgndb_dist_m": round(float(d[k])), "ele_m": round(float(pz[k]), 1), "ele_src": "model",
                     "status": f"no OSM summit; model summit {round(float(d[k]))} m from the name point"})

    named = {r["_k"] for r in rows}
    edge = a.edge_m / a.res
    high = []
    for k in np.flatnonzero(pp >= a.high_prom):
        if k in named or min((np.hypot(px[k] - r["x"], py[k] - r["y"]) for r in rows), default=1e9) < a.agree_m * 2:
            continue
        near_edge = min(pr[k], pc[k], h - 1 - pr[k], w - 1 - pc[k]) < edge
        high.append({"x": float(px[k]), "y": float(py[k]), "ele_m": round(float(pz[k]), 1),
                     "prominence_m": round(float(pp[k])), "edge": int(near_edge)})

    write(a.out, dst, rows, high, sorted(n["name"] for n in names if n["name"] not in used))
    flagged = [r for r in rows if r["status"] != "ok"]
    n_osm = sum(r["osm_id"] is not None for r in rows)
    print(f"peaks: {n_osm} OSM summits and {len(rows) - n_osm} official names snapped to the model; "
          f"{len(rows) - len(flagged)} ok, {len(flagged)} to look at; "
          f"{len(high)} unnamed high points (prominence >= {a.high_prom:.0f} m)")
    for r in flagged:
        print(f"  look: {r['name'] or r['osm_id']}: {r['status']}")


def write(path, srs, rows, high, unmatched):
    Path(path).unlink(missing_ok=True)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    specs = {
        "peaks": [("name", ogr.OFTString), ("name_src", ogr.OFTString), ("osm_id", ogr.OFTInteger64),
                  ("osm_name", ogr.OFTString), ("cgndb_id", ogr.OFTString), ("cgndb_dist_m", ogr.OFTInteger),
                  ("osm_ele_m", ogr.OFTReal), ("dem_ele_m", ogr.OFTReal), ("dem_dist_m", ogr.OFTInteger),
                  ("prominence_m", ogr.OFTInteger), ("ele_m", ogr.OFTReal), ("ele_src", ogr.OFTString),
                  ("status", ogr.OFTString)],
        "high_points": [("ele_m", ogr.OFTReal), ("prominence_m", ogr.OFTInteger), ("edge", ogr.OFTInteger)],
    }
    for name, recs in (("peaks", rows), ("high_points", high)):
        lyr = ds.CreateLayer(name, srs, ogr.wkbPoint)
        for f, t in specs[name]:
            lyr.CreateField(ogr.FieldDefn(f, t))
        for r in recs:
            ft = ogr.Feature(lyr.GetLayerDefn())
            g = ogr.Geometry(ogr.wkbPoint)
            g.AddPoint_2D(r["x"], r["y"])
            ft.SetGeometry(g)
            for f, _ in specs[name]:
                if r.get(f) is not None:
                    ft.SetField(f, r[f])
            lyr.CreateFeature(ft)
    meta = ds.CreateLayer("cgndb_unmatched", None, ogr.wkbNone)
    meta.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    for n in unmatched:
        ft = ogr.Feature(meta.GetLayerDefn())
        ft.SetField("name", n)
        meta.CreateFeature(ft)
    ds = None


if __name__ == "__main__":
    main()
