"""Map the ice of Sheet No. 16 from the scan: where its contours are printed in blue, not brown.

On the sheet, glaciers have no fill. Contours on ice are printed from the blue plate and contours
on rock and soil from the brown plate. So ice is where the local share of blue contour ink is high.

Steps, on the 10 m warped scan (derived/sheet16_26911.tif, cell average of the 600 ppi master):
1. Paper colour per channel from a smooth 80th percentile; optical density OD = -log10(I / paper).
2. Ink pixels: blue where OD_red exceeds OD_blue, brown where OD_blue exceeds OD_red. Black lettering
   and the red roads are left out.
3. Blue share = blue density / (blue + brown density), Gaussian smoothing of SIGMA pixels.
4. Ice = blue share above SHARE, dense blue ink nearby (MIN_BLUE), above MIN_ELEV_M, and not near an
   OSM lake or river (lakes are water-lined in blue on the sheet; rivers and gravel flats are blue).
   Lakes next to the 1985 ice are not masked: they formed under or at the ice since 1913.
5. Patches at a reviewed not-ice point are removed (data/not_ice.json: blue creeks on brown slopes,
   found by a check of every 1913 patch with no 1985 ice on the master scan, 11-10).
6. Repeated for a grid of SHARE and SIGMA values: the spread of the area is the method range.

Writes derived/ice1913.gpkg (layer ice1913, central settings), derived/ice1913_metrics.json
and out/quicklooks/ice1913_check.png (outline over the scan, for a visual check).
"""
import json
from pathlib import Path

import georef
import ink
import numpy as np
from osgeo import gdal, ogr, osr
from PIL import Image
from scipy import ndimage as ndi
from sheet import CRS, DERIVED, OUT, RAW

gdal.UseExceptions()
ogr.UseExceptions()

SHARES = (0.5, 0.6, 0.7)
SIGMAS = (8, 12, 16)  # pixels of 10 m
CENTRAL = (0.6, 12)
MIN_BLUE = 0.03       # smoothed blue-ink density: ice contours are dense, single blue creeks are not
MIN_ELEV_M = 1850.0   # Bow valley floor is 1700 to 1800 m here; 1913 snouts on the sheet end higher
MIN_AREA_KM2 = 0.1
NOT_ICE = json.loads((Path(__file__).resolve().parents[1] / "data" / "not_ice.json").read_text())["points"]
LAKE_BUFFER_PX = 16    # water-lining reaches about 100 m out from the shore, plus the 160 m georeferencing error
NEW_LAKE_PX = 30       # 300 m: lakes this close to the 1985 ice count as formed since 1913
RIVER_BUFFER_PX = 15   # rivers and braided flats are drawn in blue too


