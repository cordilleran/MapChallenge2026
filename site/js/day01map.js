/* Day 1 dynamic map: confluence glyphs on a Leaflet canvas. Data: window.DAY01_JUNCTIONS (data/day01_junctions.js).
   Arm length is set in screen pixels from the same rules as the static maps (A: 0.78*sqrt(order) mm; B: 0.8*magnitude^0.147 mm,
   1 mm = 3.78 CSS px at zoom 9) and grows with the square root of the zoom factor. Smaller streams are revealed as you zoom in. */
(function () {
  "use strict";
  var BLUE = "#7fb7d6", INK = "#e9f1f5", AMBER = "#ffb454", MM = 3.78, Z0 = 9, K = window.DAY01_K;        // K: Shreve length exponent, written with the data by 25_export_leaflet_data.R
  var J = window.DAY01_JUNCTIONS.map(function (r) {
    var ins = []; for (var i = 0; i < r[7].length; i += 3) ins.push([r[7][i], r[7][i + 1], r[7][i + 2]]);
    return { lat: r[0], lng: r[1], rise: r[2] === 1, oo: r[3], om: r[4], ob: r[5], us: r[6] === 1, ins: ins };
  });
  var mode = "strahler", showAmber = true, hover = -1;
  var map = L.map("map", { zoomSnap: 0.5, zoomDelta: 0.5, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false,
    minZoom: 6, maxZoom: 15, attributionControl: true, worldCopyJump: false });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution("Day 1 · Points · #30DayMapChallenge · BC Freshwater Atlas (OGL-BC), USGS 3DHP");
  var hv = (location.hash || "").replace("#", "").split("/").map(Number);                 // shareable view: #zoom/lat/lng
  if (hv.length === 3 && hv.every(isFinite)) map.setView([hv[1], hv[2]], hv[0]); else map.fitBounds(window.DAY01_BOUNDS, { padding: [20, 20] });
  var base = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
    { opacity: 0.55, maxZoom: 15, attribution: "© OpenStreetMap contributors © CARTO" });

  function mkCanvas(cls) { var c = document.createElement("canvas"); c.className = cls; c.style.position = "absolute"; c.style.pointerEvents = "none";
    map.getPanes().overlayPane.appendChild(c); return c; }
  var cv = mkCanvas("glyphs"), hl = mkCanvas("glyph-hover");
  var vis = [];                                           // visible junctions this draw: [index, x, y]

  function minOrder(z) { return z < 7 ? 6 : z < 8 ? 5 : z < 9.5 ? 4 : z < 10.5 ? 3 : z < 11.5 ? 2 : 1; }
  function armPx(order, mag, z) {
    var mm = mode === "strahler" ? 0.78 * Math.sqrt(order) : 0.8 * Math.pow(Math.max(mag, 1), K);
    return mm * MM * Math.min(6, Math.max(0.6, Math.pow(2, (z - Z0) / 2)));
  }
  function place(c, size, dpr) {
    c.width = size.x * dpr; c.height = size.y * dpr; c.style.width = size.x + "px"; c.style.height = size.y + "px";
    L.DomUtil.setPosition(c, map.containerPointToLayerPoint([0, 0]));
    var g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, size.x, size.y); return g;
  }
  function draw() {
    var z = map.getZoom(), size = map.getSize(), dpr = window.devicePixelRatio || 1, g = place(cv, size, dpr);
    place(hl, size, dpr); vis = [];
    var mo = minOrder(z), lw = Math.min(2, Math.max(0.8, 1 + 0.15 * (z - Z0))), pad = 40, bb = map.getBounds().pad(0.15);
    for (var i = 0; i < J.length; i++) { var j = J[i]; if (j.oo < mo || !bb.contains([j.lat, j.lng])) continue;
      var p = map.latLngToContainerPoint([j.lat, j.lng]); if (p.x < -pad || p.y < -pad || p.x > size.x + pad || p.y > size.y + pad) continue;
      vis.push([i, p.x, p.y]); }
    g.lineCap = "round"; g.lineWidth = lw;
    g.strokeStyle = BLUE; g.globalAlpha = 0.9; g.beginPath();
    vis.forEach(function (v) { var j = J[v[0]]; j.ins.forEach(function (a) { var L_ = armPx(a[1], a[2], z), r = a[0] * Math.PI / 180;
      g.moveTo(v[1], v[2]); g.lineTo(v[1] + Math.sin(r) * L_, v[2] - Math.cos(r) * L_); }); }); g.stroke();
    g.strokeStyle = INK; g.globalAlpha = 1; g.beginPath();
    vis.forEach(function (v) { var j = J[v[0]], L_ = armPx(j.oo, j.om, z), r = j.ob * Math.PI / 180;
      g.moveTo(v[1], v[2]); g.lineTo(v[1] + Math.sin(r) * L_, v[2] - Math.cos(r) * L_); }); g.stroke();
    if (showAmber) { g.fillStyle = AMBER; var rad = Math.max(1.1, 1.3 * lw); g.beginPath();
      vis.forEach(function (v) { if (J[v[0]].rise) { g.moveTo(v[1] + rad, v[2]); g.arc(v[1], v[2], rad, 0, 6.2832); } }); g.fill(); }
    document.getElementById("status").textContent = "zoom " + z.toFixed(1) + " · " + vis.length.toLocaleString() + " junctions on screen · outflow order " + mo + " and up";
    drawHover();
  }
  function drawHover() {
    var size = map.getSize(), dpr = window.devicePixelRatio || 1, g = hl.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, size.x, size.y);
    if (hover < 0) return; var v = vis.filter(function (q) { return q[0] === hover; })[0]; if (!v) return;
    g.strokeStyle = AMBER; g.lineWidth = 1.5; g.beginPath(); g.arc(v[1], v[2], 9, 0, 6.2832); g.stroke();
  }
  function describe(j) {
    var el = document.getElementById("info"); el.textContent = "";
    function line(label, text) { var d = document.createElement("div"); var b = document.createElement("b"); b.textContent = label + " "; d.appendChild(b); d.appendChild(document.createTextNode(text)); el.appendChild(d); }
    line("Junction", (j.us ? "United States" : "British Columbia") + (j.rise ? ", order rises" : ""));
    line("Inflows", j.ins.map(function (a) { return "order " + a[1] + " (" + a[2].toLocaleString() + " sources)"; }).join(", "));
    line("Outflow", "order " + j.oo + " (" + j.om.toLocaleString() + " sources)");
  }
  function pick(e) {
    var x = e.containerPoint.x, y = e.containerPoint.y, best = -1, bd = 12 * 12;
    for (var k = 0; k < vis.length; k++) { var dx = vis[k][1] - x, dy = vis[k][2] - y, d = dx * dx + dy * dy; if (d < bd) { bd = d; best = vis[k][0]; } }
    if (best !== hover) { hover = best; drawHover(); if (best >= 0) describe(J[best]); else document.getElementById("info").textContent = "Hover or tap a junction."; }
  }
  window.DAY01_TEST = { map: map, vis: function () { return vis; }, base: base };                   // read-only handles for smoke tests
  map.on("mousemove", pick); map.on("click", pick);
  map.on("moveend zoomend resize", draw); draw();

  map.on("moveend", function () { var c = map.getCenter(); try { history.replaceState(null, "", "#" + map.getZoom() + "/" + c.lat.toFixed(4) + "/" + c.lng.toFixed(4)); } catch (e) {} });
  document.getElementById("btn-strahler").addEventListener("click", function () { setMode("strahler"); });
  document.getElementById("btn-shreve").addEventListener("click", function () { setMode("shreve"); });
  function setMode(m) { mode = m; document.getElementById("btn-strahler").setAttribute("aria-pressed", m === "strahler"); document.getElementById("btn-shreve").setAttribute("aria-pressed", m === "shreve");
    document.getElementById("mode-note").textContent = m === "strahler" ? "Arm length grows with Strahler order." : "Arm length grows with Shreve magnitude (headwater streams upstream)."; draw(); }
  if (/[?&]mode=shreve/.test(location.search)) setMode("shreve");
  document.getElementById("chk-base").addEventListener("change", function (e) { if (e.target.checked) { base.addTo(map); base.bringToBack(); } else map.removeLayer(base); });
  document.getElementById("chk-amber").addEventListener("change", function (e) { showAmber = e.target.checked; draw(); });
})();
