"""Render the Day 6 map with QGIS (headless): the 2021 terrain and ice in the style of Sheet No. 16.

This script is the one source of truth for the style. It builds the layers and symbols in code,
saves each layer style as a QML file in day-06/styles/ (feet) and styles/metric/ (the QGIS style
kit), and exports, in feet as on the sheet and in metres (suffix _m):
- out/day06_sheet[_m].png   the full sheet: title, map, collar, references (and _zoom at 400 dpi)
- out/day06_modern[_m].png  the map frame only (for the comparison slider)
- out/day06_scan.png        the georeferenced 1925 scan, same frame and size (07b colour-matches it)

Heights are printed as on the sheet: summit names in capitals over their height, unofficial
summits and high points as a height only, lake surface heights in the lake, index contours labelled.

Run with the system Python and QGIS:  PYTHONPATH=/usr/share/qgis/python python3 07_render.py
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsGeometryGeneratorSymbolLayer,
    QgsInvertedPolygonRenderer,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsNullSymbolRenderer,
    QgsPalLayerSettings,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsRasterDataProvider,
    QgsRasterLayer,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from sheet import DERIVED, INK, LAT_N, LAT_S, LON_E, LON_W, OUT

STYLES = OUT.parent / "styles"
# A transverse Mercator centred on the sheet, so the meridians of the frame stand nearly upright.
TM = "+proj=tmerc +lat_0=51.5 +lon_0=-116.3908 +k=1 +x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs"
SCALE = 62500
DPI = 200
ZOOM_DPI = 400  # the full sheet again, for the page's zoomed view
LABEL_MARGIN_MM = 2.5  # no label closer than this to the map edge (156 m at 1:62,500)

SERIF, SANS = "EB Garamond", "Nimbus Sans"


def line(color, width, dash=None, cap=Qt.PenCapStyle.RoundCap):
    s = QgsSimpleLineSymbolLayer(QColor(color), width)
    s.setPenCapStyle(cap)
    if dash:
        s.setUseCustomDashPattern(True)
        s.setCustomDashVector(dash)
    return s


def symbol(*layers, kind=QgsLineSymbol):
    sym = kind()
    sym.deleteSymbolLayer(0)
    for lyr in layers:
        sym.appendSymbolLayer(lyr)
    return sym


def vlayer(name, layer, gpkg="map.gpkg", subset=None):
    # The filter goes in the URI: setSubsetString on an open GeoPackage layer made later opens of the
    # same file print "unable to open database file" (QGIS 4.2.3), although they drew.
    v = QgsVectorLayer(f"{DERIVED / gpkg}|layername={layer}" + (f"|subset={subset}" if subset else ""), name, "ogr")
    if not v.isValid():
        raise SystemExit(f"Cannot open {layer} in {gpkg}")
    return v


def rules(v, items):
    root = QgsRuleBasedRenderer.Rule(None)
    for label, expr, sym in items:
        root.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, expr, label))
    v.setRenderer(QgsRuleBasedRenderer(root))


def text(font, size, color, italic=False, caps=False, spacing=0.0, buffer=True):
    f = QFont(font)
    f.setItalic(italic)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    if caps:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
    t = QgsTextFormat()
    t.setFont(f)
    t.setSize(size)
    t.setColor(QColor(color))
    if buffer:
        b = QgsTextBufferSettings()
        b.setEnabled(True)
        b.setSize(0.6)
        b.setColor(QColor(INK["paper"]))
        b.setOpacity(0.85)
        t.setBuffer(b)
    return t


UNITS = {
    "ft": {"suffix": "", "contours": "contours", "field": "elev_ft", "ele": "ele_ft", "step": "100 ft",
           "index": "1,000 ft", "interval": "Contour interval 100 feet", "heights": "Heights in feet", "mark": "′"},
    "m": {"suffix": "_m", "contours": "contours_m", "field": "elev_m", "ele": "ele_m", "step": "25 m",
          "index": "250 m", "interval": "Contour interval 25 metres", "heights": "Heights in metres", "mark": ""},
}


# The sheet's abbreviations: Mt. Stephen, Paget Pk., Trolltinder Mtn., Wapta L., L. Margaret, Niles Cr.
ABBREV = [("^Mount ", "Mt. "), (" Mountain$", " Mtn."), (" Peak$", " Pk."), (" Lake$", " L."), ("^Lake ", "L. "),
          (" Creek$", " Cr.")]
HEIGHT_PT = 5.4  # heights print a little larger than at first (4.6 pt), as on the sheet


def short(field="name"):
    """QGIS expression: the name with the sheet's abbreviations."""
    e = f'"{field}"'
    for pat, rep in ABBREV:
        e = f"regexp_replace({e}, '{pat}', '{rep}')"
    return e


