/* Day 1 dynamic map: confluence glyphs on a Leaflet canvas.
   Data: data/day01_junctions.js (25_export_leaflet_data.R) and data/day01_relief.js (26_relief.R).
   Arm length follows the static maps (A: 0.78 * sqrt(order) mm; B: 0.8 * magnitude^K mm), with 1 mm = 3.78 CSS px at
   zoom 9, and grows with the square root of the zoom factor. Smaller streams are revealed as you zoom in. */
(function () {
  "use strict";

  var BLUE = "#7fb7d6", INK = "#e9f1f5", AMBER = "#ffb454", MUTED = "#8aa0ae", CASE = "#0c1822";
  var PX_PER_MM = 3.78, Z0 = 9, K = window.DAY01_K, NAMES = window.DAY01_NAMES, MOUTH = window.DAY01_MOUTH;

  // ---- data ----------------------------------------------------------------------------------------------------
  // Row: [lat, lng, rises, outOrder, outMag, outBearing, outName, us, areaKm2, [inBearing, inOrder, inMag, inName, ...]]
  var J = window.DAY01_JUNCTIONS.map(function (r) {
    var ins = [];
    for (var i = 0; i < r[9].length; i += 4) ins.push({ b: r[9][i], o: r[9][i + 1], m: r[9][i + 2], n: r[9][i + 3] });
    return { lat: r[0], lng: r[1], rise: r[2] === 1, out: { b: r[5], o: r[3], m: r[4], n: r[6] }, us: r[7] === 1, area: r[8], ins: ins };
  });
  var kettleArm = MOUTH.arms.filter(function (a) { return a.kind === "kettle"; })[0];

  // ---- map and relief ------------------------------------------------------------------------------------------
  var map = L.map("map", { zoomSnap: 0.5, zoomDelta: 0.5, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false,
    minZoom: 6, maxZoom: 15, worldCopyJump: false });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution("Day 1 · Points · #30DayMapChallenge · BC Freshwater Atlas (OGL-BC), USGS 3DHP · relief from a 30 m DEM");
  var hv = (location.hash || "").replace("#", "").split("/").map(Number);                 // shareable view: #zoom/lat/lng
  if (hv.length === 3 && hv.every(isFinite)) map.setView([hv[1], hv[2]], hv[0]);
  else map.fitBounds(window.DAY01_BOUNDS, { padding: [20, 20] });
  map.createPane("relief").style.zIndex = 350;             // its own pane under the glyph canvas (overlay pane, 400), so re-adding it never covers the glyphs
  var R = window.DAY01_RELIEF, relief = L.imageOverlay(R.url, R.bounds, { opacity: 1, interactive: false, pane: "relief" }).addTo(map);
  var casing = R.look === "superior";                      // dark casing under the glyphs on the light relief
  map.getContainer().style.background = R.edge;            // the relief fades into this colour, so its edge never shows
  map.setMaxBounds(L.latLngBounds(R.bounds)); map.options.maxBoundsViscosity = 1;
  function limitZoom() { map.setMinZoom(Math.floor(map.getBoundsZoom(window.DAY01_BOUNDS) * 2) / 2); }   // never further out than the whole basin
  limitZoom(); map.on("resize", limitZoom);

  function makeCanvas(cls) {
    var c = document.createElement("canvas");
    c.className = cls; c.style.position = "absolute"; c.style.pointerEvents = "none";
    map.getPanes().overlayPane.appendChild(c);
    return c;
  }
  var glyphCanvas = makeCanvas("glyphs"), hoverCanvas = makeCanvas("glyph-hover");

  // ---- state ---------------------------------------------------------------------------------------------------
  var mode = "strahler", showAmber = true, hover = null;   // hover: a junction index, "mouth", or null
  var onScreen = [];                                       // junctions drawn this frame: [index, x, y]
  var mouthPt = null;                                      // screen position of the mouth this frame

  function minOrder(z) { return z < 7 ? 6 : z < 8 ? 5 : z < 9.5 ? 4 : z < 10.5 ? 3 : z < 11.5 ? 2 : 1; }
  function zoomFactor(z) { return Math.min(6, Math.max(0.6, Math.pow(2, (z - Z0) / 2))); }
  function armPx(order, mag, z) {
    var mm = mode === "strahler" ? 0.78 * Math.sqrt(order) : 0.8 * Math.pow(Math.max(mag, 1), K);
    return mm * PX_PER_MM * zoomFactor(z);
  }
  function reliefOn() { return map.hasLayer(relief); }
  function lineTo(g, x, y, bearing, len) {
    var r = bearing * Math.PI / 180;
    g.moveTo(x, y); g.lineTo(x + Math.sin(r) * len, y - Math.cos(r) * len);
  }
  function fitCanvas(c, size, dpr) {
    c.width = size.x * dpr; c.height = size.y * dpr; c.style.width = size.x + "px"; c.style.height = size.y + "px";
    L.DomUtil.setPosition(c, map.containerPointToLayerPoint([0, 0]));
    var g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, size.x, size.y);
    return g;
  }

  // ---- drawing -------------------------------------------------------------------------------------------------
  function draw() {
    var z = map.getZoom(), size = map.getSize(), dpr = window.devicePixelRatio || 1;
    var g = fitCanvas(glyphCanvas, size, dpr); fitCanvas(hoverCanvas, size, dpr);
    var mo = minOrder(z), lw = Math.min(2, Math.max(0.8, 1 + 0.15 * (z - Z0))), pad = 40, view = map.getBounds().pad(0.15);

    onScreen = [];
    for (var i = 0; i < J.length; i++) {
      var j = J[i];
      if (j.out.o < mo || !view.contains([j.lat, j.lng])) continue;
      var p = map.latLngToContainerPoint([j.lat, j.lng]);
      if (p.x < -pad || p.y < -pad || p.x > size.x + pad || p.y > size.y + pad) continue;
      onScreen.push([i, p.x, p.y]);
    }
    var inArms = new Path2D(), outArms = new Path2D(), dots = new Path2D(), rad = Math.max(1.1, 1.3 * lw);
    onScreen.forEach(function (v) {
      var j = J[v[0]];
      j.ins.forEach(function (a) { lineTo(inArms, v[1], v[2], a.b, armPx(a.o, a.m, z)); });
      lineTo(outArms, v[1], v[2], j.out.b, armPx(j.out.o, j.out.m, z));
      if (j.rise) { dots.moveTo(v[1] + rad, v[2]); dots.arc(v[1], v[2], rad, 0, 2 * Math.PI); }
    });
    g.lineCap = "round";
    if (casing && reliefOn()) {                                                            // casing first, under everything
      g.strokeStyle = CASE; g.globalAlpha = 0.55; g.lineWidth = lw + 1.6; g.stroke(inArms); g.stroke(outArms);
      if (showAmber) { g.lineWidth = 1.6; g.stroke(dots); }
    }
    g.lineWidth = lw;
    g.strokeStyle = BLUE; g.globalAlpha = 0.9; g.stroke(inArms);                           // inflow arms
    g.strokeStyle = INK; g.globalAlpha = 1; g.stroke(outArms);                             // outflow arms
    if (showAmber) { g.fillStyle = AMBER; g.fill(dots); }                                  // order rises here
    drawMouth(g, z, lw);
    document.getElementById("status").textContent = "zoom " + z.toFixed(1) + " · " + onScreen.length.toLocaleString() +
      " junctions on screen · outflow order " + mo + " and up";
    drawHover();
  }

  // The last junction: the Kettle arm as usual; the Columbia, which is far larger than anything here, as a dashed pale line.
  function drawMouth(g, z, lw) {
    mouthPt = map.latLngToContainerPoint([MOUTH.lat, MOUTH.lng]);
    var x = mouthPt.x, y = mouthPt.y, colLen = 1.6 * armPx(8, window.DAY01_MAGMAX, z), cased = casing && reliefOn();
    var inflow = new Path2D(), columbia = new Path2D(), ring = new Path2D();
    MOUTH.arms.forEach(function (a) {
      if (a.kind.indexOf("columbia") === 0) lineTo(columbia, x, y, a.b, colLen); else lineTo(inflow, x, y, a.b, armPx(a.o, a.m, z));
    });
    ring.arc(x, y, 4, 0, 2 * Math.PI);
    g.globalAlpha = 1;
    if (cased) { g.strokeStyle = CASE; g.globalAlpha = 0.55; g.lineWidth = lw * 1.4 + 1.6; g.stroke(inflow); g.stroke(columbia); g.lineWidth = 2.8; g.stroke(ring); g.globalAlpha = 1; }
    g.lineWidth = lw * 1.4;
    g.strokeStyle = BLUE; g.stroke(inflow);
    g.strokeStyle = INK; g.setLineDash([3, 3]); g.stroke(columbia); g.setLineDash([]);
    g.strokeStyle = AMBER; g.lineWidth = 1.2; g.stroke(ring);
    if (z >= 8) { g.fillStyle = cased ? CASE : MUTED; g.font = "11px 'IBM Plex Mono', monospace"; g.fillText("Columbia River", x + 10, y + 16); }
  }

  function drawHover() {
    var size = map.getSize(), dpr = window.devicePixelRatio || 1, g = hoverCanvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, size.x, size.y);
    var p = null;
    if (hover === "mouth") p = [mouthPt.x, mouthPt.y];
    else if (hover !== null) { var v = onScreen.filter(function (q) { return q[0] === hover; })[0]; if (v) p = [v[1], v[2]]; }
    if (!p) return;
    g.strokeStyle = AMBER; g.lineWidth = 1.5; g.beginPath(); g.arc(p[0], p[1], 9, 0, 2 * Math.PI); g.stroke();
  }

  // ---- readout -------------------------------------------------------------------------------------------------
  function streamName(n) { return n >= 0 ? NAMES[n] : "unnamed"; }
  function sources(m) { return m.toLocaleString() + (m === 1 ? " source" : " sources"); }
  function armText(a) { return streamName(a.n) + ", order " + a.o + " (" + sources(a.m) + ")"; }
  function title(j) {                                                      // "Granby River joins Kettle River" when the names say so
    var out = j.out.n, side = j.ins.filter(function (a) { return a.n >= 0 && a.n !== out; })[0];
    if (out >= 0 && side) return NAMES[side.n] + " joins " + NAMES[out];
    if (out >= 0) return "on " + NAMES[out];
    return "unnamed streams";
  }
  function describe(lines) {
    var el = document.getElementById("info"); el.textContent = "";
    lines.forEach(function (l) {
      var d = document.createElement("div"), b = document.createElement("b");
      b.textContent = l[0] + " "; d.appendChild(b); d.appendChild(document.createTextNode(l[1])); el.appendChild(d);
    });
  }
  function km2(a) {                                                       // approximate: 2 significant figures, at least 0.1
    if (a === null || a === undefined) return "unknown";
    var r = a < 1 ? Math.max(0.1, Math.round(a * 10) / 10) : Number(a.toPrecision(2));
    return "about " + r.toLocaleString() + " km²";
  }
  function describeJunction(j) {
    describe([["Junction", title(j) + " · " + (j.us ? "Washington" : "British Columbia") + (j.rise ? " · order rises" : "")],
              ["Drains", km2(j.area) + " upstream (from the DEM)"],
              ["Inflows", j.ins.map(armText).join("; ")],
              ["Outflow", armText(j.out)]]);
  }
  function describeMouth() {
    describe([["Mouth", "the Kettle River joins the Columbia River in Lake Roosevelt, Washington"],
              ["Kettle", "order " + kettleArm.o + " (" + sources(kettleArm.m) + "), draining " + km2(MOUTH.area)],
              ["Columbia", "drawn dashed: far larger than any stream here, and not part of this network"]]);
  }
  function pick(e) {
    var x = e.containerPoint.x, y = e.containerPoint.y, best = null, bestD = 12 * 12;
    for (var k = 0; k < onScreen.length; k++) {
      var dx = onScreen[k][1] - x, dy = onScreen[k][2] - y, d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = onScreen[k][0]; }
    }
    if (mouthPt) { var mx = mouthPt.x - x, my = mouthPt.y - y; if (mx * mx + my * my < bestD) best = "mouth"; }
    if (best === hover) return;
    hover = best; drawHover();
    if (best === "mouth") describeMouth();
    else if (best !== null) describeJunction(J[best]);
    else document.getElementById("info").textContent = "Hover or tap a junction.";
  }

  // ---- controls ------------------------------------------------------------------------------------------------
  function setMode(m) {
    mode = m;
    document.getElementById("btn-strahler").setAttribute("aria-pressed", m === "strahler");
    document.getElementById("btn-shreve").setAttribute("aria-pressed", m === "shreve");
    document.getElementById("mode-note").textContent = m === "strahler" ? "Arm length grows with Strahler order."
      : "Arm length grows with Shreve magnitude (headwater streams upstream).";
    draw();
  }
  document.getElementById("btn-strahler").addEventListener("click", function () { setMode("strahler"); });
  document.getElementById("btn-shreve").addEventListener("click", function () { setMode("shreve"); });
  document.getElementById("chk-amber").addEventListener("change", function (e) { showAmber = e.target.checked; draw(); });
  document.getElementById("chk-relief").addEventListener("change", function (e) {
    if (e.target.checked) relief.addTo(map); else map.removeLayer(relief);
    map.getContainer().style.background = e.target.checked ? R.edge : "";
    draw();
  });

  map.on("mousemove click", pick);
  map.on("moveend zoomend resize", draw);
  map.on("moveend", function () {
    var c = map.getCenter();
    try { history.replaceState(null, "", "#" + map.getZoom() + "/" + c.lat.toFixed(4) + "/" + c.lng.toFixed(4)); } catch (e) { /* file:// */ }
  });
  window.DAY01_TEST = { map: map, onScreen: function () { return onScreen; }, relief: relief };   // read-only handles for smoke tests
  if (/[?&]mode=shreve/.test(location.search)) setMode("shreve"); else draw();
})();
