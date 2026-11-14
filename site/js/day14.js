/* Day 14, The Bath, Drained: a Leaflet CRS.Simple map of a simulated mud film, swipeable to the photo.
   Data: data/day14/meta.json, tiles/{light,dark,grey,greydark,tone,tonedark,photo}/{z}/{x}/{y}.jpg, emerge.json (pool emergence times), rules.png. */
(function () {
  "use strict";
  var BASE = "data/day14/";
  var TUB_MM = [1280, 520];
  var CARD_MM = 85.6;
  var state = { view: "model", swipeX: 0.5, cal: null, look: "sepia" };
  try { var lk = localStorage.getItem("d14look"); if (lk === "grey" || lk === "tone") state.look = lk; } catch (e) { /* storage blocked: sepia */ }
  try { var c = parseFloat(localStorage.getItem("d14-px-per-mm")); if (c > 1 && c < 40) state.cal = c; } catch (e) { /* storage blocked */ }

  function dark() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function $(id) { return document.getElementById(id); }
  function fail(msg) { $("prov").textContent = msg; }

  fetch(BASE + "meta.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(start).catch(function () { fail("The map data did not load. Reload the page. Opened as a file, the map cannot load its data; open it from the site."); });
  window.addEventListener("unhandledrejection", function () { fail("Part of the map did not load. Reload to try again."); });

  function start(meta) {
    var W = meta.width_px, H = meta.height_px, Z = meta.zmax;
    var unitsW = W / Math.pow(2, Z), unitsH = H / Math.pow(2, Z);
    var mmPerUnit = TUB_MM[0] / unitsW;
    var bounds = L.latLngBounds([[-unitsH, 0], [0, unitsW]]);
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var map = L.map("map", { crs: L.CRS.Simple, minZoom: -1, maxZoom: Z + 4, zoomSnap: 0, zoomDelta: 0.5, wheelPxPerZoomLevel: 90,
      maxBounds: bounds.pad(0.25), maxBoundsViscosity: 0.8, attributionControl: true, zoomControl: true,
      zoomAnimation: !reduce, fadeAnimation: !reduce, inertia: !reduce });
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution('Model and photo: GW, CC BY 4.0 · <a href="https://landlab.csdms.io/" target="_top">Landlab</a> · <a href="https://leafletjs.com" target="_top">Leaflet</a>');
    var opts = { minZoom: -1, maxZoom: Z + 4, maxNativeZoom: Z, minNativeZoom: 0, noWrap: true, bounds: bounds, tileSize: 256, keepBuffer: 3 };
    function tiles(set, pane) { return L.tileLayer(BASE + "tiles/" + set + "/{z}/{x}/{y}.jpg", L.extend({ pane: pane || "tilePane" }, opts)); }
    var model = { sepia: { light: tiles("light"), dark: tiles("dark") }, grey: { light: tiles("grey"), dark: tiles("greydark") }, tone: { light: tiles("tone"), dark: tiles("tonedark") } };
    map.createPane("photoPane"); map.getPane("photoPane").style.zIndex = 250;
    var photo = tiles("photo", "photoPane");
    var current = null;
    function setTheme() {
      var want = model[state.look][dark() ? "dark" : "light"];
      if (current === want) return;
      if (current) map.removeLayer(current);
      current = want.addTo(map);
    }
    setTheme();
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", setTheme);
    new MutationObserver(setTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    map.fitBounds(bounds, { animate: false, padding: [8, 8] });
    // the look: sepia ramp, or grey hillshade with the mud tinted
    function setLook(v) {
      state.look = (v === "grey" || v === "tone") ? v : "sepia";
      try { localStorage.setItem("d14look", state.look); } catch (e) { /* not kept */ }
      document.body.classList.toggle("look-grey", state.look === "grey");
      document.body.classList.toggle("look-tone", state.look === "tone");
      var rb = document.querySelector('input[name="look"][value="' + state.look + '"]'); if (rb) rb.checked = true;
      setTheme();
    }
    document.querySelectorAll('input[name="look"]').forEach(function (el) { el.addEventListener("change", function () { setLook(el.value); }); });
    setLook(state.look);
    // the drain: 120 mm from the left end, on the centre line; the hole is about 36 mm across
    function ll(xmm, ymm) { return L.latLng(-ymm / mmPerUnit, xmm / mmPerUnit); }
    var drain = L.layerGroup([
      L.circle(ll(120, 260), { radius: 18 / mmPerUnit, color: "#6b6f75", weight: 1.5, fill: true, fillColor: "#9aa0a6", fillOpacity: 0.35, dashArray: "3 3", interactive: false }),
      L.circle(ll(120, 260), { radius: 5 / mmPerUnit, stroke: false, fillColor: "#6b6f75", fillOpacity: 0.6, interactive: false })
    ]);
    function setDrain() { if ($("drainMark").checked) drain.addTo(map); else map.removeLayer(drain); }
    $("drainMark").addEventListener("change", setDrain); setDrain();
    $("veOut").textContent = Math.round(meta.ve);

    // --- swipe: the photo pane is clipped to the left of the handle ---
    var handle = L.DomUtil.create("div", "swipe-handle", map.getContainer());
    handle.setAttribute("role", "slider"); handle.setAttribute("tabindex", "0");
    handle.setAttribute("aria-label", "Swipe between the photo (left) and the model (right)");
    handle.setAttribute("aria-valuemin", "0"); handle.setAttribute("aria-valuemax", "100");
    handle.style.display = "none";
    function clip() {
      var pane = map.getPane("photoPane");
      if (state.view === "model") { pane.style.display = "none"; handle.style.display = "none"; return; }
      pane.style.display = "";
      var size = map.getSize();
      var nw = map.containerPointToLayerPoint([0, 0]), se = map.containerPointToLayerPoint(size);
      var x = state.view === "photo" ? size.x : Math.round(size.x * state.swipeX);
      var cx = map.containerPointToLayerPoint([x, 0]).x;
      pane.style.clip = "rect(" + [nw.y, cx, se.y, nw.x].join("px,") + "px)";
      handle.style.display = state.view === "swipe" ? "" : "none";
      handle.style.left = x + "px";
      handle.setAttribute("aria-valuenow", Math.round(state.swipeX * 100));
    }
    map.on("move zoom resize zoomend moveend", clip);
    var dragging = false;
    function dragTo(e) {
      var r = map.getContainer().getBoundingClientRect();
      var cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      state.swipeX = Math.min(0.98, Math.max(0.02, cx / r.width)); clip();
    }
    handle.addEventListener("pointerdown", function (e) { dragging = true; handle.setPointerCapture(e.pointerId); L.DomEvent.stop(e); });
    handle.addEventListener("pointermove", function (e) { if (dragging) dragTo(e); });
    handle.addEventListener("pointerup", function () { dragging = false; });
    handle.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        state.swipeX = Math.min(0.98, Math.max(0.02, state.swipeX + (e.key === "ArrowLeft" ? -0.05 : 0.05))); clip(); e.preventDefault();
      }
    });
    L.DomEvent.disableClickPropagation(handle);
    document.querySelectorAll('input[name="view"]').forEach(function (r) {
      r.addEventListener("change", function () {
        state.view = r.value;
        if (state.view !== "model" && !map.hasLayer(photo)) photo.addTo(map);
        clip(); provNote();
      });
    });

    // --- drain replay and shoreline isochrones, from the model's emergence times (loaded on first use) ---
    var water = null, iso = null, grid = null, loading = null, frame = 0;
    function loadGrid() {
      if (!loading) loading = fetch(BASE + "emerge.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (g) { grid = g; return g; });
      return loading;
    }
    function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
    function rgba(c) {   // a CSS colour to [r, g, b, a 0-255], via a 1 px canvas
      var cv = document.createElement("canvas"); cv.width = cv.height = 1;
      var x = cv.getContext("2d"); x.fillStyle = c; x.fillRect(0, 0, 1, 1); return x.getImageData(0, 0, 1, 1).data;
    }
    var waterCanvas = null;
    function drawWater() {
      var v = +$("drain").value;
      if (v >= 100) { $("drainOut").textContent = "drained"; if (water) { map.removeLayer(water); water = null; } return; }
      if (!grid) { $("drainOut").textContent = "loading…"; loadGrid().then(drawWater); return; }
      var t = grid.t_max * v / 100;
      $("drainOut").textContent = t.toFixed(0) + " s after the start";
      if (!waterCanvas) { waterCanvas = document.createElement("canvas"); waterCanvas.width = grid.nx; waterCanvas.height = grid.ny; }
      var ctx = waterCanvas.getContext("2d"), img = ctx.createImageData(grid.nx, grid.ny), px = img.data, c = rgba(cssVar("--water"));
      for (var k = 0, n = grid.nx * grid.ny; k < n; k++) {
        if (grid.t[k] > t) { px[4 * k] = c[0]; px[4 * k + 1] = c[1]; px[4 * k + 2] = c[2]; px[4 * k + 3] = c[3]; }
      }
      ctx.putImageData(img, 0, 0);
      var url = waterCanvas.toDataURL();
      if (water) water.setUrl(url);
      else water = L.imageOverlay(url, bounds, { interactive: false, className: "d14-water" }).addTo(map);
    }
    function onDrain() { if (frame) return; frame = requestAnimationFrame(function () { frame = 0; drawWater(); }); }
    function drawIso() {
      if (iso) { map.removeLayer(iso); iso = null; }
      if (!$("iso").checked) return;
      if (!grid) { loadGrid().then(drawIso); return; }
      var k = 4, cv = document.createElement("canvas"); cv.width = grid.nx * k; cv.height = grid.ny * k;
      var ctx = cv.getContext("2d"); ctx.fillStyle = cssVar("--iso");
      function band(i, j) { var e = grid.t[j * grid.nx + i]; return e < 0 ? -1 : Math.floor(e / 5); }
      for (var j = 0; j < grid.ny - 1; j++) for (var i = 0; i < grid.nx - 1; i++) {
        var b = band(i, j);
        if (b < 0) continue;
        if (band(i + 1, j) !== b && band(i + 1, j) >= 0) ctx.fillRect((i + 1) * k - 1, j * k, 1.5, k);
        if (band(i, j + 1) !== b && band(i, j + 1) >= 0) ctx.fillRect(i * k, (j + 1) * k - 1, k, 1.5);
      }
      iso = L.imageOverlay(cv.toDataURL(), bounds, { interactive: false }).addTo(map);
    }
    $("drain").addEventListener("input", onDrain);
    $("iso").addEventListener("change", drawIso);
    var rules = null;
    $("hatch").addEventListener("change", function () {
      if (this.checked) rules = L.imageOverlay(BASE + "rules.png", bounds, { interactive: false, opacity: 0.85 }).addTo(map);
      else if (rules) { map.removeLayer(rules); rules = null; }
    });

    // --- scale: ratio to the real tub, scale bar, provenance by zoom ---
    function cssPxPerMm() { return Math.pow(2, map.getZoom()) / mmPerUnit; }
    function realPxPerMm() { return state.cal || (96 / 25.4); }
    function fmtRatio(r) {
      if (r >= 1) return (r < 10 ? r.toFixed(1) : Math.round(r)) + " : 1";
      return "1 : " + (1 / r < 10 ? (1 / r).toFixed(1) : Math.round(1 / r));
    }
    function provNote() {
      var p = cssPxPerMm() * (window.devicePixelRatio || 1), msg = "";
      // p is device pixels per mm; a note shows once a source's pixel or cell spans more than 2 device pixels
      if (state.view !== "photo" && p > 2 * meta.px_per_mm_at_zmax) msg = "Past the deepest tiles (0.25 mm): enlarged, no new detail.";
      else if (state.view !== "model" && p > 2 / 0.34) msg = "Finer than the photograph (about 0.34 mm a pixel).";
      else if (state.view !== "photo" && p > 4 / meta.model_dx_mm) msg = "Finer than the model's 2 mm grid: texture below 2 mm is synthesised.";
      $("prov").textContent = msg;
    }
    function scale() {
      var r = cssPxPerMm() / realPxPerMm();
      $("ratioN").textContent = fmtRatio(r);
      $("ratioL").textContent = state.cal ? "map : tub" : "map : tub (uncalibrated)";
      var ppm = cssPxPerMm(), steps = [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500], mm = steps[0];
      for (var i = 0; i < steps.length; i++) if (steps[i] * ppm <= 140) mm = steps[i];
      $("sbBar").style.width = Math.round(mm * ppm) + "px";
      $("sbLab").textContent = mm >= 10 ? (mm / 10) + " cm" : mm + " mm";
      provNote();
    }
    map.on("zoom zoomend", scale); scale();
    $("oneToOne").addEventListener("click", function () {
      var z = Math.log2(realPxPerMm() * mmPerUnit);
      map.setZoom(Math.min(map.getMaxZoom(), z), { animate: !reduce });
      if (!state.cal) $("calibHelp").textContent = "Not yet calibrated: 1 : 1 assumes a 96 dpi screen, which phones are not. Use Calibrate.";
    });
    $("reset").addEventListener("click", function () {
      map.fitBounds(bounds, { animate: !reduce, padding: [8, 8] });
      $("drain").value = 100; drawWater();
    });
    var dlg = $("calDlg"), calR = $("calR"), calBar = $("calBar");
    function showBar() { calBar.style.width = calR.value + "px"; }
    $("calib").addEventListener("click", function () {
      calR.value = Math.round(realPxPerMm() * CARD_MM); showBar();
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    });
    calR.addEventListener("input", showBar);
    dlg.addEventListener("close", function () {
      if (dlg.returnValue !== "ok") return;
      state.cal = calR.value / CARD_MM;
      try { localStorage.setItem("d14-px-per-mm", String(state.cal)); } catch (e) { /* storage blocked */ }
      $("calibHelp").textContent = "Calibrated: " + state.cal.toFixed(2) + " screen px per mm.";
      scale();
    });

    // --- panel: closed at start on phones ---
    var panel = $("panel"), tog = $("panelToggle");
    function setPanel(open) { panel.hidden = !open; tog.setAttribute("aria-expanded", String(open)); }
    setPanel(window.innerWidth > 640);
    tog.addEventListener("click", function () { setPanel(panel.hidden); });
    L.DomEvent.disableClickPropagation(panel); L.DomEvent.disableScrollPropagation(panel);
    L.DomEvent.disableClickPropagation($("drainbox")); L.DomEvent.disableScrollPropagation($("drainbox"));
    // a link can set the state: #view=swipe&drain=40&iso=1&hatch=1&look=grey|tone&drainmark=0
    var hp = {};
    location.hash.replace(/^#/, "").split("&").forEach(function (kv) { var p = kv.split("="); if (p[0]) hp[p[0]] = decodeURIComponent(p[1] || ""); });
    if (hp.view && /^(model|swipe|photo)$/.test(hp.view)) {
      var rb = document.querySelector('input[name="view"][value="' + hp.view + '"]');
      if (rb) { rb.checked = true; rb.dispatchEvent(new Event("change")); }
    }
    if (hp.drain && !isNaN(+hp.drain)) { $("drain").value = Math.max(0, Math.min(100, +hp.drain)); drawWater(); }
    if (hp.look) setLook(hp.look);
    if (hp.drainmark === "0") { $("drainMark").checked = false; setDrain(); }
    if (hp.iso === "1") { $("iso").checked = true; drawIso(); }
    if (hp.hatch === "1") { $("hatch").checked = true; $("hatch").dispatchEvent(new Event("change")); }
    clip();
  }
})();