def labels(v, items):
    """Rule-based labels: (expression, QgsPalLayerSettings) pairs."""
    root = QgsRuleBasedLabeling.Rule(None)
    for expr, s in items:
        r = QgsRuleBasedLabeling.Rule(s)
        r.setFilterExpression(expr)
        root.appendChild(r)
    v.setLabeling(QgsRuleBasedLabeling(root))
    v.setLabelsEnabled(True)


def pal(expr, fmt, placement, priority, html=False, dist=0.0):
    s = QgsPalLayerSettings()
    s.isExpression = True
    s.fieldName = expr
    if html:
        fmt.setAllowHtmlFormatting(True)
    s.setFormat(fmt)
    s.placement = placement
    s.priority = priority
    s.dist = dist
    s.multilineAlign = Qgis.LabelMultiLineAlignment.Center
    return s


def marker(shape, size, fill, stroke, width=0.18):
    m = QgsSimpleMarkerSymbolLayer(shape, size)
    m.setColor(QColor(fill))
    m.setStrokeColor(QColor(stroke))
    m.setStrokeWidth(width)
    return symbol(m, kind=QgsMarkerSymbol)


def build_layers(units):
    u = UNITS[units]
    scan = QgsRasterLayer(str(DERIVED / "sheet16_26911_display.tif"), "Sheet No. 16 (1925 scan)")
    # Average the 4 m cells into each output pixel; QGIS takes the nearest cell by default, which aliases.
    dp = scan.dataProvider()
    dp.enableProviderResampling(True)
    dp.setZoomedOutResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Average)
    dp.setZoomedInResamplingMethod(QgsRasterDataProvider.ResamplingMethod.Bilinear)

    forefield = vlayer("Ground uncovered since 1913", "forefield")
    forefield.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": INK["forefield"], "outline_style": "no"})))

    contours = vlayer("Contours", u["contours"])
    rules(contours, [
        (f"Contour, {u['step']}", "on_ice = 0 AND idx = 0", symbol(line(INK["brown"], 0.16))),
        (f"Index contour, {u['index']}", "on_ice = 0 AND idx = 1", symbol(line(INK["brown_idx"], 0.34))),
        ("Contour on ice, 2021", "on_ice = 1 AND idx = 0", symbol(line(INK["blue"], 0.16))),
        ("Index contour on ice, 2021", "on_ice = 1 AND idx = 1", symbol(line(INK["blue_idx"], 0.34))),
    ])
    # Index contours carry their height along the line, in their own ink, as on the sheet.
    along = []
    for on_ice, ink in ((0, INK["brown_idx"]), (1, INK["blue_idx"])):
        s = pal(f'to_string(to_int("{u["field"]}"))', text(SANS, 4.4, ink), Qgis.LabelPlacement.Curved, 2)
        s.repeatDistance = 70
        s.repeatDistanceUnit = Qgis.RenderUnit.Millimeters
        along.append((f"idx = 1 AND on_ice = {on_ice}", s))
    labels(contours, along)

    summits = vlayer("Summits", "peaks")
    rules(summits, [
        ("Summit with official name", "official = 1",
         marker(Qgis.MarkerShape.Circle, 0.9, INK["paper"], INK["black"])),
        ("Other summit or high point", "official = 0", marker(Qgis.MarkerShape.Circle, 0.4, INK["black"], INK["black"], 0)),
    ])
    height = f'to_string("{u["ele"]}") || \'{u["mark"]}\''
    ele = f"if(show_ele = 1, {height}, '')"
    name_fmt = text(SANS, 5.6, INK["black"], caps=True, spacing=0.25)
    labels(summits, [
        ("official = 1", pal(f"'<span>' || upper({short()}) || '</span><br><span style=\"font-size:{HEIGHT_PT}pt\">' "
                             f"|| {ele} || '</span>'", name_fmt, Qgis.LabelPlacement.AroundPoint, 8, html=True, dist=0.4)),
        ("official = 0 AND show_ele = 1", pal(ele, text(SANS, HEIGHT_PT, INK["black"]), Qgis.LabelPlacement.AroundPoint,
                                             4, dist=0.3)),
    ])
    high = vlayer("High points", "high_points")
    high.setRenderer(QgsSingleSymbolRenderer(marker(Qgis.MarkerShape.Circle, 0.4, INK["black"], INK["black"], 0)))
    labels(high, [("1 = 1", pal(height, text(SANS, HEIGHT_PT, INK["black"]), Qgis.LabelPlacement.AroundPoint, 3,
                                dist=0.3))])
    lake_h = vlayer("Lake heights", "lake_elev")
    lake_h.setRenderer(QgsNullSymbolRenderer())
    labels(lake_h, [("1 = 1", pal(height, text(SANS, HEIGHT_PT, INK["black"]), Qgis.LabelPlacement.OverPoint, 9))])

    ice21 = vlayer("Ice margin, 2021", "ice2021")
    ice21.setRenderer(QgsSingleSymbolRenderer(symbol(
        line(INK["blue_idx"], 0.22, dash=[1.2, 0.9]), kind=QgsFillSymbol)))

    ice13 = vlayer("Ice limit, 1913", "ice1913")
    ice13.setRenderer(QgsSingleSymbolRenderer(symbol(
        line(INK["paper"], 1.0), line(INK["limit"], 0.45, dash=[3.0, 0.9, 0.5, 0.9]), kind=QgsFillSymbol)))

    lakes = vlayer("Lakes", "lakes", "osm.gpkg")
    fill = QgsFillSymbol.createSimple({"color": INK["water"], "outline_color": INK["water_line"],
                                       "outline_width": "0.25"})
    for d in (-30, -65, -105):  # water-lining: rings stepping in from the shore, as engraved
        g = QgsGeometryGeneratorSymbolLayer.create({"geometryModifier": f"boundary(buffer($geometry, {d}))"})
        g.setSymbolType(Qgis.SymbolType.Line)
        g.subSymbol().symbolLayer(0).setColor(QColor(INK["water_line"]))
        g.subSymbol().symbolLayer(0).setWidth(0.12)
        fill.appendSymbolLayer(g)
    lakes.setRenderer(QgsSingleSymbolRenderer(fill))

    streams = vlayer("Rivers and creeks", "streams", "osm.gpkg")
    rules(streams, [
        ("River", "kind = 'river'", symbol(line(INK["water_line"], 0.4))),
        ("Creek", "kind <> 'river'", symbol(line(INK["water_line"], 0.18))),
    ])

    roads = vlayer("Roads", "roads", "osm.gpkg", subset="kind <> 'service'")
    roads.setRenderer(QgsSingleSymbolRenderer(symbol(line(INK["red"], 0.38))))
    trails = vlayer("Trails", "trails", "osm.gpkg", subset="kind IN ('path','footway','bridleway','track')")
    trails.setRenderer(QgsSingleSymbolRenderer(
        symbol(line(INK["red"], 0.22, dash=[2.2, 1.2], cap=Qt.PenCapStyle.FlatCap))))

    rail = vlayer("Railway", "rail", "osm.gpkg")
    ticks = QgsMarkerLineSymbolLayer.create({"interval": "1.6", "placement": "interval"})
    ticks.subSymbol().symbolLayer(0).setShape(Qgis.MarkerShape.Line)
    ticks.subSymbol().symbolLayer(0).setSize(1.1)
    ticks.subSymbol().symbolLayer(0).setStrokeColor(QColor(INK["black"]))
    ticks.subSymbol().symbolLayer(0).setStrokeWidth(0.2)
    rules(rail, [
        ("Railway", "tunnel = 0", symbol(line(INK["black"], 0.42), ticks)),
        ("Railway in tunnel", "tunnel = 1", symbol(line(INK["black"], 0.3, dash=[1.0, 0.8]))),
    ])

    boundary = vlayer("Alberta - British Columbia boundary", "boundary", "osm.gpkg")
    boundary.setRenderer(QgsSingleSymbolRenderer(symbol(
        line(INK["paper"], 1.4), line(INK["black"], 0.6, dash=[3.2, 1.6], cap=Qt.PenCapStyle.FlatCap))))

    names = vlayer("Names", "names")
    names.setRenderer(QgsNullSymbolRenderer())  # the points are not drawn, only their labels
    # Placement order when labels compete: lakes, then glaciers, summits, ranges, creeks.
    root = QgsRuleBasedLabeling.Rule(None)
    for kind, fmt, prio in (
        ("lake", text(SERIF, 6.6, INK["blue_idx"], italic=True), 10),
        ("glacier", text(SERIF, 7.0, INK["blue_idx"], italic=True, spacing=1.8), 9),  # spaced out, as the sheet does
        ("mountain", text(SANS, 5.6, INK["black"], caps=True, spacing=0.25), 7),
        ("river", text(SERIF, 6.2, INK["blue_idx"], italic=True), 6),
    ):
        s = QgsPalLayerSettings()
        s.isExpression = True
        s.fieldName = short()
        s.setFormat(fmt)
        s.placement = Qgis.LabelPlacement.OverPoint if kind != "mountain" else Qgis.LabelPlacement.AroundPoint
        s.priority = prio
        if kind == "glacier":  # lettered along the contours, as the sheet does (angle from 06_layers.py)
            s.dataDefinedProperties().setProperty(QgsPalLayerSettings.Property.LabelRotation,
                                                  QgsProperty.fromField("angle"))
        r = QgsRuleBasedLabeling.Rule(s)
        r.setFilterExpression(f"kind = '{kind}'")
        root.appendChild(r)
    names.setLabeling(QgsRuleBasedLabeling(root))
    names.setLabelsEnabled(True)

    # Creek and river names lettered along the stream, just above it (06_layers.py: stream_names).
    creeks = vlayer("Creek names", "stream_names")
    creeks.setRenderer(QgsNullSymbolRenderer())
    cs = pal(short(), text(SERIF, 6.2, INK["blue_idx"], italic=True, spacing=0.3), Qgis.LabelPlacement.Curved, 6,
             dist=0.4)
    cs.lineSettings().setPlacementFlags(Qgis.LabelLinePlacementFlag.AboveLine | Qgis.LabelLinePlacementFlag.BelowLine)
    cs.maxCurvedCharAngleIn, cs.maxCurvedCharAngleOut = 25.0, -25.0
    labels(creeks, [("1 = 1", cs)])

    # The frame's sides are meridians, so in this projection it is a trapezoid, narrower at the top by
    # about 47 m a side. The map is drawn over its bounding rectangle: paper covers the two slivers
    # outside it (OSM water, roads and trails ran into them; contours and ice are clipped to the frame),
    # and the neat line follows the trapezoid, as on the sheet.
    outside = vlayer("Outside the frame", "frame")
    outside.setRenderer(QgsInvertedPolygonRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": INK["paper"], "outline_style": "no"}))))
    neat = vlayer("Neat line", "frame")
    neat.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"style": "no", "outline_color": INK["black"], "outline_width": "0.3"})))

    # First in the list draws on top. Lakes sit over the creeks and rivers that run into them.
    vectors = [neat, outside, names, creeks, summits, high, lake_h, boundary, rail, roads, trails, ice13, ice21, lakes,
               streams, contours, forefield]
    return scan, vectors