def grid_like(ds, src, resample="bilinear", burn=None, where=None):
    """A raster or vector source on the grid of ds."""
    gt, w, h = ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize
    bounds = [gt[0], gt[3] + h * gt[5], gt[0] + w * gt[1], gt[3]]
    if burn is None:
        return gdal.Warp("", str(src), format="MEM", dstSRS=CRS, outputBounds=bounds,
                         width=w, height=h, resampleAlg=resample).ReadAsArray().astype(float)
    m = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Byte)
    m.SetGeoTransform(gt)
    m.SetProjection(ds.GetProjection())
    v = ogr.Open(str(src))
    lyr = v.GetLayerByName("streams" if burn == "rivers" else burn)
    if burn == "rivers":
        lyr.SetAttributeFilter("kind = 'river'")
    elif where:
        lyr.SetAttributeFilter(where)
    gdal.RasterizeLayer(m, [1], lyr, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    return m.ReadAsArray().astype(bool)


def frame_mask(ds):
    """Inside the map frame (the four shifted corners), on the grid of ds."""
    gt = ds.GetGeoTransform()
    ring = ogr.Geometry(ogr.wkbLinearRing)
    corners = {k: (e, n) for (px, py, e, n), k in zip(georef.gcps(), georef.CORNER_PX, strict=True)}
    for k in ("NW", "NE", "SE", "SW", "NW"):
        ring.AddPoint_2D(*corners[k])
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    srs = osr.SpatialReference()
    srs.SetFromUserInput(CRS)
    mem = ogr.GetDriverByName("MEM").CreateDataSource("")
    lyr = mem.CreateLayer("f", srs, ogr.wkbPolygon)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(poly)
    lyr.CreateFeature(f)
    m = gdal.GetDriverByName("MEM").Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
    m.SetGeoTransform(gt)
    m.SetProjection(ds.GetProjection())
    gdal.RasterizeLayer(m, [1], lyr, burn_values=[1])
    return ndi.binary_erosion(m.ReadAsArray().astype(bool), iterations=3)


def ink_planes(rgb):
    p = ink.plates(ink.paper_and_od(rgb)[1])
    return p["blue"], p["brown"]


def drop_reviewed(mask, ds):
    """Remove the patches that contain a reviewed not-ice point (data/not_ice.json)."""
    gt = ds.GetGeoTransform()
    lbl, _ = ndi.label(mask)
    for p in NOT_ICE:
        c, r = int((p["E"] - gt[0]) / gt[1]), int((p["N"] - gt[3]) / gt[5])
        if 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and lbl[r, c]:
            mask = mask & (lbl != lbl[r, c])
    return mask


def smooth(blue, brown, sigma):
    """Blue and brown ink density, smoothed over sigma pixels."""
    return ndi.gaussian_filter(blue.astype(float), sigma), ndi.gaussian_filter(brown.astype(float), sigma)


def ice_mask(bd, sd, allowed, share):
    tot = bd + sd
    m = (bd / np.maximum(tot, 1e-6) > share) & (bd > MIN_BLUE) & allowed
    m = ndi.binary_opening(ndi.binary_closing(m, iterations=3), iterations=2)
    m = ndi.binary_fill_holes(m) & allowed
    lbl, n = ndi.label(m)
    sizes = ndi.sum(m, lbl, range(1, n + 1)) * 1e-4  # km2 at 10 m
    return np.isin(lbl, 1 + np.flatnonzero(sizes >= MIN_AREA_KM2))


def write_polygons(mask, ds, path):
    m = gdal.GetDriverByName("MEM").Create("", ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte)
    m.SetGeoTransform(ds.GetGeoTransform())
    m.SetProjection(ds.GetProjection())
    m.GetRasterBand(1).WriteArray(mask.astype(np.uint8))
    srs = osr.SpatialReference()
    srs.SetFromUserInput(CRS)
    if path.exists():
        path.unlink()
    out = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    lyr = out.CreateLayer("ice1913", srs, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(m.GetRasterBand(1), m.GetRasterBand(1), lyr, 0)
    out = None


def main():
    ds = gdal.Open(str(DERIVED / "sheet16_26911.tif"))
    rgb = ds.ReadAsArray()[:3].astype(float)
    blue, brown = ink_planes(rgb)
    dem = grid_like(ds, RAW / "mrdem30_window.tif")
    lakes = grid_like(ds, DERIVED / "osm.gpkg", burn="lakes")
    # Lakes that formed since 1913 lay under the ice then (Takakkaw Lake below the Daly Glacier).
    # A lake within NEW_LAKE_PX of the 1985 ice is taken to be one of these and is not masked.
    ice85 = ndi.binary_dilation(grid_like(ds, RAW / "glaciers_1984_2021.gpkg", burn="glaciers",
                                          where="keep = 'YES' AND year = 1985"), iterations=NEW_LAKE_PX)
    lbl, _ = ndi.label(lakes)
    new = np.unique(lbl[ice85 & lakes])
    lakes &= ~np.isin(lbl, new[new > 0])
    lakes = ndi.binary_dilation(lakes, iterations=LAKE_BUFFER_PX)
    rivers = ndi.binary_dilation(grid_like(ds, DERIVED / "osm.gpkg", burn="rivers"), iterations=RIVER_BUFFER_PX)
    allowed = frame_mask(ds) & ~lakes & ~rivers & (dem > MIN_ELEV_M)

    runs = {}
    for sigma in SIGMAS:
        bd, sd = smooth(blue, brown, sigma)
        for share in SHARES:
            m = drop_reviewed(ice_mask(bd, sd, allowed, share), ds)
            runs[f"share{share}_sigma{sigma}"] = round(float(m.sum()) * 1e-4, 2)
            if (share, sigma) == CENTRAL:
                central = m
    areas = sorted(runs.values())
    metrics = {
        "area_km2_central": runs[f"share{CENTRAL[0]}_sigma{CENTRAL[1]}"],
        "area_km2_range": [areas[0], areas[-1]],
        "runs": runs,
        "settings": {"shares": SHARES, "sigmas_px": SIGMAS, "central": CENTRAL, "min_blue": MIN_BLUE, "lake_buffer_px": LAKE_BUFFER_PX, "new_lake_px": NEW_LAKE_PX, "river_buffer_px": RIVER_BUFFER_PX,
                     "min_elev_m": MIN_ELEV_M, "min_area_km2": MIN_AREA_KM2},
    }
    write_polygons(central, ds, DERIVED / "ice1913.gpkg")
    (DERIVED / "ice1913_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    # Visual check: the central outline in red over the scan.
    q = OUT / "quicklooks"
    q.mkdir(parents=True, exist_ok=True)
    img = np.moveaxis(rgb, 0, -1).astype(np.uint8).copy()
    edge = central & ~ndi.binary_erosion(central, iterations=2)
    img[edge] = (220, 0, 0)
    Image.fromarray(img).save(q / "ice1913_check.png")
    print(json.dumps({k: metrics[k] for k in ("area_km2_central", "area_km2_range")}))


if __name__ == "__main__":
    main()
