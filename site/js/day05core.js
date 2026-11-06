/* Day 5 (Viewsheds): pure projection, bilinear DEM sampling, and line-of-sight profile engine.
   Pure functions, no DOM: runs in the browser and under Node.js (tests).
   Code: MIT; see the repo README. */
(function (root) {
  "use strict";

  // ---------- EPSG:3979 (NAD83(CSRS) / Canada Atlas Lambert, LCC 2SP, GRS80) ----------
  // Parameters confirmed from `gdalsrsinfo EPSG:3979`:
  //   +proj=lcc +lat_0=49 +lon_0=-95 +lat_1=49 +lat_2=77 +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs
  const GRS80_A = 6378137.0;
  const GRS80_RF = 298.257222101;
  const GRS80_F = 1.0 / GRS80_RF;
  const GRS80_E2 = 2.0 * GRS80_F - GRS80_F * GRS80_F;
  const GRS80_E = Math.sqrt(GRS80_E2);

  const WGS84_A = 6378137.0;
  const WGS84_RF = 298.257223563;
  const WGS84_F = 1.0 / WGS84_RF;
  const WGS84_E2 = 2.0 * WGS84_F - WGS84_F * WGS84_F;

  const DEG2RAD = Math.PI / 180.0;
  const RAD2DEG = 180.0 / Math.PI;
  const ARCSEC2RAD = DEG2RAD / 3600.0;

  const LAT1_RAD = 49.0 * DEG2RAD;
  const LAT2_RAD = 77.0 * DEG2RAD;
  const LAT0_RAD = 49.0 * DEG2RAD;
  const LON0_RAD = -95.0 * DEG2RAD;
  const X0 = 0.0;
  const Y0 = 0.0;

  function lccM(phi) {
    const s = Math.sin(phi);
    return Math.cos(phi) / Math.sqrt(1.0 - GRS80_E2 * s * s);
  }

  function lccT(phi) {
    const es = GRS80_E * Math.sin(phi);
    return Math.tan(Math.PI * 0.25 - phi * 0.5) / Math.pow((1.0 - es) / (1.0 + es), GRS80_E * 0.5);
  }

  const M1 = lccM(LAT1_RAD);
  const M2 = lccM(LAT2_RAD);
  const T1 = lccT(LAT1_RAD);
  const T2 = lccT(LAT2_RAD);
  const T0 = lccT(LAT0_RAD);
  const LCC_N = (Math.log(M1) - Math.log(M2)) / (Math.log(T1) - Math.log(T2));
  const LCC_F = M1 / (LCC_N * Math.pow(T1, LCC_N));
  const LCC_R0 = GRS80_A * LCC_F * Math.pow(T0, LCC_N);

  // PROJ / GDAL default pipeline from EPSG:4326 (WGS 84) to EPSG:4617 (NAD83(CSRS)):
  // Inverse of "NAD83(CSRS) to WGS 84 (2)" coordinate_frame Helmert transformation:
  //   +step +inv +proj=helmert +x=-0.991 +y=1.9072 +z=0.5129
  //         +rx=-0.0257899075194932 +ry=-0.0096500989602704 +rz=-0.0116599432323421 +s=0
  //         +convention=coordinate_frame
  const HELM_DX = -0.991;
  const HELM_DY = 1.9072;
  const HELM_DZ = 0.5129;
  const HELM_RX = -0.0257899075194932 * ARCSEC2RAD;
  const HELM_RY = -0.0096500989602704 * ARCSEC2RAD;
  const HELM_RZ = -0.0116599432323421 * ARCSEC2RAD;

  function wgs84ToNad83CsrsRad(latRad, lonRad) {
    const sinLat = Math.sin(latRad), cosLat = Math.cos(latRad);
    const sinLon = Math.sin(lonRad), cosLon = Math.cos(lonRad);
    const nu = WGS84_A / Math.sqrt(1.0 - WGS84_E2 * sinLat * sinLat);
    const X = nu * cosLat * cosLon;
    const Y = nu * cosLat * sinLon;
    const Z = nu * (1.0 - WGS84_E2) * sinLat;

    // Inverse coordinate_frame Helmert: subtract translation and apply transpose rotation
    const X2 = X - HELM_DX - HELM_RZ * Y + HELM_RY * Z;
    const Y2 = Y - HELM_DY + HELM_RZ * X - HELM_RX * Z;
    const Z2 = Z - HELM_DZ - HELM_RY * X + HELM_RX * Y;

    const p = Math.hypot(X2, Y2);
    const lon2 = Math.atan2(Y2, X2);
    let lat2 = Math.atan2(Z2, p * (1.0 - GRS80_E2));
    for (let i = 0; i < 4; i++) {
      const s = Math.sin(lat2);
      const n2 = GRS80_A / Math.sqrt(1.0 - GRS80_E2 * s * s);
      lat2 = Math.atan2(Z2 + GRS80_E2 * n2 * s, p);
    }
    return { latRad: lat2, lonRad: lon2 };
  }

  /**
   * Forward projection from geographic (lat, lon in degrees) to EPSG:3979 (x, y in metres).
   * Matches `gdaltransform -s_srs EPSG:4326 -t_srs EPSG:3979` to < 0.001 m by default,
   * or pure GRS80 LCC-2SP (`gdaltransform -s_srs EPSG:4617 -t_srs EPSG:3979`) if opts.datum === "NAD83".
   */
  function projectTo3979(latDeg, lonDeg, opts) {
    let phi = latDeg * DEG2RAD;
    let lam = lonDeg * DEG2RAD;
    if (!opts || opts.datum !== "NAD83") {
      const shifted = wgs84ToNad83CsrsRad(phi, lam);
      phi = shifted.latRad;
      lam = shifted.lonRad;
    }
    const t = lccT(phi);
    const r = GRS80_A * LCC_F * Math.pow(t, LCC_N);
    const theta = LCC_N * (lam - LON0_RAD);
    const x = X0 + r * Math.sin(theta);
    const y = Y0 + LCC_R0 - r * Math.cos(theta);
    return { x, y };
  }

  /**
   * Inverse projection from EPSG:3979 (x, y in metres) to geographic (lat, lon in degrees, NAD83(CSRS)).
   */
  function unprojectFrom3979(x, y) {
    const dx = x - X0;
    const dy = LCC_R0 - (y - Y0);
    const r = Math.sign(LCC_N) * Math.hypot(dx, dy);
    const theta = Math.atan2(dx, dy);
    const t = Math.pow(r / (GRS80_A * LCC_F), 1.0 / LCC_N);
    let phi = Math.PI * 0.5 - 2.0 * Math.atan(t);
    for (let i = 0; i < 6; i++) {
      const es = GRS80_E * Math.sin(phi);
      phi = Math.PI * 0.5 - 2.0 * Math.atan(t * Math.pow((1.0 - es) / (1.0 + es), GRS80_E * 0.5));
    }
    const lam = theta / LCC_N + LON0_RAD;
    return { lat: phi * RAD2DEG, lon: lam * RAD2DEG };
  }

  // ---------- Bilinear DEM sampling on the Int16 grid ----------
  /**
   * Create a DEM wrapper from an ArrayBuffer or Int16Array and the metadata from profile_dem.json.
   */
  function createDem(int16BufferOrArray, meta) {
    const data = int16BufferOrArray instanceof Int16Array
      ? int16BufferOrArray
      : new Int16Array(int16BufferOrArray);
    const cols = meta.cols || 735;
    const rows = meta.rows || 677;
    const gt = meta.geotransform || [-1381680.0, 30.0, 0.0, 231690.0, 0.0, -30.0];
    const scale = meta.scale_to_metres !== undefined ? meta.scale_to_metres : 0.1;
    return { data, cols, rows, geotransform: gt, scale };
  }

  /**
   * Sample elevation (in metres) at EPSG:3979 (x, y) using bilinear interpolation across pixel centres.
   * Pixel centre (col, row) is at (gt[0] + (col + 0.5) * gt[1], gt[3] + (row + 0.5) * gt[5]).
   */
  function sampleDemBilinear(dem, x, y) {
    const gt = dem.geotransform;
    const cols = dem.cols, rows = dem.rows;
    const data = dem.data;
    const scale = dem.scale !== undefined ? dem.scale : 0.1;

    const u = (x - gt[0]) / gt[1] - 0.5;
    const v = (y - gt[3]) / gt[5] - 0.5;
    if (u < -0.5 || u > cols - 0.5 || v < -0.5 || v > rows - 0.5) {
      return NaN;
    }

    const c0 = Math.floor(u);
    const r0 = Math.floor(v);
    const du = u - c0;
    const dv = v - r0;

    const c0c = Math.max(0, Math.min(cols - 1, c0));
    const c1c = Math.max(0, Math.min(cols - 1, c0 + 1));
    const r0c = Math.max(0, Math.min(rows - 1, r0));
    const r1c = Math.max(0, Math.min(rows - 1, r0 + 1));

    const z00 = data[r0c * cols + c0c] * scale;
    const z10 = data[r0c * cols + c1c] * scale;
    const z01 = data[r1c * cols + c0c] * scale;
    const z11 = data[r1c * cols + c1c] * scale;

    return (1.0 - dv) * ((1.0 - du) * z00 + du * z10) + dv * ((1.0 - du) * z01 + du * z11);
  }

  /**
   * Return the grid cell centre (x, y) and cell elevation (m) for the DEM cell containing (x, y).
   */
  function snapToDemCell(dem, x, y) {
    const gt = dem.geotransform;
    const col = Math.floor((x - gt[0]) / gt[1]);
    const row = Math.floor((y - gt[3]) / gt[5]);
    if (col < 0 || col >= dem.cols || row < 0 || row >= dem.rows) return null;
    const scale = dem.scale !== undefined ? dem.scale : 0.1;
    return {
      col,
      row,
      x: gt[0] + (col + 0.5) * gt[1],
      y: gt[3] + (row + 0.5) * gt[5],
      z: dem.data[row * dem.cols + col] * scale,
    };
  }

  // ---------- Line-of-sight profile with Earth curvature & atmospheric refraction ----------
  // Exact formula from GDAL `gdal_viewshed` documentation:
  //   "{CurvCoeff} = 1 - {RefractionCoeff}"
  //   "The height of the DEM is corrected according to the following formula:
  //    Height_{Corrected} = Height_{DEM} - {CurvCoeff} \frac{{TargetDistance}^2}{SphereDiameter}"
  // With SphereDiameter = 2 * R (R = 6371008.8 m) and RefractionCoeff k = 0.13 (CurvCoeff = 0.87):
  //   drop = d^2 / (2 * R) * (1 - k)
  const EARTH_RADIUS_M = 6371008.8;
  const DEFAULT_REFRACTION_K = 0.13;
  const DEFAULT_STEP_M = 15.0;
  const DEFAULT_OBSERVER_HEIGHT_M = 1.6;

  function earthCurvatureDrop(distanceM, k, radiusM) {
    const refr = k !== undefined ? k : DEFAULT_REFRACTION_K;
    const R = radiusM !== undefined ? radiusM : EARTH_RADIUS_M;
    return ((distanceM * distanceM) / (2.0 * R)) * (1.0 - refr);
  }

  /**
   * Compute a line-of-sight profile between start (observer) and end (target) in EPSG:3979 metres.
   * Samples every `stepM` (default 15 m), applies Earth curvature + refraction drop = d^2 / (2R) * (1 - k)
   * with R = 6371008.8 m and k = 0.13, places the observer 1.6 m above the DEM at the start and the target
   * at ground (0 m), and returns:
   *   - distances: Float64Array of horizontal distances from start (m)
   *   - groundHeights: Float64Array of raw bilinear DEM ground heights (m)
   *   - correctedGroundHeights: Float64Array of curvature-corrected DEM heights (ground - drop, m)
   *   - sightLineHeights: Float64Array of minimum visible height at each sample (or ray height to target)
   *   - horizonHeights: Float64Array of running horizon height (zObs + maxSlope * d + drop, m)
   *   - targetRayHeights: Float64Array of direct start-to-end ray height (zObs + targetSlope * d + drop, m)
   *   - visible: Uint8Array of 1 (visible from observer) or 0 (occluded by an earlier ridge) per sample
   *   - targetVisible: boolean (true if the far end sample is visible)
   *
   * Note on observer position: in raster viewshed tools (GRASS `r.viewshed` and `gdal_viewshed`), the
   * observer is snapped to the centre of the DEM cell containing `(x0, y0)`. By default (`snapObserverCell: true`),
   * `losProfile` snaps the observer's elevation to its DEM cell if `(x0, y0)` is within a steep summit cell,
   * or uses exact bilinear sampling when `snapObserverCell: false`.
   */
  function losProfile(dem, x0, y0, x1, y1, opts) {
    const o = Object.assign(
      {
        stepM: DEFAULT_STEP_M,
        observerHeightM: DEFAULT_OBSERVER_HEIGHT_M,
        targetHeightM: 0.0,
        k: DEFAULT_REFRACTION_K,
        radiusM: EARTH_RADIUS_M,
        snapObserverCell: true,
      },
      opts || {}
    );

    let startX = x0, startY = y0;
    if (o.snapObserverCell) {
      const cell = snapToDemCell(dem, x0, y0);
      if (cell) {
        startX = cell.x;
        startY = cell.y;
      }
    }

    const dx = x1 - startX;
    const dy = y1 - startY;
    const totalDist = Math.hypot(dx, dy);
    const nSteps = Math.max(1, Math.ceil(totalDist / o.stepM));
    const nSamples = nSteps + 1;

    const distances = new Float64Array(nSamples);
    const groundHeights = new Float64Array(nSamples);
    const correctedGroundHeights = new Float64Array(nSamples);
    const sightLineHeights = new Float64Array(nSamples);
    const targetRayHeights = new Float64Array(nSamples);
    const xs = new Float64Array(nSamples);
    const ys = new Float64Array(nSamples);
    const visible = new Uint8Array(nSamples);

    const zStartGround = sampleDemBilinear(dem, startX, startY);
    const zObs = zStartGround + o.observerHeightM;

    let maxSlope = -Infinity;

    for (let i = 0; i < nSamples; i++) {
      const frac = totalDist > 0 ? i / nSteps : 0.0;
      const d = frac * totalDist;
      const x = startX + frac * dx;
      const y = startY + frac * dy;
      const zGround = i === 0 ? zStartGround : sampleDemBilinear(dem, x, y);
      const drop = earthCurvatureDrop(d, o.k, o.radiusM);
      const zCorr = zGround - drop;

      distances[i] = d;
      xs[i] = x;
      ys[i] = y;
      groundHeights[i] = zGround;
      correctedGroundHeights[i] = zCorr;

      if (i === 0) {
        visible[i] = 1;
        sightLineHeights[i] = zObs;
      } else {
        const targetCorr = zCorr + o.targetHeightM;
        const slopeToTarget = (targetCorr - zObs) / d;
        const slopeOfGround = (zCorr - zObs) / d;
        if (slopeToTarget >= maxSlope - 1e-12) {
          visible[i] = 1;
          sightLineHeights[i] = zGround + o.targetHeightM;
        } else {
          visible[i] = 0;
          // Height in un-dropped ground coordinates of the blocking horizon ray at distance d
          sightLineHeights[i] = zObs + maxSlope * d + drop;
        }
        if (slopeOfGround > maxSlope) {
          maxSlope = slopeOfGround;
        }
      }
    }

    // Also compute the direct line-of-sight ray from observer to the final endpoint
    const endDrop = earthCurvatureDrop(totalDist, o.k, o.radiusM);
    const endTargetCorr = correctedGroundHeights[nSamples - 1] + o.targetHeightM;
    const endSlope = totalDist > 0 ? (endTargetCorr - zObs) / totalDist : 0.0;
    for (let i = 0; i < nSamples; i++) {
      const d = distances[i];
      const drop = earthCurvatureDrop(d, o.k, o.radiusM);
      targetRayHeights[i] = zObs + endSlope * d + drop;
    }

    return {
      distances,
      groundHeights,
      correctedGroundHeights,
      sightLineHeights,
      targetRayHeights,
      visible,
      xs,
      ys,
      observerElevationM: zObs,
      totalDistanceM: totalDist,
      targetVisible: visible[nSamples - 1] === 1,
    };
  }

  const api = {
    GRS80_A,
    GRS80_RF,
    EARTH_RADIUS_M,
    DEFAULT_REFRACTION_K,
    DEFAULT_STEP_M,
    DEFAULT_OBSERVER_HEIGHT_M,
    projectTo3979,
    unprojectFrom3979,
    createDem,
    sampleDemBilinear,
    snapToDemCell,
    earthCurvatureDrop,
    losProfile,
  };

  root.D5C = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof self !== "undefined" ? self : this);
