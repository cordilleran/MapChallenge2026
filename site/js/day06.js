// Day 6: before/after slider, pickers for the units of the repeat and the colours of the scan,
// and tiled zoom viewers for the full repeat and the 600 ppi scan. Loaded with defer, so the whole page is parsed first.
(function () {
  const IMG = "img/day06/";
  const wrap = document.getElementById("d6-compare");
  const top = document.getElementById("d6-top");
  const base = document.getElementById("d6-base");
  const range = document.getElementById("d6-range");
  const bar = document.getElementById("d6-bar");
  if (!wrap || !top || !range) return;

  // Slider.
  function set(v) {
    top.style.clipPath = `inset(0 ${100 - v}% 0 0)`;
    bar.style.left = `${v}%`;
  }
  range.addEventListener("input", () => set(+range.value));
  // Drag or tap on the image itself as well as on the range control.
  let down = false;
  function at(ev) {
    const r = wrap.getBoundingClientRect();
    const v = Math.min(100, Math.max(0, ((ev.clientX - r.left) / r.width) * 100));
    range.value = v.toFixed(1);
    set(v);
  }
  wrap.addEventListener("pointerdown", (ev) => { down = true; wrap.setPointerCapture(ev.pointerId); at(ev); });
  wrap.addEventListener("pointermove", (ev) => { if (down) at(ev); });
  wrap.addEventListener("pointerup", () => { down = false; });
  wrap.addEventListener("pointercancel", () => { down = false; });
  set(+range.value);

  // Pickers: each group of buttons sets one image source.
  const SRC = {
    units: {
      ft: { base: "2021.webp", sheet: "sheet.webp", tiles: "sheet" },
      m: { base: "2021_m.webp", sheet: "sheet_m.webp", tiles: "sheet_m" },
    },
    scan: { matched: "scan_matched.webp", raw: "scan.webp" },
  };
  let units = "ft";
  let sheetViewer = null;
  function pick(attr, apply) {
    const buttons = document.querySelectorAll(`.d6-tools button[${attr}]`);
    buttons.forEach((b) => b.addEventListener("click", () => {
      buttons.forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
      apply(b.getAttribute(attr));
    }));
  }
  const dzi = (name) => IMG + "tiles/" + name + ".dzi";
  pick("data-units", (u) => {
    units = u;
    base.src = IMG + SRC.units[u].base;
    const plain = document.getElementById("d6-sheet");
    if (plain) plain.src = IMG + SRC.units[u].sheet;
    if (sheetViewer) {
      // Same sheet size in both units, so the view stays on the same place.
      const view = sheetViewer.viewport.getBounds();
      sheetViewer.addOnceHandler("open", () => sheetViewer.viewport.fitBounds(view, true));
      sheetViewer.open(dzi(SRC.units[u].tiles));
    }
  });
  pick("data-scan", (k) => { top.src = IMG + SRC.scan[k]; });

  // The full repeat and the 600 ppi scan, tiled (img/day06/tiles, from 08b_tiles.py), each opened when it
  // nears the screen. Until then (or without scripts) the repeat is a plain image.
  function deepZoom(box, tiles, onOpen) {
    if (!box || !window.OpenSeadragon || !("IntersectionObserver" in window)) return;
    const seen = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      seen.disconnect();
      const viewer = window.OpenSeadragon({
        element: box,
        prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
        tileSources: dzi(tiles()),
        showNavigator: true,
        navigatorPosition: "TOP_RIGHT",
        navigatorSizeRatio: 0.18,
        navigatorAutoFade: false, // the overview and buttons stay in view
        autoHideControls: false,
        showRotationControl: false,
        visibilityRatio: 1,
        constrainDuringPan: true,
        maxZoomPixelRatio: 2,
        gestureSettingsMouse: { scrollToZoom: false }, // the wheel keeps scrolling the page
      });
      // The plain image stays until the first tiles arrive (OpenSeadragon 5 no longer fires tile-drawn).
      viewer.addOnceHandler("tile-loaded", () => box.querySelector(":scope > img")?.remove());
      if (onOpen) onOpen(viewer);
    }, { rootMargin: "300px" });
    seen.observe(box);
  }
  deepZoom(document.getElementById("d6-sheet-viewer"), () => SRC.units[units].tiles, (v) => { sheetViewer = v; });
  deepZoom(document.getElementById("d6-scan-viewer"), () => "scan");
})();
