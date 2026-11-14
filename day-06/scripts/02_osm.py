"""Turn the Overpass download (raw-261109/osm.json) into map layers in EPSG:26911.

Writes derived/osm.gpkg with the layers:
- lakes (polygons: natural=water ways and multipolygon relations; intermittent = 1 for OSM intermittent=yes)
- streams (waterway=river|stream|canal; attribute kind)
- roads (highways for vehicles; attribute kind)
- trails (path, footway, track, bridleway)
- rail (railway=rail; attribute tunnel = 1 inside a tunnel)
- glaciers_osm (natural=glacier; kept for comparison only, these outlines have no date)
- boundary (the Alberta-British Columbia boundary, from raw-261109/osm_boundary.json)
"""
import json

from osgeo import ogr, osr
from sheet import CRS, DERIVED, RAW

ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "service", "motorway_link", "trunk_link", "primary_link", "secondary_link"}
TRAILS = {"path", "footway", "track", "bridleway", "steps"}

ogr.UseExceptions()
osr.UseExceptions()


def main():
    els = json.loads((RAW / "osm.json").read_text())["elements"]
    bnd = json.loads((RAW / "osm_boundary.json").read_text())["elements"]
    els += bnd
    bnd_ways = {e["id"] for e in bnd if e["type"] == "way"}
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in els if e["type"] == "node"}
    ways = {e["id"]: e for e in els if e["type"] == "way"}
    rels = [e for e in els if e["type"] == "relation"]

    wgs, utm = osr.SpatialReference(), osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    utm.SetFromUserInput(CRS)
    for s in (wgs, utm):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(wgs, utm)

    def line(w):
        g = ogr.Geometry(ogr.wkbLineString)
        for n in w["nodes"]:
            if n in nodes:
                g.AddPoint_2D(*nodes[n])
        return g

    def ring_poly(w):
        r = ogr.Geometry(ogr.wkbLinearRing)
        for n in w["nodes"]:
            if n in nodes:
                r.AddPoint_2D(*nodes[n])
        p = ogr.Geometry(ogr.wkbPolygon)
        p.AddGeometry(r)
        return p

    def rel_poly(rel):
        edges = ogr.Geometry(ogr.wkbMultiLineString)
        for m in rel["members"]:
            if m["type"] == "way" and m["ref"] in ways:
                edges.AddGeometry(line(ways[m["ref"]]))
        try:
            return ogr.BuildPolygonFromEdges(edges, 0, 1, 1e-7)
        except RuntimeError:
            return None

    out = DERIVED / "osm.gpkg"
    DERIVED.mkdir(parents=True, exist_ok=True)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(out))
    layers = {}

    def add(layer, geom, **attrs):
        if geom is None or geom.IsEmpty():
            return
        if layer not in layers:
            gtype = ogr.wkbMultiPolygon if layer in ("lakes", "glaciers_osm") else ogr.wkbMultiLineString
            lyr = ds.CreateLayer(layer, utm, gtype)
            lyr.CreateField(ogr.FieldDefn("osm_id", ogr.OFTInteger64))
            for k in ("name", "kind"):
                lyr.CreateField(ogr.FieldDefn(k, ogr.OFTString))
            lyr.CreateField(ogr.FieldDefn("tunnel", ogr.OFTInteger))
            # intermittent = 1: water only at times (OSM intermittent=yes). On this sheet that is the braid
            # plain of the Kicking Horse below Field: the whole channel belt, gravel bars included (11-13).
            lyr.CreateField(ogr.FieldDefn("intermittent", ogr.OFTInteger))
            layers[layer] = lyr
        lyr = layers[layer]
        g = geom.Clone()
        g.Transform(tr)
        g = ogr.ForceToMultiPolygon(g) if lyr.GetGeomType() == ogr.wkbMultiPolygon else ogr.ForceToMultiLineString(g)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(g)
        for k, v in attrs.items():
            f.SetField(k, v)
        lyr.CreateFeature(f)

    for w in sorted(ways.values(), key=lambda w: w["id"]):
        t = w.get("tags", {})
        base = {"osm_id": w["id"], "name": t.get("name", "")}
        closed = len(w["nodes"]) > 3 and w["nodes"][0] == w["nodes"][-1]
        if w["id"] in bnd_ways:
            add("boundary", line(w), kind="AB-BC", **base)
        elif t.get("natural") == "water" and closed:
            add("lakes", ring_poly(w), kind=t.get("water", ""), intermittent=int(t.get("intermittent") == "yes"), **base)
        elif t.get("natural") == "glacier" and closed:
            add("glaciers_osm", ring_poly(w), **base)
        elif t.get("waterway") in ("river", "stream", "canal"):
            add("streams", line(w), kind=t["waterway"], **base)
        elif t.get("highway") in ROADS:
            add("roads", line(w), kind=t["highway"], **base)
        elif t.get("highway") in TRAILS:
            add("trails", line(w), kind=t["highway"], **base)
        elif t.get("railway") == "rail":
            add("rail", line(w), kind=t.get("service", "main"), tunnel=int(t.get("tunnel") == "yes"), **base)
    for r in sorted(rels, key=lambda r: r["id"]):
        t = r.get("tags", {})
        if t.get("type") != "multipolygon":
            continue
        layer = "lakes" if t.get("natural") == "water" else "glaciers_osm" if t.get("natural") == "glacier" else None
        if layer:
            add(layer, rel_poly(r), osm_id=r["id"], name=t.get("name", ""), kind=t.get("water", ""),
                intermittent=int(t.get("intermittent") == "yes"))
    print({k: v.GetFeatureCount() for k, v in layers.items()})
    ds = None


if __name__ == "__main__":
    main()
