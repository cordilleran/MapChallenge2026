"""Compare the 1913 ice from the sheet with the dated satellite outlines, inside the map frame.

- Modern ice: Bevington and Menounos (2022) outlines, keep = 'YES', for 1985 and 2021
  (the first full year in this window and the last year of the record).
- Check: the share of 1985 ice that lies inside the 1913 outline. Glaciers here have shrunk
  since the Little Ice Age, so a sound 1913 outline should contain nearly all of the 1985 ice.
  A low share would point to missed ice in the 1913 mapping or to a georeferencing shift.

Writes derived/modern.gpkg (layers ice1985, ice2021, frame; clipped to the frame)
and derived/compare_metrics.json.
"""
import json

import georef
from osgeo import ogr, osr
from sheet import CRS, DERIVED, RAW

ogr.UseExceptions()
osr.UseExceptions()


def frame():
    ring = ogr.Geometry(ogr.wkbLinearRing)
    c = {k: (e, n) for (px, py, e, n), k in zip(georef.gcps(), georef.CORNER_PX, strict=True)}
    for k in ("NW", "NE", "SE", "SW", "NW"):
        ring.AddPoint_2D(*c[k])
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(ring)
    return p


def union_year(year, utm):
    src = ogr.Open(str(RAW / "glaciers_1984_2021.gpkg"))
    lyr = src.GetLayerByName("glaciers")
    lyr.SetAttributeFilter(f"keep = 'YES' AND year = {year}")
    tr = osr.CoordinateTransformation(lyr.GetSpatialRef(), utm)
    u = ogr.Geometry(ogr.wkbMultiPolygon)
    for f in lyr:
        g = f.GetGeometryRef().Clone()
        g.Transform(tr)
        u = u.Union(g.MakeValid())
    return u


def ice1913():
    ds = ogr.Open(str(DERIVED / "ice1913.gpkg"))  # keep the source open while reading its layer
    lyr = ds.GetLayer(0)
    u = ogr.Geometry(ogr.wkbMultiPolygon)
    for f in lyr:
        u = u.Union(f.GetGeometryRef())
    return u


def main():
    utm = osr.SpatialReference()
    utm.SetFromUserInput(CRS)
    utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    fr = frame()
    old = ice1913().Intersection(fr)
    (DERIVED / "modern.gpkg").unlink(missing_ok=True)
    out = ogr.GetDriverByName("GPKG").CreateDataSource(str(DERIVED / "modern.gpkg"))
    metrics = {"area_km2": {"1913": round(old.GetArea() / 1e6, 2)}}
    for name, geom in [("frame", fr)] + [(f"ice{y}", union_year(y, utm).Intersection(fr)) for y in (1985, 2021)]:
        lyr = out.CreateLayer(name, utm, ogr.wkbMultiPolygon)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.ForceToMultiPolygon(geom))
        lyr.CreateFeature(f)
        if name != "frame":
            metrics["area_km2"][name[3:]] = round(geom.GetArea() / 1e6, 2)
            if name == "ice1985":
                metrics["share_1985_inside_1913"] = round(geom.Intersection(old).GetArea() / geom.GetArea(), 3)
    out = None
    a = metrics["area_km2"]
    rng = json.loads((DERIVED / "ice1913_metrics.json").read_text())["area_km2_range"]
    metrics["area_1913_range_km2"] = rng
    metrics["loss_1913_2021_pct"] = round(100 * (1 - a["2021"] / a["1913"]), 1)
    metrics["loss_1913_2021_pct_range"] = sorted(round(100 * (1 - a["2021"] / r), 1) for r in rng)
    metrics["loss_1985_2021_pct"] = round(100 * (1 - a["2021"] / a["1985"]), 1)
    (DERIVED / "compare_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