def frame_extent(crs):
    """The frame polygon's bounding box in the display CRS."""
    from qgis.core import QgsCoordinateTransform
    fr = vlayer("frame", "frame")
    tr = QgsCoordinateTransform(fr.crs(), crs, QgsProject.instance())
    return tr.transformBoundingBox(fr.extent())


def map_item(layout, layers, crs, rect, x, y):
    m = QgsLayoutItemMap(layout)
    m.setCrs(crs)
    m.setLayers(layers)
    m.setExtent(rect)
    w = rect.width() / SCALE * 1000
    h = rect.height() / SCALE * 1000
    m.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    m.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
    m.setExtent(rect)
    m.setScale(SCALE)
    m.setBackgroundColor(QColor(INK["paper"]))
    # Labels stay whole and keep clear of the edge; the frame is narrower than the item at the top by
    # 47 m (0.75 mm), so the margin also keeps them off the paper outside the neat line.
    m.setLabelMargin(QgsLayoutMeasurement(LABEL_MARGIN_MM, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(m)
    return m, w, h


def label(layout, txt, x, y, w, h, font, size, color=INK["black"], align=Qt.AlignmentFlag.AlignHCenter,
          italic=False, caps=False, spacing=0.0):
    it = QgsLayoutItemLabel(layout)
    it.setText(txt)
    it.setTextFormat(text(font, size, color, italic=italic, caps=caps, spacing=spacing, buffer=False))
    it.setHAlign(align)
    it.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    it.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(it)
    return it


def dms(v, seconds=True):
    """Degrees, minutes (and seconds) as the sheet prints them: 51°37′15″."""
    t = round(abs(v) * 3600) if seconds else round(abs(v) * 60) * 60  # whole seconds (or minutes)
    d, m, sec = t // 3600, t // 60 % 60, t % 60
    return f"{d}°{m:02d}′{sec:02d}″" if seconds else f"{d}°{m:02d}′"


def graticule(lay, crs, rect, x0, y0):
    """Margin labels for the 5-minute graticule (layer graticule, 06_layers.py) and the coordinates of
    the four corners as the sheet prints them. Positions are in layout millimetres."""
    from qgis.core import QgsCoordinateTransform

    def mm(x, y):
        return x0 + (x - rect.xMinimum()) / SCALE * 1000, y0 + (rect.yMaximum() - y) / SCALE * 1000

    def layer_points(name):
        v = vlayer(name, name)
        tr = QgsCoordinateTransform(v.crs(), crs, QgsProject.instance())
        for f in v.getFeatures():
            geom = f.geometry()
            geom.transform(tr)
            yield f, [(p.x(), p.y()) for p in geom.vertices()]

    w, h, gap = 24, 3.2, 1.2
    for f, pts in layer_points("graticule"):
        val = dms(f["value"], seconds=False)
        ends = sorted(pts)[:: len(pts) - 1] if f["axis"] == "lat" else sorted(pts, key=lambda q: q[1])[:: len(pts) - 1]
        for i, (x, y) in enumerate(ends):
            lx, ly = mm(x, y)
            if f["axis"] == "lat":  # left end (i = 0) and right end
                label(lay, val, lx - gap - w if i == 0 else lx + gap, ly - h / 2, w, h, SANS, 6,
                      align=Qt.AlignmentFlag.AlignRight if i == 0 else Qt.AlignmentFlag.AlignLeft)
            else:                   # bottom end (i = 0) and top end
                label(lay, val, lx - w / 2, ly + gap if i == 0 else ly - gap - h, w, h, SANS, 6)

    # Corners: latitude above or below, longitude turned along the side, as on the sheet.
    corners = next(layer_points("frame"))[1][:4]
    lat = {"top": LAT_N, "bottom": LAT_S}
    lon = {"left": LON_W, "right": LON_E}
    top2 = sorted(sorted(corners, key=lambda q: -q[1])[:2])
    bot2 = sorted(sorted(corners, key=lambda q: q[1])[:2])
    w = 30
    for row, pair in (("top", top2), ("bottom", bot2)):
        for side, q in zip(("left", "right"), pair, strict=True):
            x, y = mm(*q)
            ly = y - gap - h if row == "top" else y + gap
            left = side == "left"
            label(lay, f"LAT. {dms(lat[row])}", x if left else x - w, ly, w, h, SANS, 6, spacing=0.3,
                  align=Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight)
            # A label turns about its centre: place it unturned so its centre lands beside the side,
            # its far end at the corner, then turn it.
            cx = x - gap - h / 2 if left else x + gap + h / 2
            cy = y + w / 2 if row == "top" else y - w / 2
            it = label(lay, f"LONG. {dms(lon[side])}", cx - w / 2, cy - h / 2, w, h, SANS, 6, spacing=0.3,
                       align=Qt.AlignmentFlag.AlignRight if (row == "top") == left else Qt.AlignmentFlag.AlignLeft)
            it.setItemRotation(-90 if left else 90)


def export(layout, path, dpi=DPI):
    ex = QgsLayoutExporter(layout)
    s = QgsLayoutExporter.ImageExportSettings()
    s.dpi = dpi
    # QGIS still tries to write a georeference into each PNG and GDAL prints "The PNG driver does not
    # support update access" once per image. The images are complete; the message can be ignored.
    s.exportMetadata = False
    s.generateWorldFile = False
    res = ex.exportToImage(str(path), s)
    if res != QgsLayoutExporter.Success:
        raise SystemExit(f"Export failed for {path}: {res}")


def page(project, w, h):
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    pg = layout.pageCollection().page(0)
    pg.setPageSize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
    bg = QgsFillSymbol.createSimple({"color": INK["paper"], "outline_style": "no"})
    pg.setPageStyleSymbol(bg)
    return layout


def render(project, crs, units):
    u = UNITS[units]
    project.removeAllMapLayers()
    scan, vectors = build_layers(units)
    for lyr in [scan, *vectors]:
        project.addMapLayer(lyr)

    styles = STYLES if units == "ft" else STYLES / "metric"
    styles.mkdir(parents=True, exist_ok=True)
    for v in vectors:
        v.saveNamedStyle(str(styles / (v.name().lower().replace(", ", "_").replace(" - ", "_")
                                       .replace(" ", "_") + ".qml")))

    rect = frame_extent(crs)
    mw, mh = rect.width() / SCALE * 1000, rect.height() / SCALE * 1000
    metrics = json.loads((DERIVED / "compare_metrics.json").read_text())

    # Frame-only images, same size, for the slider.
    frames = [(f"day06_modern{u['suffix']}.png", vectors)] + ([("day06_scan.png", [scan])] if units == "ft" else [])
    for name, layers in frames:
        lay = page(project, mw, mh)
        map_item(lay, layers, crs, rect, 0, 0)
        export(lay, OUT / name)

    # The full sheet.
    margin, top = 30, 46
    pw, ph = mw + 2 * margin, mh + top + 86
    lay = page(project, pw, ph)
    # The graticule (5 minutes, NAD83) is on the full sheet only: the slider compares the map body.
    grat = vlayer("Graticule", "graticule")
    grat.setRenderer(QgsSingleSymbolRenderer(symbol(line(INK["black"], 0.12))))
    project.addMapLayer(grat)
    m, _, _ = map_item(lay, vectors[:2] + [grat] + vectors[2:], crs, rect, margin, top)  # neat line = frame
    graticule(lay, crs, rect, margin, top)
    label(lay, "INTERPROVINCIAL BOUNDARY COMMISSION", margin, 10, mw, 8, SANS, 11, spacing=1.2)
    label(lay, "Boundary between Alberta and British Columbia", margin, 18, mw, 12, SERIF, 22)
    label(lay, "SHEET No 16, REPEATED", margin + mw - 60, 34, 60, 6, SANS, 8,
          align=Qt.AlignmentFlag.AlignRight, spacing=0.6)
    a = metrics["area_km2"]
    lo, hi = metrics["area_1913_range_km2"]
    label(lay, f"Terrain and ice of 2021 in the manner of the 1925 sheet. Ice on the sheet: "
               f"{a['1913']:.0f} km² in 1913 (method range {lo:.0f} to {hi:.0f}), "
               f"{a['1985']:.0f} km² in 1985, {a['2021']:.0f} km² in 2021.",
          margin, 36, mw - 62, 6, SERIF, 9, italic=True, align=Qt.AlignmentFlag.AlignLeft)
    sb = QgsLayoutItemScaleBar(lay)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.setUnits(Qgis.DistanceUnit.Miles if units == "ft" else Qgis.DistanceUnit.Kilometers)
    sb.setUnitLabel("Miles" if units == "ft" else "Kilometres")
    sb.setNumberOfSegments(2)
    sb.setNumberOfSegmentsLeft(0)
    sb.setUnitsPerSegment(1)
    sb.setTextFormat(text(SERIF, 8, INK["black"], buffer=False))
    sb.attemptMove(QgsLayoutPoint(margin, top + mh + 6, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(sb)
    label(lay, f"Scale 1:62,500  ·  {u['interval']}  ·  {u['heights']}  ·  Datum: mean sea level (CGVD2013)  ·  "
          "Graticule: NAD83", margin + 75,
          top + mh + 8, 150, 6, SERIF, 9, align=Qt.AlignmentFlag.AlignLeft)
    legend = QgsLayoutItemLegend(lay)
    legend.setLinkedMap(m)
    legend.setSyncMode(Qgis.LegendSyncMode.Manual)
    legend.setTitle("REFERENCES")
    keep = ["Contours", "Ice limit, 1913", "Ground uncovered since 1913", "Ice margin, 2021", "Lakes",
            "Rivers and creeks", "Roads", "Trails", "Railway", "Alberta - British Columbia boundary",
            "Summits"]
    root = legend.model().rootGroup()
    root.removeAllChildren()
    for name in keep:
        root.addLayer(project.mapLayersByName(name)[0])
    legend.setColumnCount(3)
    legend.setSplitLayer(True)
    legend.setEqualColumnWidth(True)
    legend.setSymbolWidth(9)
    legend.setSymbolHeight(3.6)
    for style, fmt in ((QgsLegendStyle.Title, text(SANS, 8, INK["black"], spacing=0.8, buffer=False)),
                       (QgsLegendStyle.Subgroup, text(SANS, 6.5, INK["black"], spacing=0.4, buffer=False)),
                       (QgsLegendStyle.SymbolLabel, text(SERIF, 8, INK["black"], buffer=False))):
        legend.rstyle(style).setTextFormat(fmt)
    legend.setBackgroundEnabled(False)
    legend.attemptMove(QgsLayoutPoint(margin, top + mh + 17, QgsUnitTypes.LayoutMillimeters))
    legend.attemptResize(QgsLayoutSize(mw, 40, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(legend)
    src = ("Terrain: NRCan MRDEM-30 (OGL-Canada). Ice 1985 and 2021: Bevington and Menounos 2022, "
           "doi:10.5281/zenodo.5900363 (CC BY 4.0). Ice 1913: blue contours of the 1925 sheet (scan: "
           "University of Alberta Library via the Internet Archive), mapped by colour; position within about 160 m. Water, roads, railway, boundary, "
           "summits and their heights: © OpenStreetMap contributors (ODbL); lake and other heights from MRDEM-30. "
           "Names: CGNDB (OGL-Canada).")
    label(lay, src, margin, ph - 12, mw, 10, SERIF, 7, align=Qt.AlignmentFlag.AlignLeft, italic=True)
    export(lay, OUT / f"day06_sheet{u['suffix']}.png")
    export(lay, OUT / f"day06_sheet{u['suffix']}_zoom.png", ZOOM_DPI)


def main():
    qgs = QgsApplication([], False)
    qgs.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    qgs.initQgis()
    project = QgsProject.instance()
    crs = QgsCoordinateReferenceSystem.fromProj(TM)
    project.setCrs(crs)
    for units in ("m", "ft"):  # feet last, so the saved project is the sheet's own units
        render(project, crs, units)
    project.write(str(DERIVED / "day06.qgz"))
    qgs.exitQgis()
    print("rendered", sorted(p.name for p in OUT.glob("day06_*.png")))


if __name__ == "__main__":
    main()
