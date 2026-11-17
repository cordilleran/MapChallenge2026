// Day 7: the whole sheet in a tiled zoom viewer (OpenSeadragon), as on Day 6. Loaded with defer.
// Zoom stops at MAX_ZOOM times the opening view (GW 11-16, set from 3 to 5); closer in, the eye goes
// to the small flaws of the ink separation.
(function () {
  const MAX_ZOOM = 5;
  const box = document.getElementById("d7-viewer");
  if (!box || !window.OpenSeadragon || !("IntersectionObserver" in window)) return;
  const seen = new IntersectionObserver((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    seen.disconnect();
    const viewer = window.OpenSeadragon({
      element: box,
      prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/",
      tileSources: "img/day07/tiles/page.dzi",
      showNavigator: true,
      navigatorPosition: "TOP_RIGHT",
      navigatorSizeRatio: 0.16,
      navigatorAutoFade: false,
      autoHideControls: false,
      showRotationControl: false,
      visibilityRatio: 1,
      constrainDuringPan: true,
      gestureSettingsMouse: { scrollToZoom: false }, // the wheel keeps scrolling the page
    });
    viewer.addOnceHandler("open", () => {
      viewer.viewport.maxZoomLevel = viewer.viewport.getHomeZoom() * MAX_ZOOM;
    });
    // The plain image stays until the first tiles arrive.
    viewer.addOnceHandler("tile-loaded", () => box.querySelector(":scope > img")?.remove());
  }, { rootMargin: "300px" });
  seen.observe(box);
})();
