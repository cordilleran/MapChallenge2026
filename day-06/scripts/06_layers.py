"""Final map layers in derived/map.gpkg, all clipped to the map frame.

- contours: 100 ft contours with on_ice = 1 where they cross the 2021 ice (printed blue, as the
  1925 sheet prints contours on ice) and 0 elsewhere (printed brown); idx = 1,000 ft index contour.
- ice2021, ice1985, ice1913 (outlines), forefield (1913 ice minus 2021 ice: the ground ice has left).
  ice2021 is not drawn (the contours turn blue on it); ice1985 and ice1913 are drawn as ghost lines.
- contours_m: the same for the metric set (25 m, index 250 m).
- peaks: summits from peaks.py inside the frame, with ele_ft and ele_m for the label; official = 1
  for a CGNDB name (other OSM names, often climbers' labels, are printed as a height only); show_ele = 1
  where the height is OSM's and agrees with the terrain model (the 30 m model cuts sharp tops, so its
  own heights are not printed).
- high_points: unnamed summits of 150 m prominence or more, height from the model (printed smaller).
- lake_elev: surface height of each lake of 0.05 km² or more (median of the terrain model inside it),
  printed in the lake as on the sheet.
- names: CGNDB names of glaciers, lakes and rivers, and of mountains that are not in peaks. Glacier
  names are moved inside the 2021 ice (at least ICE_INSET_M from its edge), nearest the CGNDB point,
  and carry angle: the direction of the contours there (degrees clockwise, for the label), as the
  sheet letters its glaciers across the slope. Rivers drawn as OSM lines are left out here.
- stream_names: for each CGNDB river or creek, a stretch of the OSM line of the same name, up to
  STREAM_LABEL_M long and centred where the line passes nearest the CGNDB point; the name is lettered
  along it, as on the sheet.
- features: what the sheet names besides summits, lakes and creeks (11-13): falls (CGNDB names, placed on
  the nearest OSM waterfall within SNAP_FALLS_M), passes (CGNDB names with Pass or Col, placed on the OSM
  saddle; height from OSM where given, else the terrain model, ele_src says which), and huts and lodges
  (OSM tourism=alpine_hut, wilderness_hut, chalet, hotel or hostel, and historic buildings).
- graticule: 5-minute lines of latitude and longitude (NAD83) inside the frame, for the full sheet.
"""
import json

import numpy as np
from osgeo import gdal, ogr, osr
from scipy import ndimage as ndi
from sheet import CRS, DERIVED, FT, LAT_N, LAT_S, LON_E, LON_W, RAW

gdal.UseExceptions()

ogr.UseExceptions()
osr.UseExceptions()
SIMPLIFY_M = 15  # display tolerance for the ice outlines
SMOOTH_M = 25    # closing (grow then shrink) of the 1913 outline before simplifying
MIN_LAKE_KM2 = 0.05
ICE_INSET_M = 120      # glacier names sit at least this far inside the 2021 ice
ICE_SEARCH_M = 2500    # and in a patch of 2021 ice no farther than this from the CGNDB point
GLACIER_GAP_M = 450    # glacier names closer than this across their lettering are stepped apart
GLACIER_LEN_M = 2200   # (about the length of a spaced glacier name at 1:62,500)
GLACIER_EDGE_M = 200   # both ends of a glacier name stay this far inside the frame (labels keep 2.5 mm, 156 m)
GLACIER_CHAR_M = 100   # length of one spaced letter of a glacier name at 1:62,500
GLACIER_STEP_M = 50    # grid for searching the ice for a place where the whole name fits
SLOPE_SIGMA_PX = 25    # smoothing of the terrain (10 m cells) for the direction of the contours
STREAM_LABEL_M = 3000  # length of the stretch of creek a name is lettered along
STREAM_NEAR_M = 1000   # the stretch is taken from a line of that name this close to the CGNDB point
STREAM_MIN_M = 600     # shorter than this, the name stays a point label
KINDS = {"MTN": "mountain", "GLAC": "glacier", "LAKE": "lake", "RIV": "river"}  # falls and passes: features
SNAP_FALLS_M = 600     # a CGNDB falls name moves to the nearest OSM waterfall this close
SNAP_PASS_M = 1000     # a CGNDB pass moves to the OSM saddle of the same name, or the nearest this close
HUTS = ("alpine_hut", "wilderness_hut", "chalet", "hotel", "hostel")


