// Day 6: before/after slider, pickers for the units of the repeat and the colours of the scan,
// a zoomed view of the full sheet, and the tiled 600 ppi scan. Loaded with defer, so the whole page is parsed first.
(function () {
  const IMG = "img/day06/";
  const wrap = document.getElementById("d6-compare");
  const top = document.getElementById("d6-top");
  const base = document.getElementById("d6-base");
  const range = document.getElementById("d6-range");
  const bar = document.getElementById("d6-bar");
  const sheet = document.getElementById("d6-sheet");
  const sheetBox = document.getElementById("d6-sheet-box");
  const zoomBtn = document.getElementById("d6-zoom");
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
      ft: { base: "2021.webp", sheet: "sheet.webp", zoom: "sheet_zoom.webp" },
      m: { base: "2021_m.webp", sheet: "sheet_m.webp", zoom: "sheet_m_zoom.webp" },
    },
    scan: { matched: "scan_matched.webp", raw: "scan.webp" },
  };
  let units = "ft";
  let zoomed = false;
  function sheetSrc() { return IMG + SRC.units[units][zoomed ? "zoom" : "sheet"]; }
  function pick(attr, apply) {
    const buttons = document.querySelectorAll(`.d6-tools button[${attr}]`);
    buttons.forEach((b) => b.addEventListener("click", () => {
      buttons.forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
      apply(b.getAttribute(attr));
    }));
  }
  pick("data-units", (u) => {
    units = u;
    base.src = IMG + SRC.units[u].base;
    if (sheet) sheet.src = sheetSrc();
  });
  pick("data-scan", (k) => { top.src = IMG + SRC.scan[k]; });

  // The 600 ppi scan, tiled (img/day06/scan, from 08b_scan_tiles.py), opened when it nears the screen.
  const scanBox = document.getElementById("d6-scan-viewer");
  if (scanBox && window.OpenSeadragon && "IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      seen.disconnect();
      window.OpenSeadragon({
        element: scanBox,
        prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
        tileSources: IMG + "scan/sheet16.dzi",
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
    }, { rootMargin: "300px" });
    seen.observe(scanBox);
  }

  // Zoomed view of the full sheet: a 400 dpi image in a scrolling box, panned by dragging.
  if (!sheet || !sheetBox || !zoomBtn) return;
  const ZOOM = 3; // image width as a multiple of the box
  function zoom(on, fx, fy) {
    zoomed = on;
    sheetBox.classList.toggle("zoomed", on);
    zoomBtn.setAttribute("aria-pressed", String(on));
    zoomBtn.textContent = on ? "Fit the sheet" : "Zoom in";
    sheet.src = sheetSrc();
    // Keep the point that was clicked (fractions fx, fy of the image) in the middle of the box.
    if (on) {
      const w = sheetBox.clientWidth * ZOOM;
      const h = w * sheet.height / sheet.width;
      sheetBox.scrollLeft = fx * w - sheetBox.clientWidth / 2;
      sheetBox.scrollTop = fy * h - sheetBox.clientHeight / 2;
    }
  }
  zoomBtn.addEventListener("click", () => zoom(!zoomed, 0.5, 0.3));
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && zoomed) zoom(false); });
  let drag = null;
  let moved = false;
  sheetBox.addEventListener("pointerdown", (ev) => {
    moved = false;
    if (!zoomed || ev.pointerType !== "mouse") return; // touch pans by scrolling
    drag = { x: ev.clientX, y: ev.clientY, l: sheetBox.scrollLeft, t: sheetBox.scrollTop };
    sheetBox.setPointerCapture(ev.pointerId);
  });
  sheetBox.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 4) moved = true;
    sheetBox.scrollLeft = drag.l - (ev.clientX - drag.x);
    sheetBox.scrollTop = drag.t - (ev.clientY - drag.y);
  });
  const end = () => { drag = null; };
  sheetBox.addEventListener("pointerup", end);
  sheetBox.addEventListener("pointercancel", end);
  // A click (not a drag) zooms in on that point, or back out.
  sheet.addEventListener("click", (ev) => {
    if (moved) return;
    const r = sheet.getBoundingClientRect();
    zoom(!zoomed, (ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height);
  });
})();
