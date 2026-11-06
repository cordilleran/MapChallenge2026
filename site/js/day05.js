/* Day 5 (Viewsheds: Six views on a valley): plain JavaScript controller.
   Loads data, recomputes cumulative viewsheds via Canvas data URLs, manages Leaflet map,
   base layers (Hillshade, Satellite 2025, Land cover 2021), fullscreen control,
   uncertainty overlays, line-of-sight profiles, and full-width station panel with interactive panorama.
   No frameworks, no build step, runs in all modern browsers.
   Code: MIT; see repo README. */
(function () {
  "use strict";

  // Rights holder agreement in place: repeat photographs are displayed with photo credits.
  const SHOW_REPEATS = true;
  const DATA_V = "?v=20261105h"; // D97: data files change with the page; bump with the script version

  // Approximate ground area per 32.72 m pixel in km2 (from viewsheds_index.json)
  const GROUND_RES_M = 32.72;
  const PX_AREA_KM2 = (GROUND_RES_M * GROUND_RES_M) / 1e6;

  // Viewshed bounds in EPSG:4326 (from viewsheds_index.json & base_bounds.json & layers.json)
  const VIEWSHED_BOUNDS = [
    [48.74424, -114.67921],
    [49.519508, -113.481756],
  ];

  // Station definitions matching viewsheds_index.json bit packing:
  // bit i (0..5) is (1 << i) for station_order[i] in [84, 85, 86, 87, 88, 89]
  const STATIONS = [
    { id: 84, bit: 0, mask: 1, name: "Stn. 84 Mt Blakiston (Shoulder)", short: "84 Mt Blakiston", lat: 49.103232, lon: -114.023494, elev: 2731.4, mlpId: 2081, inThesis: true },
    { id: 85, bit: 1, mask: 2, name: "Stn. 85 Anderson", short: "85 Anderson", lat: 49.138364, lon: -114.006758, elev: 2108.6, mlpId: 1992, inThesis: false },
    { id: 86, bit: 2, mask: 4, name: "Stn. 86 Sage Creek", short: "86 Sage Creek", lat: 49.154908, lon: -114.161517, elev: 2420.0, mlpId: 2020, inThesis: false },
    { id: 87, bit: 3, mask: 8, name: "Stn. 87 Blakiston Divide", short: "87 Blakiston Divide", lat: 49.157083, lon: -114.11485, elev: 2416.5, mlpId: 2054, inThesis: false },
    { id: 88, bit: 4, mask: 16, name: "Stn. 88 Lost Mt", short: "88 Lost Mt", lat: 49.126758, lon: -114.088225, elev: 2485.9, mlpId: 2021, inThesis: true },
    { id: 89, bit: 5, mask: 32, name: "Stn. 89 Lone Mt", short: "89 Lone Mt", lat: 49.104172, lon: -114.124058, elev: 2413.5, mlpId: 2067, inThesis: true },
  ];

  const STATION_MAP = {};
  STATIONS.forEach((s) => { STATION_MAP[s.id] = s; });

  // Raster dimensions
  const RASTER_W = 2666;
  const RASTER_H = 2638;
  const TOTAL_PX = RASTER_W * RASTER_H;

  // Offscreen canvases for fast pixel manipulation
  const cSrc = document.createElement("canvas");
  cSrc.width = RASTER_W;
  cSrc.height = RASTER_H;
  const ctxSrc = cSrc.getContext("2d", { willReadFrequently: true });

  const cDst = document.createElement("canvas");
  cDst.width = RASTER_W;
  cDst.height = RASTER_H;
  const ctxDst = cDst.getContext("2d");
  const dstImageData = ctxDst.createImageData(RASTER_W, RASTER_H);
  const dstU32 = new Uint32Array(dstImageData.data.buffer);

  // Cache for decoded scenario packed uint8 arrays: { scenarioKey: Uint8Array }
  const scenarioCache = {};

  // Application State
  const stationActive = { 84: true, 85: true, 86: true, 87: true, 88: true, 89: true };
  let currentScenario = "main";
  let currentUncMode = "cumul"; // cumul | rmse26 | rmse80 | pos
  let currentUncStation = 84;
  let currentBaseLayer = "hillshade"; // hillshade | satellite | landcover
  let currentStationId = 89; // Default station is 89
  let currentSelectedPlate = 597;
  let panoZoom = 1; // 1 or 2
  let panoMode = "color"; // color | grey
  let showTopPeaks = false;
  let isFallbackFs = false;
  let uncLoadSeq = 0; // D97: a late image load must not overwrite a newer layer

  // Global data holders
  let viewshedsIndex = null;
  let baseBounds = null;
  let profileDemMeta = null;
  let demInstance = null;
  let variantsData = null;
  let vectorsData = null;
  let photosData = null;
  let wedgesData = null;
  let layersData = null;
  let panoPeaksData = null;
  // D93: observer position. "station" = MLP station point as recorded (observer on its 30 m DEM cell + 1.6 m);
  // "highpoint" = highest DEM cell of the 3x3 window around it (+ 1.6 m).
  let currentPosition = "station";
  let panoPeaksHp = null;
  let positionsData = null;
  const STATION_LL0 = {};
  function peaksFor(stnId) {
    const src = currentPosition === "highpoint" ? panoPeaksHp : panoPeaksData;
    return src && src[String(stnId)];
  }
  function panoSuffix() { return currentPosition === "highpoint" ? "_hp" : ""; }

  // Leaflet map and layers
  let map = null;
  let baseViewshedOverlay = null;
  let baseCoreOverlay = null;
  let satelliteOverlay = null;
  let landcoverOverlay = null;
  let viewshedOverlay = null;
  let fireLayer = null;
  let peaksLayer = null;
  let stationMarkers = {};
  let profileLine = null;
  let plateDirectionsLayer = null;
  let mapAttrControl = null;
  let fsBtn = null;

  // DOM elements
  const elStatus = document.getElementById("d5-map-status");
  const elAreaVal = document.getElementById("d5-area-val");
  const elLegendBar = document.getElementById("d5-legend-bar");
  const elLegendTitle = document.getElementById("d5-legend-title");
  const elUncTableWrap = document.getElementById("d5-unc-table-wrap");
  const elVariantTableBody = document.querySelector("#d5-variant-table tbody");
  const elProfFrom = document.getElementById("d5-prof-from");
  const elProfTo = document.getElementById("d5-prof-to");
  const elProfSvg = document.getElementById("d5-prof-svg");
  const elProfSummary = document.getElementById("d5-prof-summary");
  const elPhonePagerLabel = document.getElementById("d5-stn-pager-label");
  const elFullscreenWrap = document.getElementById("d5-fullscreen-wrap");

  // Helper: set status message
  function setStatus(msg) {
    if (elStatus) elStatus.textContent = msg;
  }

  // -------------------------------------------------------------------------
  // 1. Initial Data Fetching
  // -------------------------------------------------------------------------
  function loadAllData() {
    setStatus("Loading survey data and rasters...");

    const pViewsheds = fetch("data/day05/viewsheds_index.json" + DATA_V).then((r) => r.json());
    const pBaseBounds = fetch("data/day05/base_bounds.json" + DATA_V).then((r) => r.json());
    const pProfMeta = fetch("data/day05/profile_dem.json" + DATA_V).then((r) => r.json());
    const pProfBin = fetch("data/day05/profile_dem.bin" + DATA_V).then((r) => r.arrayBuffer());
    const pVariants = fetch("data/day05/variants.json" + DATA_V).then((r) => r.json());
    const pVectors = fetch("data/day05/vectors.geojson" + DATA_V).then((r) => r.json());
    const pPhotos = fetch("data/day05/photos.json" + DATA_V).then((r) => r.json());
    const pWedges = fetch("data/day05/wedges.json" + DATA_V).then((r) => r.json());
    const pLayers = fetch("data/day05/layers.json" + DATA_V).then((r) => r.json());
    const pPanoPeaks = fetch("data/day05/pano_peaks.json" + DATA_V).then((r) => r.json());
    const pPanoPeaksHp = fetch("data/day05/pano_peaks_hp.json" + DATA_V).then((r) => r.json());
    const pPositions = fetch("data/day05/positions.json" + DATA_V).then((r) => r.json());

    Promise.all([pViewsheds, pBaseBounds, pProfMeta, pProfBin, pVariants, pVectors, pPhotos, pWedges, pLayers, pPanoPeaks, pPanoPeaksHp, pPositions])
      .then(([vIdx, bBounds, pMeta, pBin, vars, vecs, photos, wedges, layers, pPeaks, pPeaksHp, positions]) => {
        panoPeaksHp = pPeaksHp;
        positionsData = positions;
        viewshedsIndex = vIdx;
        baseBounds = bBounds;
        profileDemMeta = pMeta;
        variantsData = vars;
        vectorsData = vecs;
        photosData = photos;
        wedgesData = wedges;
        layersData = layers;
        panoPeaksData = pPeaks;

        // Initialize pure DEM sampling engine from day05core.js
        if (window.D5C && window.D5C.createDem) {
          demInstance = window.D5C.createDem(new Int16Array(pBin), profileDemMeta);
        }

        initMap();
        initLandcoverLegend();
        initStationPanel();
        initControls();
        populateProfileTargets();

        // Initial scenario decode and cumulative viewshed render
        loadScenarioRaster("main", function () {
          updateCumulativeViewshed();
          setStatus("Viewshed ready. Select stations or scenario to explore.");
        });

        // Run initial profile
        updateProfile();

        // Open default station 89
        openStation(89);
      })
      .catch((err) => {
        console.error("Data load error:", err);
        setStatus("Error loading data files.");
      });
  }

  // -------------------------------------------------------------------------
  // 2. Leaflet Map Initialization & Extent / Base Layers
  // -------------------------------------------------------------------------
  function initMap() {
    map = L.map("map", {
      zoomSnap: 0.5,
      zoomDelta: 0.5,
      maxBounds: VIEWSHED_BOUNDS,
      maxBoundsViscosity: 1.0,
      maxZoom: 16,
      attributionControl: false,
    });

    // Custom attribution control
    mapAttrControl = L.control.attribution({ position: "bottomright", prefix: false });
    mapAttrControl.addTo(map);
    updateMapAttribution();

    // Initial view centred on upper Blakiston Valley
    map.setView([49.13, -114.08], 11.5);

    // North arrow / compass control (matching site standard)
    const Compass = L.Control.extend({
      options: { position: "topright" },
      onAdd: function () {
        const d = L.DomUtil.create("div", "map-compass");
        d.setAttribute("role", "img");
        d.setAttribute("aria-label", "North is up");
        d.innerHTML =
          '<svg viewBox="0 -4 24 28" width="34" height="40" aria-hidden="true">' +
          '<text x="12" y="0" text-anchor="middle">N</text><circle cx="12" cy="12" r="9" class="ring"/>' +
          '<path d="M12 5 L14 12 L10 12 Z" class="north"/><path d="M14 12 L12 19 L10 12 Z" class="south"/>' +
          '<circle cx="12" cy="12" r=".8" class="hub"/></svg>';
        return d;
      },
    });
    new Compass().addTo(map);

    // Full screen button control in top-right corner
    const FullscreenControl = L.Control.extend({
      options: { position: "topright" },
      onAdd: function () {
        const btn = L.DomUtil.create("button", "d5-fs-btn");
        btn.type = "button";
        btn.setAttribute("aria-label", "Full screen");
        btn.textContent = "Full screen";
        btn.addEventListener("click", toggleFullscreen);
        fsBtn = btn;
        return btn;
      },
    });
    new FullscreenControl().addTo(map);

    // Leaflet scale bar
    L.control.scale({ position: "bottomleft", imperial: false, maxWidth: 140 }).addTo(map);

    // Panes for controlled visual ordering
    map.createPane("baseReliefPane").style.zIndex = 200;
    map.createPane("viewshedPane").style.zIndex = 300;
    map.createPane("vectorLinesPane").style.zIndex = 400;
    map.createPane("platesPane").style.zIndex = 420;
    map.createPane("profilePane").style.zIndex = 450;
    map.createPane("markersPane").style.zIndex = 500;

    plateDirectionsLayer = L.layerGroup().addTo(map);

    // Base relief overlays (Hillshade) from base_bounds.json
    if (baseBounds && baseBounds.viewshed) {
      baseViewshedOverlay = L.imageOverlay(baseBounds.viewshed.url, baseBounds.viewshed.bounds, {
        opacity: 0.95,
        interactive: false,
        pane: "baseReliefPane",
      }).addTo(map);
    }
    if (baseBounds && baseBounds.core) {
      baseCoreOverlay = L.imageOverlay(baseBounds.core.url, baseBounds.core.bounds, {
        opacity: 0.95,
        interactive: false,
        pane: "baseReliefPane",
      }); // GW 11-05: not shown; the hillshade stays plain now that Satellite and Land cover are their own layers
    }

    // Additional base layers (Satellite 2025 and Land cover 2021) from layers.json
    if (layersData && layersData.bounds) {
      if (layersData.satellite && layersData.satellite.url) {
        satelliteOverlay = L.imageOverlay(layersData.satellite.url, layersData.bounds, {
          opacity: 0.95,
          interactive: false,
          pane: "baseReliefPane",
        });
      }
      if (layersData.landcover && layersData.landcover.url) {
        landcoverOverlay = L.imageOverlay(layersData.landcover.url, layersData.bounds, {
          opacity: 0.95,
          interactive: false,
          pane: "baseReliefPane",
        });
      }
    }

    // Dynamic minZoom fitting to hillshade bounds
    updateMinZoom();
    map.on("resize", updateMinZoom);

    // Add vector layers
    initVectorLayers();
  }

  function updateMinZoom() {
    if (!map) return;
    const fitZoom = map.getBoundsZoom(VIEWSHED_BOUNDS, false);
    map.setMinZoom(fitZoom);
    if (map.getZoom() < fitZoom) {
      map.setZoom(fitZoom);
    }
  }

  function updateMapAttribution() {
    if (!mapAttrControl) return;
    let baseCredit = "MRDEM-30 (NRCan) / GLO-30";
    if (currentBaseLayer === "satellite" && layersData && layersData.satellite) {
      baseCredit = layersData.satellite.credit;
    } else if (currentBaseLayer === "landcover" && layersData && layersData.landcover) {
      baseCredit = layersData.landcover.credit;
    }
    if (mapAttrControl._container) {
      mapAttrControl._container.innerHTML =
        "Day 5 · Senses: Sight · #30DayMapChallenge · " + baseCredit + " · Mountain Legacy Project · Government of Alberta · CWFIS · © OpenStreetMap contributors";
    }
  }

  function switchBaseLayer(layerKey) {
    currentBaseLayer = layerKey;
    const btns = document.querySelectorAll("#d5-layer-btns button");
    btns.forEach((b) => {
      b.setAttribute("aria-pressed", b.getAttribute("data-layer") === layerKey ? "true" : "false");
    });

    if (layerKey === "hillshade") {
      if (baseViewshedOverlay && !map.hasLayer(baseViewshedOverlay)) map.addLayer(baseViewshedOverlay);
      if (satelliteOverlay && map.hasLayer(satelliteOverlay)) map.removeLayer(satelliteOverlay);
      if (landcoverOverlay && map.hasLayer(landcoverOverlay)) map.removeLayer(landcoverOverlay);
    } else if (layerKey === "satellite") {
      if (baseViewshedOverlay && map.hasLayer(baseViewshedOverlay)) map.removeLayer(baseViewshedOverlay);
      if (baseCoreOverlay && map.hasLayer(baseCoreOverlay)) map.removeLayer(baseCoreOverlay);
      if (satelliteOverlay && !map.hasLayer(satelliteOverlay)) map.addLayer(satelliteOverlay);
      if (landcoverOverlay && map.hasLayer(landcoverOverlay)) map.removeLayer(landcoverOverlay);
    } else if (layerKey === "landcover") {
      if (baseViewshedOverlay && map.hasLayer(baseViewshedOverlay)) map.removeLayer(baseViewshedOverlay);
      if (baseCoreOverlay && map.hasLayer(baseCoreOverlay)) map.removeLayer(baseCoreOverlay);
      if (satelliteOverlay && map.hasLayer(satelliteOverlay)) map.removeLayer(satelliteOverlay);
      if (landcoverOverlay && !map.hasLayer(landcoverOverlay)) map.addLayer(landcoverOverlay);
    }

    const lcLegendWrap = document.getElementById("d5-landcover-legend-wrap");
    if (lcLegendWrap) {
      lcLegendWrap.hidden = (layerKey !== "landcover");
    }

    updateMapAttribution();
  }

  function initLandcoverLegend() {
    const elBar = document.getElementById("d5-landcover-legend-bar");
    if (!elBar || !layersData || !layersData.landcover || !layersData.landcover.legend) return;
    elBar.innerHTML = "";
    layersData.landcover.legend.forEach((item) => {
      const itemEl = document.createElement("div");
      itemEl.className = "legend-item";
      const rgbStr = "rgb(" + item.rgb.join(",") + ")";
      itemEl.innerHTML =
        '<span class="legend-swatch" style="background:' + rgbStr + '; width:14px; height:14px;"></span>' +
        '<span>' + item.name + '</span>';
      elBar.appendChild(itemEl);
    });
  }

  // -------------------------------------------------------------------------
  // 3. Full Screen Handling
  // -------------------------------------------------------------------------
  function isFsActive() {
    return (document.fullscreenElement === elFullscreenWrap) || isFallbackFs;
  }

  function toggleFullscreen() {
    if (!elFullscreenWrap) return;
    if (isFallbackFs) { toggleFallbackFs(); return; } // D97: leave the fallback first
    if (document.fullscreenEnabled) {
      if (!document.fullscreenElement) {
        elFullscreenWrap.requestFullscreen().catch(() => {
          toggleFallbackFs();
        });
      } else {
        document.exitFullscreen().catch(() => {});
      }
    } else {
      toggleFallbackFs();
    }
  }

  function toggleFallbackFs() {
    isFallbackFs = !isFallbackFs;
    elFullscreenWrap.classList.toggle("d5-fullscreen-fallback", isFallbackFs);
    onFsChange();
  }

  function onFsChange() {
    const active = isFsActive();
    if (fsBtn) {
      fsBtn.textContent = active ? "Exit full screen" : "Full screen";
      fsBtn.setAttribute("aria-label", active ? "Exit full screen" : "Full screen");
    }
    if (map) {
      setTimeout(function () {
        map.invalidateSize();
        updateMinZoom();
      }, 80);
    }
  }

  document.addEventListener("fullscreenchange", onFsChange);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isFallbackFs) {
      toggleFallbackFs();
    }
  });

  // -------------------------------------------------------------------------
  // 4. Vector Layers (Boundary, Parkway, Trails, Kenow Fire, Stations, Peaks)
  // -------------------------------------------------------------------------
  function initVectorLayers() {
    if (!vectorsData || !vectorsData.features) return;

    const feats = vectorsData.features;

    // 1. Park boundary
    const boundaryFeats = feats.filter((f) => f.properties.layer === "park_boundary");
    if (boundaryFeats.length > 0) {
      L.geoJSON(boundaryFeats, {
        pane: "vectorLinesPane",
        style: {
          color: "#8aa0ae",
          weight: 2,
          dashArray: "5, 5",
          fill: false,
          opacity: 0.85,
        },
      }).addTo(map);
    }

    // 2. Red Rock Parkway
    const parkwayFeats = feats.filter((f) => f.properties.layer === "parkway");
    if (parkwayFeats.length > 0) {
      L.geoJSON(parkwayFeats, {
        pane: "vectorLinesPane",
        style: {
          color: "#e9f1f5",
          weight: 2.2,
          opacity: 0.9,
        },
      }).addTo(map);
    }

    // 3. Trails
    const trailFeats = feats.filter((f) => f.properties.layer === "trail");
    if (trailFeats.length > 0) {
      L.geoJSON(trailFeats, {
        pane: "vectorLinesPane",
        style: {
          color: "#5d6f7c",
          weight: 1.1,
          opacity: 0.7,
        },
      }).addTo(map);
    }

    // 4. Kenow Fire 2017 perimeter (off by default)
    const fireFeats = feats.filter((f) => f.properties.layer === "kenow_fire");
    if (fireFeats.length > 0) {
      fireLayer = L.geoJSON(fireFeats, {
        pane: "vectorLinesPane",
        style: {
          color: "#ffb454",
          weight: 1.8,
          dashArray: "6, 6",
          fill: true,
          fillColor: "#ffb454",
          fillOpacity: 0.08,
        },
      });
    }

    // 5. Named peaks
    renderPeakMarkers(false);

    // 6. Six stations as labelled markers
    STATIONS.forEach((stn) => {
      const icon = L.divIcon({
        className: "stn-map-icon",
        html: '<div class="stn-badge" id="map-badge-' + stn.id + '"><span class="badge-num">' + stn.id + '</span></div>',
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      });

      const m = L.marker([stn.lat, stn.lon], {
        icon: icon,
        pane: "markersPane",
        title: stn.name,
        alt: stn.name,
      }).addTo(map);

      m.bindTooltip(markerTip(stn), {
        direction: "top",
        offset: [0, -14],
      });

      m.on("click", function () {
        handleStationMarkerClick(stn.id);
      });

      stationMarkers[stn.id] = m;
    });

    // Profile line layer
    profileLine = L.polyline([], {
      color: "#ffb454",
      weight: 2.5,
      dashArray: null,
      pane: "profilePane",
    }).addTo(map);
  }

  function renderPeakMarkers(showAll) {
    if (peaksLayer) {
      map.removeLayer(peaksLayer);
      peaksLayer = null;
    }

    const peakFeats = vectorsData.features.filter((f) => {
      if (f.properties.layer !== "peak") return false;
      return showAll ? true : f.properties.in_core === true;
    });

    peaksLayer = L.geoJSON(peakFeats, {
      pane: "markersPane",
      pointToLayer: function (feature, latlng) {
        const marker = L.circleMarker(latlng, {
          radius: 3.5,
          color: "#9cc7de",
          weight: 1.2,
          fillColor: "#112130",
          fillOpacity: 0.9,
        });

        const name = feature.properties.name || "Peak";
        const elev = feature.properties.elevation_m ? Math.round(feature.properties.elevation_m) + " m" : "";
        marker.bindTooltip(name + (elev ? " (" + elev + ")" : ""), {
          direction: "right",
          className: "peak-tooltip",
        });

        marker.on("click", function () {
          handlePeakMarkerClick(feature);
        });

        return marker;
      },
    }).addTo(map);
  }

  // Destination point calculation on a sphere
  function destinationPoint(lat, lon, distanceM, bearingDeg) {
    const R = 6371000.0;
    const delta = distanceM / R;
    const theta = (bearingDeg * Math.PI) / 180.0;
    const phi1 = (lat * Math.PI) / 180.0;
    const lambda1 = (lon * Math.PI) / 180.0;

    const sinPhi2 = Math.sin(phi1) * Math.cos(delta) + Math.cos(phi1) * Math.sin(delta) * Math.cos(theta);
    const phi2 = Math.asin(sinPhi2);
    const lambda2 = lambda1 + Math.atan2(Math.sin(theta) * Math.sin(delta) * Math.cos(phi1), Math.cos(delta) - Math.sin(phi1) * sinPhi2);

    return [(phi2 * 180.0) / Math.PI, (lambda2 * 180.0) / Math.PI];
  }

  // Draw recorded bearings and fitted wedge for selected station
  function updatePlateDirections(stnId, activePlateNum) {
    if (!plateDirectionsLayer || !wedgesData) return;
    plateDirectionsLayer.clearLayers();

    const stn = STATION_MAP[stnId];
    if (!stn) return;

    const stnWedges = wedgesData.filter((w) => w.station === stnId);
    if (!stnWedges || stnWedges.length === 0) return;

    stnWedges.forEach((w) => {
      const isSelected = (w.plate === activePlateNum);

      // 1. Draw each plate's recorded bearing as a dashed line 4 km long labelled with plate number
      if (w.recorded_bearing_2004_deg !== null && w.recorded_bearing_2004_deg !== undefined) {
        const endPt = destinationPoint(stn.lat, stn.lon, 4000, w.recorded_bearing_2004_deg);
        L.polyline([[stn.lat, stn.lon], endPt], {
          pane: "platesPane",
          color: isSelected ? "#ffb454" : "#e9f1f5",
          weight: isSelected ? 3.5 : 1.5,
          dashArray: isSelected ? "6, 4" : "4, 4",
          opacity: isSelected ? 1.0 : 0.8,
          interactive: false,
        }).addTo(plateDirectionsLayer);

        const labelIcon = L.divIcon({
          className: "plate-bearing-badge-wrap",
          html: '<div class="plate-bearing-badge' + (isSelected ? " active" : "") + '">' + w.plate + '</div>',
          iconSize: [32, 16],
          iconAnchor: [16, 8],
        });
        L.marker(endPt, {
          pane: "platesPane",
          icon: labelIcon,
          interactive: false,
        }).addTo(plateDirectionsLayer);
      }

      // 2. For plate 597 also draw fitted wedge (two edge lines and light fill to 6 km)
      if (w.plate === 597 && w.az_centre_deg !== null && w.hfov_deg !== null) {
        const azCentre = w.az_centre_deg;
        const hfov = w.hfov_deg;
        const azLeft = azCentre - hfov / 2.0;
        const azRight = azCentre + hfov / 2.0;
        const wedgeDist = 6000; // 6 km

        const arcPts = [[stn.lat, stn.lon]];
        const steps = 26;
        for (let i = 0; i <= steps; i++) {
          const az = azLeft + (azRight - azLeft) * (i / steps);
          arcPts.push(destinationPoint(stn.lat, stn.lon, wedgeDist, az));
        }
        arcPts.push([stn.lat, stn.lon]);

        // Light fill to 6 km
        L.polygon(arcPts, {
          pane: "platesPane",
          stroke: false,
          fill: true,
          fillColor: "#ffb454",
          fillOpacity: 0.18,
          interactive: false,
        }).addTo(plateDirectionsLayer);

        // Two edge lines to 6 km
        const leftEnd = destinationPoint(stn.lat, stn.lon, wedgeDist, azLeft);
        const rightEnd = destinationPoint(stn.lat, stn.lon, wedgeDist, azRight);
        L.polyline([[stn.lat, stn.lon], leftEnd], {
          pane: "platesPane",
          color: "#ffb454",
          weight: 2,
          opacity: 0.9,
          interactive: false,
        }).addTo(plateDirectionsLayer);
        L.polyline([[stn.lat, stn.lon], rightEnd], {
          pane: "platesPane",
          color: "#ffb454",
          weight: 2,
          opacity: 0.9,
          interactive: false,
        }).addTo(plateDirectionsLayer);
      }
    });
  }

  // -------------------------------------------------------------------------
  // 5. Station Marker & Peak Marker Clicks
  // -------------------------------------------------------------------------
  function handleStationMarkerClick(stnId) {
    if (elProfFrom) {
      elProfFrom.value = String(stnId);
      updateProfile();
    }
    openStation(stnId);
  }

  function handlePeakMarkerClick(peakFeature) {
    const peakName = peakFeature.properties.name;
    if (elProfTo) {
      for (let i = 0; i < elProfTo.options.length; i++) {
        if (elProfTo.options[i].text.indexOf(peakName) !== -1) {
          elProfTo.selectedIndex = i;
          updateProfile();
          break;
        }
      }
    }
  }

  // -------------------------------------------------------------------------
  // 6. Cumulative Viewshed Recompute Engine
  // -------------------------------------------------------------------------
  function loadScenarioRaster(scenKey, callback) {
    const cacheKey = currentPosition + ":" + scenKey;
    if (scenarioCache[cacheKey]) {
      if (callback) callback();
      return;
    }

    if (!viewshedsIndex || !viewshedsIndex.scenarios || !viewshedsIndex.scenarios[scenKey]) {
      console.error("Scenario not found in index:", scenKey);
      return;
    }

    setStatus("Loading scenario raster: " + scenKey + "...");
    const scenInfo = currentPosition === "highpoint"
      ? positionsData.packs_highpoint[scenKey]
      : viewshedsIndex.scenarios[scenKey];
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = function () {
      ctxSrc.clearRect(0, 0, RASTER_W, RASTER_H);
      ctxSrc.drawImage(img, 0, 0);
      const imgData = ctxSrc.getImageData(0, 0, RASTER_W, RASTER_H);
      const data = imgData.data;

      // Extract packed luminance byte into a tight Uint8Array
      const packed = new Uint8Array(TOTAL_PX);
      for (let i = 0; i < TOTAL_PX; i++) {
        packed[i] = data[i * 4]; // Red channel holds luminance bitmask (0..63)
      }
      scenarioCache[cacheKey] = packed;
      if (callback) callback();
    };
    img.onerror = function (e) {
      console.error("Failed to load scenario image:", scenInfo.url, e);
      setStatus("Error loading scenario raster.");
    };
    img.src = scenInfo.url;
  }

  // Sequential single-hue ramp (6 steps, light to dark)
  const CUMUL_RAMP_6 = [
    { r: 180, g: 220, b: 245, hex: "#b4dcf5" }, // 1: light sky blue
    { r: 125, g: 185, b: 225, hex: "#7db9e1" }, // 2: soft steel blue
    { r: 70,  g: 145, b: 198, hex: "#4691c6" }, // 3: river blue
    { r: 35,  g: 105, b: 158, hex: "#23699e" }, // 4: deep slate blue
    { r: 16,  g: 65,  b: 110, hex: "#10416e" }, // 5: dark navy
    { r: 4,   g: 24,  b: 48,  hex: "#041830" }, // 6: darkest midnight navy
  ];

  function updateCumulativeViewshed() {
    if (currentUncMode !== "cumul") {
      updateUncertaintyLayer();
      return;
    }

    const srcPacked = scenarioCache[currentPosition + ":" + currentScenario];
    if (!srcPacked) {
      loadScenarioRaster(currentScenario, updateCumulativeViewshed);
      return;
    }

    let activeMask = 0;
    let numActive = 0;
    for (let s = 0; s < 6; s++) {
      const stn = STATIONS[s];
      if (stationActive[stn.id]) {
        activeMask |= 1 << stn.bit;
        numActive++;
      }
    }

    const lut = new Uint32Array(64);

    if (numActive === 1) {
      const singleRgba = ((255 << 24) | (148 << 16) | (111 << 8) | 43) >>> 0;
      for (let b = 0; b < 64; b++) {
        lut[b] = ((b & activeMask) !== 0) ? singleRgba : 0;
      }
    } else if (numActive > 1) {
      for (let b = 0; b < 64; b++) {
        const masked = b & activeMask;
        if (masked === 0) {
          lut[b] = 0;
        } else {
          let count = 0;
          let m = masked;
          while (m > 0) {
            count += m & 1;
            m >>= 1;
          }
          let r, g, bl;
          if (numActive === 6) {
            const step = Math.min(5, Math.max(0, count - 1));
            r = CUMUL_RAMP_6[step].r;
            g = CUMUL_RAMP_6[step].g;
            bl = CUMUL_RAMP_6[step].b;
          } else {
            const t = (count - 1) / (numActive - 1);
            r = Math.round(180 + t * (4 - 180));
            g = Math.round(220 + t * (24 - 220));
            bl = Math.round(245 + t * (48 - 245));
          }
          lut[b] = ((255 << 24) | (bl << 16) | (g << 8) | r) >>> 0;
        }
      }
    } else {
      for (let b = 0; b < 64; b++) lut[b] = 0;
    }

    let visiblePxCount = 0;
    for (let i = 0; i < TOTAL_PX; i++) {
      const pxVal = lut[srcPacked[i]];
      dstU32[i] = pxVal;
      if (pxVal !== 0) visiblePxCount++;
    }

    ctxDst.putImageData(dstImageData, 0, 0);
    const dataUrl = cDst.toDataURL("image/png");

    if (viewshedOverlay) {
      viewshedOverlay.setUrl(dataUrl);
      viewshedOverlay.setOpacity(0.8);
    } else {
      viewshedOverlay = L.imageOverlay(dataUrl, VIEWSHED_BOUNDS, {
        opacity: 0.8,
        interactive: false,
        pane: "viewshedPane",
      }).addTo(map);
    }

    const areaKm2 = (visiblePxCount * PX_AREA_KM2).toFixed(1);
    if (elAreaVal) elAreaVal.textContent = areaKm2;

    renderCumulativeLegend(numActive);
    setStatus("Viewshed recomputed: " + areaKm2 + " km² visible (" + numActive + " station" + (numActive === 1 ? "" : "s") + ").");

    // Also update panel meta if heading is rendered
    updateStationPanelHeading();
  }

  function renderCumulativeLegend(numActive) {
    if (!elLegendBar || !elLegendTitle) return;

    elLegendTitle.textContent = "Stations seeing cell (" + numActive + " active)";
    elLegendBar.innerHTML = "";

    if (numActive === 0) {
      elLegendBar.innerHTML = '<span class="legend-note">No stations selected</span>';
      return;
    }

    if (numActive === 1) {
      const box = document.createElement("div");
      box.className = "legend-item";
      box.innerHTML = '<span class="legend-swatch" style="background:#2b6f94"></span><span class="legend-lbl">1 station</span>';
      elLegendBar.appendChild(box);
      return;
    }

    for (let c = 1; c <= numActive; c++) {
      let rgbStr;
      if (numActive === 6) {
        rgbStr = CUMUL_RAMP_6[c - 1].hex;
      } else {
        const t = (c - 1) / (numActive - 1);
        const r = Math.round(180 + t * (4 - 180));
        const g = Math.round(220 + t * (24 - 220));
        const b = Math.round(245 + t * (48 - 245));
        rgbStr = "rgb(" + r + "," + g + "," + b + ")";
      }

      const item = document.createElement("div");
      item.className = "legend-item";
      item.innerHTML = '<span class="legend-swatch" style="background:' + rgbStr + '"></span><span class="legend-lbl">' + c + "</span>";
      elLegendBar.appendChild(item);
    }
  }

  // -------------------------------------------------------------------------
  // 7. Uncertainty Layers (DEM error 2.6 m | DEM error 8 m | Station position)
  // -------------------------------------------------------------------------
  // What the selected map layer means, in one line under the selector.
  function updateUncNote() {
    const el = document.getElementById("d5-unc-note");
    if (!el) return;
    const n = currentUncStation;
    const notes = {
      cumul: "How many of the switched-on stations see each place (the station buttons above choose which).",
      rmse26: "Station " + n + ": the share of 50 runs, each with random terrain-model error of 2.6 m (NRCan's stated accuracy here), in which the station sees each place. Darker is surer.",
      rmse80: "Station " + n + ": the same 50-run test with 8 m of error, a pessimistic case for steep and forested ground.",
      pos: "Station " + n + ": how many of its recorded positions and heights see each place; the table lists them.",
    };
    el.textContent = notes[currentUncMode] || "";
  }

  function updateUncertaintyLayer() {
    updateUncNote();
    uncLoadSeq++;
    // D97: the readout is the combined area of the switched-on stations, so show it only with that layer.
    const areaLine = document.getElementById("d5-area-line");
    if (areaLine) areaLine.hidden = currentUncMode !== "cumul";
    if (currentUncMode === "cumul") {
      if (elUncTableWrap) elUncTableWrap.hidden = true;
      updateCumulativeViewshed();
      return;
    }

    const stnId = currentUncStation;
    let url = "";

    if (currentUncMode === "rmse26") {
      url = "img/day05/prob_" + stnId + "_rmse26.png";
      if (elUncTableWrap) elUncTableWrap.hidden = true;
      renderProbabilityRaster(url, "DEM error 2.6 m probability (0 to 100%)");
    } else if (currentUncMode === "rmse80") {
      url = "img/day05/prob_" + stnId + "_rmse80.png";
      if (elUncTableWrap) elUncTableWrap.hidden = true;
      renderProbabilityRaster(url, "DEM error 8.0 m probability (0 to 100%)");
    } else if (currentUncMode === "pos") {
      url = "img/day05/vs_" + stnId + "_unc.png";
      renderStationPositionRaster(url, stnId);
      renderVariantTable(stnId);
    }
  }

  function renderProbabilityRaster(url, title) {
    setStatus("Loading probability raster...");
    const seq = uncLoadSeq;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = function () {
      if (seq !== uncLoadSeq || currentUncMode === "cumul") return;
      ctxSrc.clearRect(0, 0, RASTER_W, RASTER_H);
      ctxSrc.drawImage(img, 0, 0);
      const imgData = ctxSrc.getImageData(0, 0, RASTER_W, RASTER_H);
      const data = imgData.data;

      const lutProb = new Uint32Array(256);
      lutProb[0] = 0;
      for (let p = 1; p <= 100; p++) {
        const t = p / 100.0;
        const r = Math.round(255 + t * (183 - 255));
        const g = Math.round(224 + t * (106 - 224));
        const b = Math.round(178 + t * (0 - 178));
        const a = Math.round(120 + t * (235 - 120));
        lutProb[p] = ((a << 24) | (b << 16) | (g << 8) | r) >>> 0;
      }

      for (let i = 0; i < TOTAL_PX; i++) {
        dstU32[i] = lutProb[data[i * 4]];
      }

      ctxDst.putImageData(dstImageData, 0, 0);
      const dataUrl = cDst.toDataURL("image/png");
      if (viewshedOverlay) viewshedOverlay.setUrl(dataUrl);

      renderProbabilityLegend(title);
      setStatus("Displaying " + title + " for Station " + currentUncStation + ".");
    };
    img.onerror = function () {
      setStatus("Error loading uncertainty raster.");
    };
    img.src = url;
  }

  function renderStationPositionRaster(url, stnId) {
    setStatus("Loading station position uncertainty raster...");
    const seq = uncLoadSeq;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = function () {
      if (seq !== uncLoadSeq || currentUncMode === "cumul") return;
      ctxSrc.clearRect(0, 0, RASTER_W, RASTER_H);
      ctxSrc.drawImage(img, 0, 0);
      const imgData = ctxSrc.getImageData(0, 0, RASTER_W, RASTER_H);
      const data = imgData.data;

      const maxCount = viewshedsIndex && viewshedsIndex.uncertainty && viewshedsIndex.uncertainty[stnId]
        ? viewshedsIndex.uncertainty[stnId].max_count
        : 7;

      const lutPos = new Uint32Array(256);
      lutPos[0] = 0;
      for (let c = 1; c <= maxCount; c++) {
        const t = (c - 1) / (maxCount - 1 || 1);
        const r = Math.round(180 + t * (20 - 180));
        const g = Math.round(215 + t * (70 - 215));
        const b = Math.round(230 + t * (110 - 230));
        const a = Math.round(140 + t * (240 - 140));
        lutPos[c] = ((a << 24) | (b << 16) | (g << 8) | r) >>> 0;
      }

      for (let i = 0; i < TOTAL_PX; i++) {
        dstU32[i] = lutPos[data[i * 4]];
      }

      ctxDst.putImageData(dstImageData, 0, 0);
      const dataUrl = cDst.toDataURL("image/png");
      if (viewshedOverlay) viewshedOverlay.setUrl(dataUrl);

      renderPositionLegend(maxCount, stnId);
      setStatus("Displaying position variants for Station " + stnId + " (" + maxCount + " variants).");
    };
    img.onerror = function () {
      setStatus("Error loading position uncertainty raster.");
    };
    img.src = url;
  }

  function renderProbabilityLegend(title) {
    if (!elLegendBar || !elLegendTitle) return;
    elLegendTitle.textContent = title;
    elLegendBar.innerHTML = "";

    const stops = [0, 25, 50, 75, 100];
    stops.forEach((p) => {
      const t = p / 100.0;
      const r = Math.round(255 + t * (183 - 255));
      const g = Math.round(224 + t * (106 - 224));
      const b = Math.round(178 + t * (0 - 178));
      const rgbStr = p === 0 ? "transparent" : "rgb(" + r + "," + g + "," + b + ")";

      const item = document.createElement("div");
      item.className = "legend-item";
      item.innerHTML = '<span class="legend-swatch" style="background:' + rgbStr + '"></span><span class="legend-lbl">' + p + "%</span>";
      elLegendBar.appendChild(item);
    });
  }

  function renderPositionLegend(maxCount, stnId) {
    if (!elLegendBar || !elLegendTitle) return;
    elLegendTitle.textContent = "Variants seeing cell: Stn. " + stnId;
    elLegendBar.innerHTML = "";

    for (let c = 1; c <= maxCount; c++) {
      const t = (c - 1) / (maxCount - 1 || 1);
      const r = Math.round(180 + t * (20 - 180));
      const g = Math.round(215 + t * (70 - 215));
      const b = Math.round(230 + t * (110 - 230));
      const rgbStr = "rgb(" + r + "," + g + "," + b + ")";

      const item = document.createElement("div");
      item.className = "legend-item";
      item.innerHTML = '<span class="legend-swatch" style="background:' + rgbStr + '"></span><span class="legend-lbl">' + c + "</span>";
      elLegendBar.appendChild(item);
    }
  }

  function renderVariantTable(stnId) {
    if (!elUncTableWrap || !elVariantTableBody || !variantsData) return;
    elVariantTableBody.innerHTML = "";

    const list = variantsData.variants.filter((v) => v.station === Number(stnId));
    list.forEach((v) => {
      const tr = document.createElement("tr");

      const label = v.notes ? v.variant_id + " (" + v.notes + ")" : v.variant_id;
      const elev = v.abs_observer_height ? v.abs_observer_height.toFixed(1) + " m" : "-";
      const km2 = v.visible_area_km2 ? v.visible_area_km2.toFixed(1) + " km²" : "-";
      const overlap = v.jaccard_main !== undefined ? (v.jaccard_main * 100).toFixed(1) + "%" : "-";

      tr.innerHTML =
        '<td style="text-align:left"><code>' + label + "</code></td>" +
        "<td>" + elev + "</td>" +
        "<td>" + km2 + "</td>" +
        "<td>" + overlap + "</td>";

      elVariantTableBody.appendChild(tr);
    });

    elUncTableWrap.hidden = false;
  }

  // -------------------------------------------------------------------------
  // 8. Line of Sight Profile Panel
  // -------------------------------------------------------------------------
  function populateProfileTargets() {
    if (!elProfTo || !profileDemMeta) return;
    elProfTo.innerHTML = "";

    const gStn = document.createElement("optgroup");
    gStn.label = "Survey Stations";
    STATIONS.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = "stn_" + s.id;
      opt.textContent = s.short;
      gStn.appendChild(opt);
    });
    elProfTo.appendChild(gStn);

    const gPeaks = document.createElement("optgroup");
    gPeaks.label = "Core Box Peaks";
    if (profileDemMeta.core_box_peaks) {
      profileDemMeta.core_box_peaks.forEach((p, idx) => {
        const opt = document.createElement("option");
        opt.value = "peak_" + idx;
        opt.textContent = p.name + " (" + Math.round(p.elevation_m) + " m)";
        gPeaks.appendChild(opt);
      });
    }
    elProfTo.appendChild(gPeaks);

    if (elProfTo.options.length > 6) {
      elProfTo.selectedIndex = 6;
    }
  }

  function updateProfile() {
    if (!demInstance || !window.D5C || !elProfFrom || !elProfTo) return;

    const startStnId = Number(elProfFrom.value);
    const startStn = STATION_MAP[startStnId];
    if (!startStn) return;

    let targetName = "";
    let targetX = 0, targetY = 0, targetLat = 0, targetLon = 0;

    const toVal = elProfTo.value;
    if (toVal.indexOf("stn_") === 0) {
      const tgtStnId = Number(toVal.replace("stn_", ""));
      const tgtStn = STATION_MAP[tgtStnId];
      if (!tgtStn) return;
      targetName = tgtStn.short;
      targetLat = tgtStn.lat;
      targetLon = tgtStn.lon;
      const pt = window.D5C.projectTo3979(tgtStn.lat, tgtStn.lon);
      targetX = pt.x;
      targetY = pt.y;
    } else if (toVal.indexOf("peak_") === 0) {
      const idx = Number(toVal.replace("peak_", ""));
      const p = profileDemMeta.core_box_peaks[idx];
      if (!p) return;
      targetName = p.name;
      targetLat = p.lat;
      targetLon = p.lon;
      targetX = p.x_epsg3979;
      targetY = p.y_epsg3979;
    }

    const startPt = window.D5C.projectTo3979(startStn.lat, startStn.lon);

    const prof = window.D5C.losProfile(demInstance, startPt.x, startPt.y, targetX, targetY, {
      observerHeightM: 1.6,
      targetHeightM: 0.0,
      snapObserverCell: true,
    });

    renderProfileSvg(prof, startStn.short, targetName);

    if (profileLine) {
      profileLine.setLatLngs([
        [startStn.lat, startStn.lon],
        [targetLat, targetLon],
      ]);
      profileLine.setStyle({
        dashArray: prof.targetVisible ? null : "4, 4",
        color: prof.targetVisible ? "#ffb454" : "#e9f1f5",
      });
    }
  }

  function renderProfileSvg(prof, startName, targetName) {
    if (!elProfSvg || !elProfSummary) return;

    const n = prof.distances.length;
    const totalDistM = prof.totalDistanceM;
    const totalDistKm = totalDistM / 1000.0;
    const zObs = prof.observerElevationM;

    const endDrop = window.D5C.earthCurvatureDrop(totalDistM);
    const endZCorr = prof.groundHeights[n - 1] - endDrop;
    const slope = totalDistM > 0 ? (endZCorr - zObs) / totalDistM : 0;

    let minClear = Infinity;
    let firstBlockDist = null;

    for (let i = 1; i < n; i++) {
      const d = prof.distances[i];
      const rayCorr = zObs + slope * d;
      const gCorr = prof.correctedGroundHeights[i];
      const clear = rayCorr - gCorr;

      if (!prof.targetVisible && firstBlockDist === null && clear < -1e-4) {
        firstBlockDist = d;
      }

      if (d >= 60 && d <= totalDistM - 60) {
        if (clear < minClear) {
          minClear = clear;
        }
      }
    }

    if (minClear === Infinity) {
      for (let i = 1; i < n - 1; i++) {
        const d = prof.distances[i];
        const clear = (zObs + slope * d) - prof.correctedGroundHeights[i];
        if (clear < minClear) {
          minClear = clear;
        }
      }
    }
    if (minClear === Infinity) minClear = 0;

    if (prof.targetVisible) {
      const clearM = Math.max(0, minClear).toFixed(1);
      elProfSummary.textContent =
        targetName + " is visible from " + startName + " (distance " + totalDistKm.toFixed(2) + " km; clears the terrain by at least " + clearM + " m).";
    } else {
      const blockDistStr = firstBlockDist !== null ? (firstBlockDist / 1000.0).toFixed(2) + " km" : "sight line";
      elProfSummary.textContent =
        targetName + " is not visible from " + startName + " (distance " + totalDistKm.toFixed(2) + " km; first blocking point is at " + blockDistStr + ").";
    }

    const W = 760, H = 220;
    const padL = 60, padR = 25, padT = 20, padB = 30;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    let minZ = Infinity, maxZ = -Infinity;
    for (let i = 0; i < n; i++) {
      const z = prof.correctedGroundHeights[i];
      if (z < minZ) minZ = z;
      if (z > maxZ) maxZ = z;
    }
    if (zObs > maxZ) maxZ = zObs;
    if (endZCorr > maxZ) maxZ = endZCorr;

    const yMin = Math.floor((minZ - 40) / 100) * 100;
    const yMax = Math.ceil((maxZ + 40) / 100) * 100;
    const ySpan = yMax - yMin || 1;

    function px(d) {
      return padL + (d / (totalDistM || 1)) * plotW;
    }
    function py(z) {
      return padT + plotH - ((z - yMin) / ySpan) * plotH;
    }

    let polyPts = px(0) + "," + (padT + plotH);
    let linePath = "M " + px(0) + " " + py(prof.correctedGroundHeights[0]);
    for (let i = 0; i < n; i++) {
      const x = px(prof.distances[i]);
      const y = py(prof.correctedGroundHeights[i]);
      polyPts += " " + x + "," + y;
      if (i > 0) linePath += " L " + x + " " + y;
    }
    polyPts += " " + px(totalDistM) + "," + (padT + plotH);

    let hiddenPathsSvg = "";
    let inHidden = false;
    let hiddenStart = 0;

    for (let i = 0; i < n; i++) {
      if (prof.visible[i] === 0 && !inHidden) {
        inHidden = true;
        hiddenStart = i;
      } else if (prof.visible[i] === 1 && inHidden) {
        inHidden = false;
        let hPts = px(prof.distances[hiddenStart]) + "," + py(zObs + slope * prof.distances[hiddenStart]);
        for (let j = hiddenStart; j < i; j++) {
          hPts += " " + px(prof.distances[j]) + "," + py(prof.correctedGroundHeights[j]);
        }
        hPts += " " + px(prof.distances[i - 1]) + "," + py(zObs + slope * prof.distances[i - 1]);
        hiddenPathsSvg += '<polygon points="' + hPts + '" class="prof-hidden-shade" />';
      }
    }
    if (inHidden) {
      let hPts = px(prof.distances[hiddenStart]) + "," + py(zObs + slope * prof.distances[hiddenStart]);
      for (let j = hiddenStart; j < n; j++) {
        hPts += " " + px(prof.distances[j]) + "," + py(prof.correctedGroundHeights[j]);
      }
      hPts += " " + px(totalDistM) + "," + py(endZCorr);
      hiddenPathsSvg += '<polygon points="' + hPts + '" class="prof-hidden-shade" />';
    }

    const obsX = px(0), obsY = py(zObs);
    const tgtX = px(totalDistM), tgtY = py(endZCorr);
    const sightLineClass = prof.targetVisible ? "prof-ray visible" : "prof-ray blocked";

    let xTicksSvg = "";
    const xStepKm = totalDistKm > 10 ? 5 : totalDistKm > 4 ? 2 : 1;
    for (let km = 0; km <= totalDistKm; km += xStepKm) {
      const x = px(km * 1000);
      xTicksSvg +=
        '<line x1="' + x + '" y1="' + (padT + plotH) + '" x2="' + x + '" y2="' + (padT + plotH + 4) + '" stroke="var(--line)" />' +
        '<text class="tk" x="' + x + '" y="' + (padT + plotH + 16) + '" text-anchor="middle">' + km + " km</text>";
    }

    let yTicksSvg = "";
    const yStep = (yMax - yMin) > 1000 ? 500 : 200;
    for (let z = yMin; z <= yMax; z += yStep) {
      const y = py(z);
      yTicksSvg +=
        '<line x1="' + (padL - 4) + '" y1="' + y + '" x2="' + padL + '" y2="' + y + '" stroke="var(--line)" />' +
        '<text class="tk" x="' + (padL - 8) + '" y="' + (y + 3) + '" text-anchor="end">' + z + " m</text>";
    }

    elProfSvg.innerHTML =
      '<rect width="' + W + '" height="' + H + '" fill="var(--tile)" />' +
      '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (padT + plotH) + '" stroke="var(--line)" />' +
      '<line x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (padL + plotW) + '" y2="' + (padT + plotH) + '" stroke="var(--line)" />' +
      xTicksSvg +
      yTicksSvg +
      hiddenPathsSvg +
      '<polygon points="' + polyPts + '" class="prof-ground-fill" />' +
      '<path d="' + linePath + '" class="prof-ground-line" />' +
      '<line x1="' + obsX + '" y1="' + obsY + '" x2="' + tgtX + '" y2="' + tgtY + '" class="' + sightLineClass + '" />' +
      '<circle cx="' + obsX + '" cy="' + obsY + '" r="3.5" class="prof-pt-obs" />' +
      '<text class="ax" x="' + (obsX + 4) + '" y="' + (obsY - 6) + '">Obs (1.6 m)</text>' +
      '<circle cx="' + tgtX + '" cy="' + tgtY + '" r="3.5" class="prof-pt-tgt" />' +
      '<text class="ax" x="' + (tgtX - 4) + '" y="' + (tgtY - 6) + '" text-anchor="end">' + targetName + "</text>";
  }

  // -------------------------------------------------------------------------
  // 9. Station Panel (Panorama, Peaks, Azimuth Ruler, Plates & Plate View)
  // -------------------------------------------------------------------------
  function initStationPanel() {
    // Station selector toolbar buttons
    const selBtns = document.querySelectorAll("#d5-stn-select button");
    selBtns.forEach((btn) => {
      btn.addEventListener("click", function () {
        const sid = Number(this.getAttribute("data-stn"));
        openStation(sid);
      });
    });

    // Mobile pager buttons
    const btnPrev = document.getElementById("d5-prev-stn");
    if (btnPrev) {
      btnPrev.addEventListener("click", function () {
        const curIdx = STATIONS.findIndex((s) => s.id === currentStationId);
        const prevIdx = (curIdx - 1 + STATIONS.length) % STATIONS.length;
        openStation(STATIONS[prevIdx].id);
      });
    }

    const btnNext = document.getElementById("d5-next-stn");
    if (btnNext) {
      btnNext.addEventListener("click", function () {
        const curIdx = STATIONS.findIndex((s) => s.id === currentStationId);
        const nextIdx = (curIdx + 1) % STATIONS.length;
        openStation(STATIONS[nextIdx].id);
      });
    }

    // Panorama 2x Zoom button
    const zoomBtn = document.getElementById("d5-pano-zoom-btn");
    if (zoomBtn) {
      zoomBtn.addEventListener("click", function () {
        const scrollBox = document.getElementById("d5-pano-scroll");
        let centerAz = 0;
        if (scrollBox) {
          centerAz = (scrollBox.scrollLeft + scrollBox.clientWidth / 2) / (10 * panoZoom);
        }
        panoZoom = panoZoom === 1 ? 2 : 1;
        this.textContent = panoZoom === 1 ? "2x" : "1x";
        this.setAttribute("aria-label", panoZoom === 1 ? "Toggle 2x panorama zoom" : "Toggle 1x panorama zoom");
        refreshPanorama(false);
        if (scrollBox) {
          scrollBox.scrollLeft = Math.max(0, centerAz * 10 * panoZoom - scrollBox.clientWidth / 2);
        }
      });
    }

    // Panorama Colour/Grey toggle
    const modeBtn = document.getElementById("d5-pano-mode-btn");
    if (modeBtn) {
      modeBtn.addEventListener("click", function () {
        panoMode = panoMode === "color" ? "grey" : "color";
        this.textContent = panoMode === "color" ? "Greyscale" : "Colour";
        const elImg = document.getElementById("d5-pano-img");
        if (elImg) {
          elImg.src = panoMode === "grey"
            ? "img/day05/pano/pano_" + currentStationId + panoSuffix() + "_grey.webp"
            : "img/day05/pano/pano_" + currentStationId + panoSuffix() + ".webp";
        }
      });
    }

    // Top 10 Peaks checkbox
    const chkTopPeaks = document.getElementById("d5-chk-top-peaks");
    if (chkTopPeaks) {
      chkTopPeaks.addEventListener("change", function () {
        showTopPeaks = this.checked;
        const track = document.getElementById("d5-pano-track");
        if (track) {
          track.classList.toggle("show-top-peaks", showTopPeaks);
        }
      });
    }

    // Keyboard arrow scrolling on panorama scrollbox
    const scrollBox = document.getElementById("d5-pano-scroll");
    if (scrollBox) {
      scrollBox.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft") {
          scrollBox.scrollLeft -= 50;
          e.preventDefault();
        } else if (e.key === "ArrowRight") {
          scrollBox.scrollLeft += 50;
          e.preventDefault();
        }
      });
    }
  }

  function openStation(stnId) {
    currentStationId = Number(stnId);

    // Update station selector buttons
    const selBtns = document.querySelectorAll("#d5-stn-select button");
    selBtns.forEach((b) => {
      b.setAttribute("aria-pressed", Number(b.getAttribute("data-stn")) === currentStationId ? "true" : "false");
    });

    // Update phone pager label
    const stnIdx = STATIONS.findIndex((s) => s.id === currentStationId);
    if (elPhonePagerLabel && stnIdx !== -1) {
      elPhonePagerLabel.textContent = (stnIdx + 1) + " of " + STATIONS.length + ": Station " + currentStationId;
    }

    // Update heading
    updateStationPanelHeading();

    // Default plate selection for this station
    let defaultPlate = null;
    if (photosData && photosData.photos) {
      const stnPhotos = photosData.photos.filter((p) => p.station === currentStationId && p.id !== "dawson1881");
      if (stnPhotos.length > 0) {
        defaultPlate = stnPhotos[0].plate;
      }
    }
    currentSelectedPlate = defaultPlate;

    // Render panorama, ruler, peaks, plates, and center first plate
    refreshPanorama(true);

    // Render plate list and plate view
    renderPlateList(currentStationId);
    renderPlateView(currentSelectedPlate);

    // Update plate directions on Leaflet map
    updatePlateDirections(currentStationId, currentSelectedPlate);
  }

  function updateStationPanelHeading() {
    const elHeader = document.getElementById("d5-panel-header");
    if (!elHeader) return;

    const stn = STATION_MAP[currentStationId];
    if (!stn) return;

    const pPeaks = peaksFor(currentStationId);
    const obsElev = pPeaks && pPeaks.observer_elev_m !== undefined ? pPeaks.observer_elev_m.toFixed(1) : stn.elev.toFixed(1);

    const stnIdxInfo = viewshedsIndex && viewshedsIndex.stations && viewshedsIndex.stations[String(currentStationId)];
    let visArea = "";
    if (stnIdxInfo && stnIdxInfo.area_km2) {
      visArea = stnIdxInfo.area_km2[currentScenario] || stnIdxInfo.area_km2.main || "";
    }
    if (currentPosition === "highpoint" && positionsData) {
      const hp = positionsData.stations[String(currentStationId)].highpoint;
      visArea = hp.area_km2[currentScenario] || hp.visible_km2;
    }

    const scenName = currentScenario === "main" ? "bare earth" : currentScenario;

    elHeader.innerHTML =
      '<div class="d5-panel-title-row">' +
        '<h3>' + stn.name + '</h3>' +
        '<a href="https://explore.mountainlegacy.ca/stations/show/' + stn.mlpId + '" target="_blank" rel="noopener" class="link">Mountain Legacy Project station ' + stn.mlpId + '</a>' +
      '</div>' +
      '<p class="rline small d5-panel-meta">Observer elevation: <b>' + obsElev + ' m</b> · Visible area: <b>' + visArea + ' km²</b> (' + scenName + ')</p>';
  }

  function refreshPanorama(centerFirstBearing) {
    const stn = STATION_MAP[currentStationId];
    const elImg = document.getElementById("d5-pano-img");
    const elTrack = document.getElementById("d5-pano-track");
    const scrollBox = document.getElementById("d5-pano-scroll");

    if (!elImg || !elTrack || !stn) return;

    const w = 3600 * panoZoom;
    const h = 370 * panoZoom;

    elTrack.style.width = w + "px";
    elTrack.classList.toggle("show-top-peaks", showTopPeaks);

    elImg.src = panoMode === "grey"
      ? "img/day05/pano/pano_" + currentStationId + panoSuffix() + "_grey.webp"
      : "img/day05/pano/pano_" + currentStationId + panoSuffix() + ".webp";
    elImg.width = w;
    elImg.height = h;
    elImg.alt = "Simulated panorama for " + stn.name;

    if (scrollBox) {
      scrollBox.setAttribute("aria-label", "360 degree simulated panorama for " + stn.short);
    }

    renderAzimuthRuler(panoZoom);
    renderPanoramaPeaks(currentStationId, panoZoom);
    renderPanoramaPlates(currentStationId, panoZoom);

    if (centerFirstBearing && scrollBox) {
      let centerAz = 0;
      if (photosData && photosData.photos) {
        const stnPhotos = photosData.photos.filter((p) => p.station === currentStationId && p.id !== "dawson1881");
        if (stnPhotos.length > 0 && wedgesData) {
          const wItem = wedgesData.find((item) => item.plate === stnPhotos[0].plate);
          if (wItem && wItem.recorded_bearing_2004_deg !== null && wItem.recorded_bearing_2004_deg !== undefined) {
            centerAz = wItem.recorded_bearing_2004_deg;
          }
        }
      }
      const targetPx = centerAz * 10 * panoZoom;
      scrollBox.scrollLeft = Math.max(0, targetPx - scrollBox.clientWidth / 2);
    }
  }

  function renderAzimuthRuler(zoom) {
    const svg = document.getElementById("d5-pano-ruler");
    if (!svg) return;
    const w = 3600 * zoom;
    svg.setAttribute("width", String(w));
    svg.setAttribute("viewBox", "0 0 " + w + " 24");

    let html = "";
    for (let az = 0; az <= 360; az += 10) {
      const x = az * 10 * zoom;
      const isMajor = (az % 30 === 0);
      const tickH = isMajor ? 8 : 4;
      const tickClass = isMajor ? "ruler-tick-major" : "ruler-tick";
      html += '<line x1="' + x + '" y1="0" x2="' + x + '" y2="' + tickH + '" class="' + tickClass + '" />';

      if (isMajor) {
        let label = az + "°";
        let isCardinal = false;
        if (az === 0 || az === 360) { label = "N"; isCardinal = true; }
        else if (az === 90) { label = "E"; isCardinal = true; }
        else if (az === 180) { label = "S"; isCardinal = true; }
        else if (az === 270) { label = "W"; isCardinal = true; }

        const txtClass = isCardinal ? "ruler-txt-cardinal" : "ruler-txt";
        let anchor = "middle";
        if (x === 0) anchor = "start";
        if (x === w) anchor = "end";
        html += '<text x="' + x + '" y="19" class="' + txtClass + '" style="text-anchor:' + anchor + '">' + label + '</text>';
      }
    }
    svg.innerHTML = html;
  }

  function renderPanoramaPeaks(stnId, zoom) {
    const layer = document.getElementById("d5-pano-peaks-layer");
    if (!layer || !peaksFor(stnId)) return;
    layer.innerHTML = "";

    const stnData = peaksFor(stnId);
    if (!stnData || !stnData.peaks) return;

    // Find 10 highest peaks of this station for permanent labels
    const sortedPeaks = stnData.peaks.slice().sort((a, b) => b.elevation_m - a.elevation_m);
    const top10Set = new Set(sortedPeaks.slice(0, 10));

    stnData.peaks.forEach((peak) => {
      const x = peak.col * zoom;
      const y = peak.row * zoom;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pano-peak-btn";
      btn.setAttribute("aria-label", peak.name);
      btn.style.left = x + "px";
      btn.style.top = y + "px";

      // 7 px triangle: filled for on_skyline, hollow otherwise
      let iconSvg = "";
      if (peak.on_skyline) {
        iconSvg = '<svg width="7" height="7" viewBox="0 0 7 7" aria-hidden="true"><polygon points="3.5,0 7,7 0,7" fill="#ffb454"/></svg>';
      } else {
        iconSvg = '<svg width="7" height="7" viewBox="0 0 7 7" aria-hidden="true"><polygon points="3.5,1 6,6 1,6" fill="none" stroke="#7fb7d6" stroke-width="1.2"/></svg>';
      }

      let innerHtml = iconSvg;
      if (top10Set.has(peak)) {
        innerHtml += '<span class="pano-peak-text-label">' + peak.name + '</span>';
      }
      btn.innerHTML = innerHtml;

      const elevAngleSign = peak.vert_angle_deg >= 0 ? "+" : "";
      const elevAngleStr = elevAngleSign + peak.vert_angle_deg.toFixed(1) + " degrees";
      const skylineStr = peak.on_skyline ? "on the skyline" : "seen in front of a higher ridge";

      function showTooltip() {
        removePanoramaTooltips();
        const tip = document.createElement("div");
        tip.className = "pano-peak-tip";
        tip.id = "active-pano-tip";
        tip.innerHTML =
          '<b>' + peak.name + '</b><br>' +
          'azimuth ' + Math.round(peak.azimuth_deg) + ' degrees<br>' +
          'elevation angle ' + elevAngleStr + '<br>' +
          'range ' + peak.distance_km.toFixed(1) + ' km<br>' +
          'height ' + Math.round(peak.elevation_m) + ' m (' + (peak.elevation_source === 'OpenStreetMap' ? 'published, OpenStreetMap' : 'terrain model') + ')<br>' +
          skylineStr;

        // Place by measuring the tooltip (GW 11-05: fixed thresholds cut off names of high peaks):
        // above the marker if it fits inside the panorama, otherwise below; kept inside left and right.
        tip.style.visibility = "hidden";
        layer.appendChild(tip);
        const tw = tip.offsetWidth, th = tip.offsetHeight;
        const totalW = 3600 * zoom;
        const boxH = (layer.offsetHeight || 370 * zoom);
        let left = Math.min(Math.max(x - tw / 2, 4), totalW - tw - 4);
        let top = y - th - 10;
        if (top < 4) top = y + 12;
        if (top + th > boxH - 4) top = Math.max(4, boxH - th - 4);
        tip.style.left = left + "px";
        tip.style.top = top + "px";
        tip.style.transform = "none";
        tip.style.visibility = "visible";
      }

      btn.addEventListener("mouseenter", showTooltip);
      btn.addEventListener("focus", showTooltip);
      btn.addEventListener("mouseleave", removePanoramaTooltips);
      btn.addEventListener("blur", removePanoramaTooltips);

      layer.appendChild(btn);
    });
  }

  function removePanoramaTooltips() {
    const old = document.getElementById("active-pano-tip");
    if (old) old.remove();
  }

  function renderPanoramaPlates(stnId, zoom) {
    const layer = document.getElementById("d5-pano-plates-layer");
    if (!layer || !wedgesData) return;
    layer.innerHTML = "";

    const stnWedges = wedgesData.filter((w) => w.station === stnId);
    const panoH = 370 * zoom;

    stnWedges.forEach((w) => {
      // Plate 597 fitted wedge shading
      if (w.plate === 597 && w.az_centre_deg !== null && w.hfov_deg !== null) {
        const azCentre = w.az_centre_deg;
        const hfov = w.hfov_deg;
        const azLeft = azCentre - hfov / 2.0;
        const xLeft = azLeft * 10 * zoom;
        const wPx = hfov * 10 * zoom;

        const shade = document.createElement("div");
        shade.className = "pano-wedge-shade";
        shade.style.left = xLeft + "px";
        shade.style.width = wPx + "px";
        shade.style.height = panoH + "px";
        layer.appendChild(shade);
      }

      // Recorded bearing vertical dashed line
      if (w.recorded_bearing_2004_deg !== null && w.recorded_bearing_2004_deg !== undefined) {
        const lineX = w.recorded_bearing_2004_deg * 10 * zoom;
        const line = document.createElement("div");
        line.className = "pano-plate-line";
        line.style.left = lineX + "px";
        line.style.height = panoH + "px";
        layer.appendChild(line);

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pano-plate-lbl-btn";
        btn.setAttribute("data-plate", String(w.plate));
        btn.textContent = "Plate " + w.plate;
        btn.style.left = lineX + "px";
        btn.style.top = "8px";
        btn.addEventListener("click", function () {
          currentSelectedPlate = w.plate;
          renderPlateView(w.plate);
          updatePlateList(stnId);
          updatePlateDirections(stnId, w.plate);
        });
        layer.appendChild(btn);
      }
    });
  }

  function renderPlateList(stnId) {
    const wrap = document.getElementById("d5-plate-list-wrap");
    if (!wrap || !photosData) return;
    wrap.innerHTML = "";

    const stn = STATION_MAP[stnId];
    const stnPhotos = photosData.photos.filter((p) => p.station === stnId && p.id !== "dawson1881");

    if (stnPhotos.length === 0) {
      const emptyMsg = document.createElement("p");
      emptyMsg.className = "rline small";
      emptyMsg.innerHTML = 'No plates from this station are shown here yet. See the station on <a href="https://explore.mountainlegacy.ca/stations/show/' + stn.mlpId + '" target="_blank" rel="noopener">MLP Explorer</a>.';
      wrap.appendChild(emptyMsg);
      return;
    }

    const list = document.createElement("div");
    list.className = "d5-plate-list";

    stnPhotos.forEach((p) => {
      const w = wedgesData ? wedgesData.find((item) => item.plate === p.plate) : null;
      const bearingStr = (w && w.recorded_bearing_2004_deg !== null) ? "Bearing " + w.recorded_bearing_2004_deg + "°" : "";

      const row = document.createElement("div");
      row.className = "d5-plate-row" + (p.plate === currentSelectedPlate ? " active-plate" : "");
      row.id = "plate-row-" + p.plate;

      row.innerHTML =
        '<div class="d5-plate-info">' +
          '<b>Plate ' + p.plate + '</b>' +
          '<span>' + bearingStr + '</span>' +
          '<span class="d5-plate-caption-short">' + p.caption_text + '</span>' +
        '</div>' +
        '<button type="button" class="cta small d5-show-plate-btn" data-plate="' + p.plate + '">Show plate</button>';

      const btn = row.querySelector(".d5-show-plate-btn");
      btn.addEventListener("click", function () {
        currentSelectedPlate = p.plate;
        renderPlateView(p.plate);
        updatePlateList(stnId);
        updatePlateDirections(stnId, p.plate);
      });

      list.appendChild(row);
    });

    wrap.appendChild(list);
  }

  function updatePlateList(stnId) {
    const rows = document.querySelectorAll(".d5-plate-row");
    rows.forEach((r) => {
      const pid = Number(r.id.replace("plate-row-", ""));
      r.classList.toggle("active-plate", pid === currentSelectedPlate);
    });
  }

  function renderPlateView(plateNum) {
    const wrap = document.getElementById("d5-plate-view-wrap");
    if (!wrap) return;
    wrap.innerHTML = "";

    if (!plateNum || !photosData) return;

    const photo = photosData.photos.find((p) => p.plate === plateNum);
    if (!photo) return;

    const view = document.createElement("div");
    view.className = "d5-plate-view";

    let html =
      '<div class="d5-plate-pair">' +
        '<figure class="d5-plate-col">' +
          '<img src="' + photo.files.historic + '" alt="1914 photograph, plate ' + photo.plate + '" class="d5-plate-img">' +
          '<figcaption class="photo-credit">' + photo.credits.historic + '</figcaption>' +
        '</figure>' +
        (SHOW_REPEATS && photo.files.repeat ?
        '<figure class="d5-plate-col">' +
          '<img src="' + photo.files.repeat + '" alt="Repeat photograph for plate ' + photo.plate + '" class="d5-plate-img">' +
          '<figcaption class="photo-credit">' + photo.credits.repeat + '</figcaption>' +
        '</figure>' : '') +
      '</div>' +
      '<p class="d5-plate-caption">' + photo.caption_text + '</p>' +
      '<p class="card-link"><a href="' + photo.mlp_station_url + '" target="_blank" rel="noopener">Mountain Legacy Project station ' + photo.mlp_station_id + '</a></p>';

    if (photo.plate === 597) {
      html +=
        '<details class="formula">' +
          '<summary>Skyline match</summary>' +
          '<figure class="wide">' +
            '<img src="img/day05/wedge_plate597.webp" alt="Plate 597 fitted model skyline overlay" class="wedge-photo" loading="lazy">' +
          '</figure>' +
          '<p id="d5-match-notes">The purple line is the skyline of the terrain model, drawn over the plate where it fits best: looking about 111 degrees (east-southeast) with a view about 51 to 52 degrees wide. Below it, the same stretch of the simulated panorama. A second, weaker fit lies at 268 degrees, near the bearings the repeat crews recorded. See Methods for how the match works and its limits.</p>' +
        '</details>';
    } else {
      html += '<p class="rline small wedge-note">Direction as recorded by the 2004 repeat crew; not yet checked against the terrain.</p>';
    }

    view.innerHTML = html;
    wrap.appendChild(view);
  }

  // -------------------------------------------------------------------------
  // 10. Interactive UI Controls & Event Listeners
  // -------------------------------------------------------------------------
  // D93: switch every station between its recorded point and the local high point.
  function markerTip(stn) {
    if (currentPosition === "highpoint" && positionsData) {
      const hp = positionsData.stations[String(stn.id)].highpoint;
      return "<b>" + stn.short + "</b><br>" + Math.round(hp.dem_m) + " m (terrain cell, local high point)";
    }
    return "<b>" + stn.short + "</b><br>" + stn.elev + " m (recorded)";
  }

  function setPosition(pos) {
    if (!positionsData || pos === currentPosition) return;
    currentPosition = pos;
    STATIONS.forEach((stn) => {
      if (!STATION_LL0[stn.id]) STATION_LL0[stn.id] = { lat: stn.lat, lon: stn.lon };
      const rec = positionsData.stations[String(stn.id)];
      const ll = pos === "highpoint" ? rec.highpoint : STATION_LL0[stn.id];
      stn.lat = ll.lat;
      stn.lon = ll.lon;
      if (stationMarkers[stn.id]) {
        stationMarkers[stn.id].setLatLng([ll.lat, ll.lon]);
        stationMarkers[stn.id].setTooltipContent(markerTip(stn));
      }
    });
    const note = document.getElementById("d5-pos-note");
    if (note) {
      note.textContent = pos === "highpoint"
        ? "The highest 30 m terrain cell next to each station point (19 to 49 m away), eye 1.6 m above it. The uncertainty layers stay on the recorded point."
        : "The MLP station point, eye 1.6 m above its 30 m terrain cell.";
    }
    loadScenarioRaster(currentScenario, updateCumulativeViewshed);
    updateProfile();
    if (typeof currentStationId !== "undefined" && currentStationId) openStation(currentStationId);
  }

  function initControls() {
    // 1. Station toggles (6 buttons)
    const stnBtns = document.querySelectorAll(".stn-toggle");
    stnBtns.forEach((btn) => {
      btn.addEventListener("click", function () {
        const sid = Number(this.getAttribute("data-stn"));
        stationActive[sid] = !stationActive[sid];
        this.setAttribute("aria-pressed", stationActive[sid] ? "true" : "false");
        updateCumulativeViewshed();
      });
    });

    // "All on" & "All off" buttons
    const btnAll = document.getElementById("d5-btn-all");
    if (btnAll) {
      btnAll.addEventListener("click", function () {
        STATIONS.forEach((s) => {
          stationActive[s.id] = true;
        });
        stnBtns.forEach((b) => b.setAttribute("aria-pressed", "true"));
        updateCumulativeViewshed();
      });
    }

    const btnNone = document.getElementById("d5-btn-none");
    if (btnNone) {
      btnNone.addEventListener("click", function () {
        STATIONS.forEach((s) => {
          stationActive[s.id] = false;
        });
        stnBtns.forEach((b) => b.setAttribute("aria-pressed", "false"));
        updateCumulativeViewshed();
      });
    }

    // 2. Scenario selector (.seg)
    const scenBtns = document.querySelectorAll("#d5-scenarios button");
    scenBtns.forEach((btn) => {
      btn.addEventListener("click", function () {
        scenBtns.forEach((b) => b.setAttribute("aria-pressed", "false"));
        this.setAttribute("aria-pressed", "true");
        currentScenario = this.getAttribute("data-scen");
        loadScenarioRaster(currentScenario, updateCumulativeViewshed);
      });
    });

    // 2b. Observer position (D93)
    const posBtns = document.querySelectorAll("#d5-pos-btns button");
    posBtns.forEach((btn) => {
      btn.addEventListener("click", function () {
        posBtns.forEach((b) => b.setAttribute("aria-pressed", "false"));
        this.setAttribute("aria-pressed", "true");
        setPosition(this.getAttribute("data-pos"));
      });
    });

    // 3. Base layer selector (.seg)
    const layerBtns = document.querySelectorAll("#d5-layer-btns button");
    layerBtns.forEach((btn) => {
      btn.addEventListener("click", function () {
        const lyr = this.getAttribute("data-layer");
        switchBaseLayer(lyr);
      });
    });

    // 4. Kenow fire checkbox
    const chkFire = document.getElementById("d5-chk-fire");
    if (chkFire) {
      chkFire.addEventListener("change", function () {
        if (!fireLayer) return;
        if (this.checked) {
          map.addLayer(fireLayer);
        } else {
          map.removeLayer(fireLayer);
        }
      });
    }

    // 5. All peaks checkbox
    const chkPeaks = document.getElementById("d5-chk-peaks");
    if (chkPeaks) {
      chkPeaks.addEventListener("change", function () {
        renderPeakMarkers(this.checked);
      });
    }

    // 6. Uncertainty station select & mode selector
    const selUncStn = document.getElementById("d5-unc-station");
    if (selUncStn) {
      selUncStn.addEventListener("change", function () {
        currentUncStation = Number(this.value);
        if (currentUncMode !== "cumul") {
          updateUncertaintyLayer();
        }
      });
    }

    const uncModeBtns = document.querySelectorAll("#d5-unc-mode button");
    uncModeBtns.forEach((btn) => {
      btn.addEventListener("click", function () {
        uncModeBtns.forEach((b) => b.setAttribute("aria-pressed", "false"));
        this.setAttribute("aria-pressed", "true");
        currentUncMode = this.getAttribute("data-mode");
        updateUncertaintyLayer();
      });
    });

    // 7. Profile controls
    if (elProfFrom) {
      elProfFrom.addEventListener("change", updateProfile);
    }
    if (elProfTo) {
      elProfTo.addEventListener("change", updateProfile);
    }

    const btnSwap = document.getElementById("d5-prof-swap");
    if (btnSwap) {
      btnSwap.addEventListener("click", function () {
        const toVal = elProfTo.value;
        if (toVal.indexOf("stn_") === 0) {
          const tgtId = toVal.replace("stn_", "");
          const fromId = elProfFrom.value;
          elProfFrom.value = tgtId;
          elProfTo.value = "stn_" + fromId;
          updateProfile();
        }
      });
    }
  }

  // Start initialization when DOM is loaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadAllData);
  } else {
    loadAllData();
  }
})();