def one(path, layer=None):
    ds = ogr.Open(str(path))
    lyr = ds.GetLayerByName(layer) if layer else ds.GetLayer(0)
    u = ogr.Geometry(ogr.wkbMultiPolygon)
    for f in lyr:
        u = u.Union(f.GetGeometryRef().MakeValid())
    return u


def cells_inside(geom, dem, z):
    """Valid values of the raster z (grid of dem) at the cells whose centres fall inside geom."""
    mem = gdal.GetDriverByName("MEM").Create("", dem.RasterXSize, dem.RasterYSize, 1, gdal.GDT_Byte)
    mem.SetGeoTransform(dem.GetGeoTransform())
    mem.SetProjection(dem.GetProjection())
    src = gdal.GetDriverByName("MEM").Create("", 0, 0, 0, gdal.GDT_Unknown)  # keep it: the layer dies with it
    lyr = src.CreateLayer("g", dem.GetSpatialRef(), ogr.wkbPolygon)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(geom)
    lyr.CreateFeature(f)
    gdal.RasterizeLayer(mem, [1], lyr, burn_values=[1])
    inside = mem.GetRasterBand(1).ReadAsArray().astype(bool)
    nodata = dem.GetRasterBand(1).GetNoDataValue()
    return z[inside & (z != nodata)] if nodata is not None else z[inside]


def parts(g):
    """Polygons or lines of a geometry, as a list of clones."""
    n = g.GetGeometryCount()
    if g.GetGeometryType() in (ogr.wkbMultiPolygon, ogr.wkbMultiLineString, ogr.wkbGeometryCollection) and n:
        return [p for i in range(n) for p in parts(g.GetGeometryRef(i))]
    return [g.Clone()] if not g.IsEmpty() else []


def chain(lines):
    """Join lines that share an end point into longer lines (OSM ways of one creek)."""
    segs = [np.array(ln.GetPoints())[:, :2] for ln in lines if ln.GetPointCount() > 1]
    joined = True
    while joined:
        joined = False
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                for x, y in ((a, b), (a[::-1], b), (a, b[::-1]), (a[::-1], b[::-1])):
                    if np.allclose(x[-1], y[0], atol=0.5):
                        segs[i], joined = np.vstack([x, y[1:]]), True
                        del segs[j]
                        break
                if joined:
                    break
            if joined:
                break
    return segs


def stretch(xy, px, py, length):
    """The part of polyline xy of the given length, centred where it passes nearest (px, py)."""
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    t = d[np.argmin(np.hypot(xy[:, 0] - px, xy[:, 1] - py))]
    lo = min(max(0, t - length / 2), max(0, d[-1] - length))
    hi = min(d[-1], lo + length)
    keep = (d > lo) & (d < hi)
    pts = np.vstack([[np.interp(lo, d, xy[:, 0]), np.interp(lo, d, xy[:, 1])], xy[keep],
                     [np.interp(hi, d, xy[:, 0]), np.interp(hi, d, xy[:, 1])]])
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts:
        g.AddPoint_2D(float(x), float(y))
    return g


def crowded(q, other, ang):
    """True if a name lettered at q (angle clockwise) would lie alongside the one at other: closer than
    GLACIER_GAP_M across the lettering and GLACIER_LEN_M along it."""
    t = np.radians(-ang)
    dx, dy = q.GetX() - other.GetX(), q.GetY() - other.GetY()
    along = abs(dx * np.cos(t) + dy * np.sin(t))
    across = abs(-dx * np.sin(t) + dy * np.cos(t))
    return across < GLACIER_GAP_M and along < GLACIER_LEN_M


def contour_angle(x, y, slope):
    """Angle of the contours at (x, y), clockwise from east as QGIS turns labels, kept upright."""
    gx, gy, gt = slope
    c, r = int((x - gt[0]) / gt[1]), int((y - gt[3]) / gt[5])
    # Uphill direction, east and north components (rows run south), then the contour across it.
    a = np.degrees(np.arctan2(-gy[r, c], gx[r, c])) + 90  # counter-clockwise from east
    return float(-((a + 90) % 180 - 90))


