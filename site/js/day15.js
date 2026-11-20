// Day 15 Inside out: the ground seen from the centre of the Earth.
// A zoom viewer over three world renders (img/day15/tiles, from day-15/static/site_assets.py),
// a distance legend, and the page's numbers, all read from data/day15.json.
(function () {
  "use strict";
  const IMG = "img/day15/";
  const box = document.getElementById("d15-viewer");
  const buttons = document.querySelectorAll(".d15-tools button[data-view]");
  const legend = document.getElementById("d15-legend");
  let view = "hypso";
  let viewer = null;
  const dzi = (v) => IMG + "tiles/world_" + v + ".dzi";

  const fmt = (x, d) => Number(x).toLocaleString("en-CA", { minimumFractionDigits: d, maximumFractionDigits: d });
  const ll = (lat, lon) => fmt(Math.abs(lat), 1) + "° " + (lat >= 0 ? "N" : "S") + ", " + fmt(Math.abs(lon), 1) + "° " + (lon >= 0 ? "E" : "W");

  fetch("data/day15.json").then((r) => {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then((d) => {
    const w = d.world.facts;
    const set = (k, v) => document.querySelectorAll(`[data-k="${k}"]`).forEach((el) => { el.textContent = v; });
    set("flat", fmt(w.equator_minus_pole_km, 1));
    set("rmax", fmt(w.r_max_km, 1));
    set("rmax-at", ll(w.r_max_at[0], w.r_max_at[1]));
    set("rmin", fmt(w.r_min_km, 1));
    set("rmin-at", ll(w.r_min_at[0], w.r_min_at[1]));
    set("lo", fmt(d.legend.lims_km[0], 0));
    set("hi", fmt(d.legend.lims_km[1], 0));
    set("z", fmt(w.z, 0));
    if (legend) legend.style.background = "linear-gradient(90deg," + d.legend.stops.join(",") + ")";
  }).catch((err) => console.error("day15.json did not load:", err));

  let pending = 0;
  function show(v, first) {
    if (v === view && !first) return;                 // the current view: nothing to reload
    view = v;
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
    const plain = box && box.querySelector(":scope > img");
    if (plain) plain.src = IMG + "world_" + v + ".webp";
    document.querySelectorAll(".d15-key").forEach((k) => { k.hidden = k.dataset.view !== v; });
    if (viewer) {
      // Same image size in every view, so keep the place; only the latest click restores it.
      const ticket = ++pending;
      const bounds = viewer.world.getItemCount() > 0 ? viewer.viewport.getBounds(true) : null;
      viewer.addOnceHandler("open", () => {
        if (bounds && ticket === pending) viewer.viewport.fitBounds(bounds, true);
      });
      viewer.open(dzi(v));
    }
  }
  buttons.forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

  if (box && window.OpenSeadragon && "IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      seen.disconnect();
      viewer = window.OpenSeadragon({
        element: box,
        drawer: "canvas",   // the WebGL drawer swapped red and blue on some tiles after full screen (Firefox, 11-19)
        prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
        tileSources: dzi(view),
        showNavigator: true,
        navigatorPosition: "TOP_RIGHT",
        navigatorSizeRatio: 0.16,
        navigatorAutoFade: false,
        autoHideControls: false,
        showRotationControl: false,
        visibilityRatio: 1,
        constrainDuringPan: true,
        maxZoomPixelRatio: 2,
        gestureSettingsMouse: { scrollToZoom: false },
      });
      viewer.addOnceHandler("tile-loaded", () => box.querySelector(":scope > img")?.remove());
    }, { rootMargin: "300px" });
    seen.observe(box);
  }
  show(view, true);
})();