def point(x, y):
    q = ogr.Geometry(ogr.wkbPoint)
    q.AddPoint_2D(float(x), float(y))
    return q


def fits(q, ang, half, inside):
    """Both ends of a name `half` metres either side of q, at angle ang, lie inside `inside`."""
    t = np.radians(-ang)
    dx, dy = half * np.cos(t), half * np.sin(t)
    return all(inside.Contains(point(q.GetX() + s * dx, q.GetY() + s * dy)) for s in (-1, 1))


def glacier_spot(p, ice, slope, inside, half):
    """Where to letter a glacier: inside the 2021 ice near p, lettered along the contours there, with
    the whole name (half its length either side) inside the map frame. The nearest such spot to p."""
    near = [g for g in ice if g.Distance(p) < ICE_SEARCH_M]
    if not near:
        return None
    best = min(near, key=lambda g: (not g.Contains(p), g.Distance(p)))
    inner = best.Buffer(-ICE_INSET_M)
    if inner.IsEmpty():
        inner = best
    if inner.Contains(p) and fits(p, a := contour_angle(p.GetX(), p.GetY(), slope), half, inside):
        return p.Clone(), a
    x0, x1, y0, y1 = inner.GetEnvelope()
    cands = []
    for x in np.arange(x0, x1, GLACIER_STEP_M):
        for y in np.arange(y0, y1, GLACIER_STEP_M):
            q = point(x, y)
            if inner.Contains(q):
                cands.append((q.Distance(p), q))
    cands = [q for _, q in sorted(cands, key=lambda c: c[0])]
    angles = [contour_angle(q.GetX(), q.GetY(), slope) for q in cands]
    # Along the contours if the name fits anywhere in the ice; if not (ice against the frame), turn it
    # by the least amount that lets it fit.
    for turn in sorted(range(-90, 91, 10), key=abs):
        for q, a in zip(cands, angles, strict=True):
            b = (a + turn + 90) % 180 - 90
            if fits(q, b, half, inside):
                return q, b
    return None


def main():
    utm = osr.SpatialReference()
    utm.SetFromUserInput(CRS)
    utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    frame = one(DERIVED / "modern.gpkg", "frame")
    ice21 = one(DERIVED / "modern.gpkg", "ice2021")
    ice85 = one(DERIVED / "modern.gpkg", "ice1985")
    ice13 = one(DERIVED / "ice1913.gpkg").Intersection(frame)

    path = DERIVED / "map.gpkg"
    path.unlink(missing_ok=True)
    out = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))

    def poly_layer(name, geom):
        lyr = out.CreateLayer(name, utm, ogr.wkbMultiPolygon)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.ForceToMultiPolygon(geom))
        lyr.CreateFeature(f)

    # For display only: the outlines follow 10 m (1913) and 30 m (2021) pixels, which a dotted
    # line shows as stair steps. Areas in compare_metrics.json use the unsimplified outlines.
    show21 = ice21.SimplifyPreserveTopology(SIMPLIFY_M)
    show13 = ice13.Buffer(SMOOTH_M).Buffer(-SMOOTH_M).SimplifyPreserveTopology(SIMPLIFY_M).Intersection(frame)
    poly_layer("frame", frame)
    poly_layer("ice2021", show21)
    poly_layer("ice1985", ice85.SimplifyPreserveTopology(SIMPLIFY_M))
    poly_layer("ice1913", show13)
    poly_layer("forefield", show13.Difference(show21))

    # Contours split at the 2021 ice margin, in feet and in metres.
    src = ogr.Open(str(DERIVED / "contours.gpkg"))
    prep = show21.Buffer(0)  # split at the drawn margin so blue contours meet the dotted line
    for layer, field in (("contours", "elev_ft"), ("contours_m", "elev_m")):
        cl = out.CreateLayer(layer, utm, ogr.wkbMultiLineString)
        for name, typ in ((field, ogr.OFTReal), ("idx", ogr.OFTInteger), ("on_ice", ogr.OFTInteger)):
            cl.CreateField(ogr.FieldDefn(name, typ))
        for f in src.GetLayerByName(layer):
            g = f.GetGeometryRef().Intersection(frame)
            if g.IsEmpty():
                continue
            pieces = ((1, g.Intersection(prep)), (0, g.Difference(prep))) if g.Intersects(prep) else ((0, g),)
            for on_ice, p in pieces:
                if p.IsEmpty() or p.GetDimension() != 1:
                    continue
                nf = ogr.Feature(cl.GetLayerDefn())
                nf.SetGeometry(ogr.ForceToMultiLineString(p))
                nf.SetField(field, f.GetField(field))
                nf.SetField("idx", f.GetField("idx"))
                nf.SetField("on_ice", on_ice)
                cl.CreateFeature(nf)

    # Peaks and high points (peaks.py), inside the frame.
    pk = ogr.Open(str(DERIVED / "peaks.gpkg"))
    peak_names = set()
    for layer in ("peaks", "high_points"):
        pl = out.CreateLayer(layer, utm, ogr.wkbPoint)
        fields = [("name", ogr.OFTString), ("official", ogr.OFTInteger), ("status", ogr.OFTString)] \
            if layer == "peaks" else []
        fields += [("ele_m", ogr.OFTInteger), ("ele_ft", ogr.OFTInteger), ("show_ele", ogr.OFTInteger)]
        for name, typ in fields:
            pl.CreateField(ogr.FieldDefn(name, typ))
        for f in pk.GetLayerByName(layer):
            g = f.GetGeometryRef()
            if not frame.Contains(g) or (layer == "high_points" and f["edge"]):
                continue
            nf = ogr.Feature(pl.GetLayerDefn())
            nf.SetGeometry(g.Clone())
            if layer == "peaks":
                nf.SetField("name", f["name"])
                nf.SetField("status", f["status"])
                nf.SetField("official", int(f["name_src"] == "CGNDB"))
                peak_names.add(f["name"])
            nf.SetField("ele_m", int(f["ele_m"] + 0.5))
            nf.SetField("ele_ft", int(f["ele_m"] / FT + 0.5))
            nf.SetField("show_ele", int(layer == "high_points" or f["ele_src"] == "OSM"))
            pl.CreateFeature(nf)

    # Lake surface heights, as printed in the lakes of the sheet.
    dem = gdal.Open(str(DERIVED / "terrain_10m.tif"))
    z = dem.GetRasterBand(1).ReadAsArray()
    ll = out.CreateLayer("lake_elev", utm, ogr.wkbPoint)
    for name, typ in (("ele_m", ogr.OFTInteger), ("ele_ft", ogr.OFTInteger)):
        ll.CreateField(ogr.FieldDefn(name, typ))
    lk = ogr.Open(str(DERIVED / "osm.gpkg"))
    for f in lk.GetLayerByName("lakes"):
        if f["intermittent"] and f["kind"] == "river":
            continue  # a braid plain, drawn as gravel flats: no water surface to give a height to
        g = f.GetGeometryRef().Intersection(frame)
        if g.IsEmpty() or g.GetArea() < MIN_LAKE_KM2 * 1e6:
            continue
        vals = cells_inside(g, dem, z)
        if not vals.size:
            continue
        m = float(np.median(vals))
        nf = ogr.Feature(ll.GetLayerDefn())
        nf.SetGeometry(g.PointOnSurface())
        nf.SetField("ele_m", int(m + 0.5))
        nf.SetField("ele_ft", int(m / FT + 0.5))
        ll.CreateFeature(nf)

    # Names.
    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(wgs, utm)
    nl = out.CreateLayer("names", utm, ogr.wkbPoint)
    for name in ("name", "kind"):
        nl.CreateField(ogr.FieldDefn(name, ogr.OFTString))
    nl.CreateField(ogr.FieldDefn("angle", ogr.OFTReal))
    sl = out.CreateLayer("stream_names", utm, ogr.wkbLineString)
    sl.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    ice = parts(one(DERIVED / "modern.gpkg", "ice2021").Intersection(frame))
    zs = ndi.gaussian_filter(z.astype(float), SLOPE_SIGMA_PX)
    gy, gx = np.gradient(zs)
    slope = (gx, gy, dem.GetGeoTransform())
    inside = frame.Buffer(-GLACIER_EDGE_M)  # where glacier names may reach
    osm = ogr.Open(str(DERIVED / "osm.gpkg"))
    streams = {}
    for f in osm.GetLayerByName("streams"):
        if f["name"]:
            streams.setdefault(f["name"], []).extend(parts(f.GetGeometryRef().Intersection(frame)))
    seen, moved, placed = set(), [], []
    for it in sorted(json.loads((RAW / "cgndb.json").read_text())["items"], key=lambda i: i["id"]):
        kind = KINDS.get(it["concise"]["code"])
        if not kind or (it["name"], kind) in seen or (kind == "mountain" and it["name"] in peak_names):
            continue
        p = ogr.Geometry(ogr.wkbPoint)
        p.AddPoint_2D(it["longitude"], it["latitude"])
        p.Transform(tr)
        if not frame.Contains(p):
            continue
        seen.add((it["name"], kind))
        if kind == "river" and streams.get(it["name"]):
            # The longest joined line of that name within STREAM_NEAR_M of the point: braids and
            # short side channels carry the name too.
            dist = [(np.min(np.hypot(a[:, 0] - p.GetX(), a[:, 1] - p.GetY())), a) for a in chain(streams[it["name"]])]
            near = [a for d, a in dist if d < STREAM_NEAR_M] or [min(dist, key=lambda t: t[0])[1]]
            xy = max(near, key=lambda a: np.hypot(*np.diff(a, axis=0).T).sum())
            g = stretch(xy, p.GetX(), p.GetY(), STREAM_LABEL_M)
            if g.Length() >= STREAM_MIN_M:
                sf = ogr.Feature(sl.GetLayerDefn())
                sf.SetGeometry(g)
                sf.SetField("name", it["name"])
                sl.CreateFeature(sf)
                continue
        nf = ogr.Feature(nl.GetLayerDefn())
        if kind == "glacier":
            half = len(it["name"]) * GLACIER_CHAR_M / 2
            spot = glacier_spot(p, ice, slope, inside, half)
            if spot:
                q, ang = spot
                # Two names close together would print as parallel lines touching: step this one
                # away from the other, across its lettering, if it stays in the ice.
                t = np.radians(-ang + 90)  # across the lettering (angle is clockwise)
                for k in (0, 1, -1, 2, -2, 3, -3):
                    r = ogr.Geometry(ogr.wkbPoint)
                    r.AddPoint_2D(q.GetX() + k * GLACIER_GAP_M * np.cos(t), q.GetY() + k * GLACIER_GAP_M * np.sin(t))
                    if not any(crowded(r, o, ang) for o in placed) and (k == 0 or (any(g.Contains(r) for g in ice)
                                                                                 and fits(r, ang, half, inside))):
                        q = r
                        break
                placed.append(q)
                moved.append(round(q.Distance(p)))
                p = q
                nf.SetField("angle", round(ang, 1))
        nf.SetGeometry(p)
        nf.SetField("name", it["name"])
        nf.SetField("kind", kind)
        nl.CreateFeature(nf)
    print(f"glacier names moved into the 2021 ice by {sorted(moved)} m")

    # Falls, passes, huts and lodges.
    fl = out.CreateLayer("features", utm, ogr.wkbPoint)
    for name, typ in (("name", ogr.OFTString), ("kind", ogr.OFTString), ("ele_m", ogr.OFTInteger),
                      ("ele_ft", ogr.OFTInteger), ("ele_src", ogr.OFTString)):
        fl.CreateField(ogr.FieldDefn(name, typ))
    extras = json.loads((RAW / "osm_extras.json").read_text())["elements"]

    def pt(lon, lat):
        q = ogr.Geometry(ogr.wkbPoint)
        q.AddPoint_2D(lon, lat)
        q.Transform(tr)
        return q

    def ll(e):
        c = e.get("center", e)
        return pt(c["lon"], c["lat"])

    falls = [ll(e) for e in extras if e["type"] == "node"
             and "waterfall" in (e["tags"].get("waterway"), e["tags"].get("natural"))]
    saddles = [(e["tags"].get("name", ""), e["tags"].get("ele"), ll(e)) for e in extras if e["type"] == "node"
               and (e["tags"].get("natural") == "saddle" or e["tags"].get("mountain_pass") == "yes")]
    gt = dem.GetGeoTransform()

    def dem_at(q):
        c, r = int((q.GetX() - gt[0]) / gt[1]), int((q.GetY() - gt[3]) / gt[5])
        return float(z[r, c])

    def add_feature(q, name, kind, ele=None, src=""):
        nf = ogr.Feature(fl.GetLayerDefn())
        nf.SetGeometry(q)
        nf.SetField("name", name)
        nf.SetField("kind", kind)
        if ele is not None:
            nf.SetField("ele_m", int(ele + 0.5))
            nf.SetField("ele_ft", int(ele / FT + 0.5))
            nf.SetField("ele_src", src)
        fl.CreateFeature(nf)

    done = set()
    counts = {"falls": 0, "falls snapped": 0, "pass": 0, "hut": 0}
    for it in sorted(json.loads((RAW / "cgndb.json").read_text())["items"], key=lambda i: i["id"]):
        code, name = it["concise"]["code"], it["name"]
        is_pass = code == "VALL" and (" Pass" in name or " Col" in name)
        if (code != "FALL" and not is_pass) or name in done:
            continue
        q = pt(it["longitude"], it["latitude"])
        if not frame.Contains(q):
            continue
        done.add(name)
        if code == "FALL":
            near = min(falls, key=q.Distance, default=None)
            if near is not None and q.Distance(near) < SNAP_FALLS_M:
                q = near
                counts["falls snapped"] += 1
            add_feature(q, name, "falls")
            counts["falls"] += 1
            continue
        same = [s for s in saddles if s[0] == name] or [s for s in saddles if q.Distance(s[2]) < SNAP_PASS_M]
        ele, src = None, "model"
        if same:
            _, e, q = min(same, key=lambda s: q.Distance(s[2]))
            try:
                ele, src = float(e), "OSM"
            except (TypeError, ValueError):
                pass
        add_feature(q, name, "pass", dem_at(q) if ele is None else ele, src)
        counts["pass"] += 1
    for e in extras:
        t = e["tags"]
        if not t.get("name") or not (t.get("tourism") in HUTS or (t.get("historic") and t.get("building"))):
            continue
        q = ll(e)
        if frame.Contains(q):
            add_feature(q, t["name"], "hut")
            counts["hut"] += 1
    print("features:", counts)

    # A 5-minute graticule in modern coordinates (NAD83), clipped to the frame. The frame itself is the
    # sheet's (its corners read as NAD27, plus the mean shift), so it sits about 120 m west and 115 m
    # south of the modern lines of the same value; the 116°15' meridian of the east edge falls outside.
    nad83 = osr.SpatialReference()
    nad83.ImportFromEPSG(4269)
    nad83.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_utm = osr.CoordinateTransformation(nad83, utm)
    gl = out.CreateLayer("graticule", utm, ogr.wkbLineString)
    gl.CreateField(ogr.FieldDefn("axis", ogr.OFTString))
    gl.CreateField(ogr.FieldDefn("value", ogr.OFTReal))
    w, e, so, n = LON_W - 0.05, LON_E + 0.05, LAT_S - 0.05, LAT_N + 0.05
    step = 5 / 60
    lines = [("lat", v, [(x, v) for x in np.linspace(w, e, 50)]) for v in np.arange(np.ceil(so / step), n / step) * step]
    lines += [("lon", v, [(v, y) for y in np.linspace(so, n, 50)]) for v in np.arange(np.ceil(w / step), e / step) * step]
    for axis, v, pts in lines:
        ln = ogr.Geometry(ogr.wkbLineString)
        for x, y in pts:
            ln.AddPoint_2D(float(x), float(y))
        ln.Transform(to_utm)
        g = ln.Intersection(frame)
        for piece in parts(g):
            gf = ogr.Feature(gl.GetLayerDefn())
            gf.SetGeometry(piece)
            gf.SetField("axis", axis)
            gf.SetField("value", round(float(v), 6))
            gl.CreateFeature(gf)
    print({out.GetLayer(i).GetName(): out.GetLayer(i).GetFeatureCount() for i in range(out.GetLayerCount())})
    out = None


if __name__ == "__main__":
    main()
