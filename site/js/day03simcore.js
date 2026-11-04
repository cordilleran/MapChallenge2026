/* Day 3 (Polygons), second take: a MAUP lab on simulated worlds.
   Pure functions, no DOM: runs in the page, in a Web Worker and under node (tests).
   Decisions D56 to D58 in the project's decision log. Code: MIT; see the repo README. */
(function (root) {
  "use strict";

  const N = 256;            // cells per side (51.2 km); under 100,000 cells keeps the worker quick
  const CELL = 0.2;         // km per cell (200 m)
  const NC = N * N;

  // ---------- random numbers ----------
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function normalGen(rand) {
    let spare = null;
    return function () {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let u = 0; while (u === 0) u = rand();
      const v = rand();
      const m = Math.sqrt(-2 * Math.log(u));
      spare = m * Math.sin(2 * Math.PI * v);
      return m * Math.cos(2 * Math.PI * v);
    };
  }
  // derive independent sub-seeds from one seed and a label
  function subSeed(seed, label) {
    let h = (seed >>> 0) ^ 0x9e3779b9;
    for (let i = 0; i < label.length; i++) { h = Math.imul(h ^ label.charCodeAt(i), 0x85ebca6b); h ^= h >>> 13; }
    return h >>> 0;
  }

  // ---------- FFT (radix 2, in place) ----------
  function fft1(re, im, off, stride, n, inv) {
    // bit reversal
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        const a = off + i * stride, b = off + j * stride;
        let t = re[a]; re[a] = re[b]; re[b] = t;
        t = im[a]; im[a] = im[b]; im[b] = t;
      }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = (inv ? 2 : -2) * Math.PI / len;
      const wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let k = 0; k < len / 2; k++) {
          const a = off + (i + k) * stride, b = off + (i + k + len / 2) * stride;
          const xr = re[b] * cr - im[b] * ci, xi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - xr; im[b] = im[a] - xi;
          re[a] += xr; im[a] += xi;
          const nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr;
        }
      }
    }
  }
  function fft2(re, im, inv) {
    for (let r = 0; r < N; r++) fft1(re, im, r * N, 1, N, inv);
    for (let c = 0; c < N; c++) fft1(re, im, c, N, N, inv);
  }

  // ---------- Matérn covariance ----------
  // rho is the scale parameter in km; nu in {0.5, 1.5, 2.5} (closed forms).
  function matern(h, rho, nu) {
    const d = h / rho;
    if (nu === 0.5) return Math.exp(-d);
    if (nu === 1.5) { const a = Math.sqrt(3) * d; return (1 + a) * Math.exp(-a); }
    const a = Math.sqrt(5) * d; return (1 + a + a * a / 3) * Math.exp(-a);
  }
  // distance (km) at which correlation falls to 0.05
  function practicalRange(rho, nu) {
    let lo = 0, hi = 50 * rho;
    for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (matern(m, rho, nu) > 0.05) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }
  // covariance on the torus, by lag (i, j), unit sill
  function torusCov(rho, nu) {
    const c = new Float64Array(NC);
    for (let i = 0; i < N; i++) {
      const di = Math.min(i, N - i) * CELL;
      for (let j = 0; j < N; j++) {
        const dj = Math.min(j, N - j) * CELL;
        c[i * N + j] = matern(Math.hypot(di, dj), rho, nu);
      }
    }
    return c;
  }
  const specCache = new Map();
  // square roots of the circulant eigenvalues, scaled for the forward transform
  function spectrum(rho, nu) {
    const key = rho + "|" + nu;
    if (specCache.has(key)) return specCache.get(key);
    const re = torusCov(rho, nu), im = new Float64Array(NC);
    fft2(re, im, false);
    const s = new Float64Array(NC);
    for (let k = 0; k < NC; k++) s[k] = Math.sqrt(Math.max(re[k], 0) / NC);
    if (specCache.size > 12) specCache.clear();
    specCache.set(key, s);
    return s;
  }
  // two independent zero-mean unit-sill Gaussian fields with Matérn covariance (Dietrich and Newsam 1993)
  function grfPair(rho, nu, normal) {
    const s = spectrum(rho, nu);
    const re = new Float64Array(NC), im = new Float64Array(NC);
    for (let k = 0; k < NC; k++) { re[k] = s[k] * normal(); im[k] = s[k] * normal(); }
    fft2(re, im, false);
    return [re, im];
  }

  // ---------- small statistics ----------
  function meanOf(a, mask) {
    let s = 0, n = 0;
    for (let k = 0; k < a.length; k++) if (!mask || mask[k]) { s += a[k]; n++; }
    return n ? s / n : NaN;
  }
  // mean of v over the cells in idx, read in place (same order and sums as meanOf on a copy)
  function meanAt(v, idx) {
    let s = 0;
    for (let k = 0; k < idx.length; k++) s += v[idx[k]];
    return idx.length ? s / idx.length : NaN;
  }
  function sdOf(a) {
    const m = meanOf(a); let s = 0;
    for (let k = 0; k < a.length; k++) s += (a[k] - m) * (a[k] - m);
    return Math.sqrt(s / a.length);
  }
  function pearson(x, y) {
    const n = x.length; if (n < 3) return NaN;
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
    mx /= n; my /= n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) { const a = x[i] - mx, b = y[i] - my; sxy += a * b; sxx += a * a; syy += b * b; }
    return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : NaN;
  }
  function ranks(x) {
    const idx = x.map((v, i) => i).sort((a, b) => x[a] - x[b]);
    const r = new Array(x.length);
    for (let i = 0; i < idx.length;) {
      let j = i; while (j + 1 < idx.length && x[idx[j + 1]] === x[idx[i]]) j++;
      for (let k = i; k <= j; k++) r[idx[k]] = (i + j) / 2;
      i = j + 1;
    }
    return r;
  }
  const spearman = (x, y) => pearson(ranks(x), ranks(y));
  const logistic = (z) => 1 / (1 + Math.exp(-z));
  // piecewise-linear membership through (x, y) knots
  function ramp(x, knots) {
    if (x <= knots[0][0]) return knots[0][1];
    for (let i = 1; i < knots.length; i++) {
      if (x <= knots[i][0]) {
        const [x0, y0] = knots[i - 1], [x1, y1] = knots[i];
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
      }
    }
    return knots[knots.length - 1][1];
  }

  // ---------- worlds ----------
  const TEXTBOOK_DEFAULTS = { rhoShort: 0.6, rhoLong: 4, nu: 1.5, longShare: 0.3, corShort: -0.8, corLong: 0.8, nugget: 0.15, marginal: "normal" };
  const WATERSHED_DEFAULTS = { demRes: 200, streamKm2: 1, rough: 1 };

  function standardize(a) {
    const m = meanOf(a), s = sdOf(a) || 1;
    for (let k = 0; k < a.length; k++) a[k] = (a[k] - m) / s;
    return a;
  }

  // Textbook: X and Y from a short and a long shared component, each with its own X-Y correlation, plus a nugget.
  function textbookWorld(seed, p) {
    p = Object.assign({}, TEXTBOOK_DEFAULTS, p || {});
    const normal = normalGen(mulberry32(subSeed(seed, "textbook")));
    const [sx, sz] = grfPair(p.rhoShort, p.nu, normal);
    const [lx, lz] = grfPair(p.rhoLong, p.nu, normal);
    const X = new Float64Array(NC), Y = new Float64Array(NC);
    const ws = Math.sqrt(1 - p.longShare), wl = Math.sqrt(p.longShare);
    const cs = p.corShort, cl = p.corLong;
    const rs = Math.sqrt(1 - cs * cs), rl = Math.sqrt(1 - cl * cl);
    const sig = Math.sqrt(1 - p.nugget), nug = Math.sqrt(p.nugget);
    for (let k = 0; k < NC; k++) {
      const sy = cs * sx[k] + rs * sz[k];
      const ly = cl * lx[k] + rl * lz[k];
      X[k] = sig * (ws * sx[k] + wl * lx[k]) + nug * normal();
      Y[k] = sig * (ws * sy + wl * ly) + nug * normal();
    }
    const out = { kind: "textbook", seed, params: p, layers: {}, pop: { all: null } };
    if (p.marginal === "lognormal") {
      const t = (v) => Math.exp(0.5 * v);
      for (let k = 0; k < NC; k++) { X[k] = t(X[k]); Y[k] = t(Y[k]); }
    }
    out.layers.X = X; out.layers.Y = Y;
    return out;
  }

  // ---- hydrology helpers (non-periodic: the window edge is the outlet) ----
  const DX = [-1, 0, 1, -1, 1, -1, 0, 1], DY = [-1, -1, -1, 0, 0, 1, 1, 1];
  const DD = [Math.SQRT2, 1, Math.SQRT2, 1, 1, Math.SQRT2, 1, Math.SQRT2];

  // binary min-heap on (key, value)
  function Heap(cap) { this.k = new Float64Array(cap); this.v = new Int32Array(cap); this.n = 0; }
  Heap.prototype.push = function (key, val) {
    let i = this.n++; const k = this.k, v = this.v;
    while (i > 0) { const p = (i - 1) >> 1; if (k[p] <= key) break; k[i] = k[p]; v[i] = v[p]; i = p; }
    k[i] = key; v[i] = val;
  };
  Heap.prototype.pop = function () {
    const k = this.k, v = this.v, top = v[0];
    const key = k[--this.n], val = v[this.n];
    let i = 0;
    for (;;) {
      let c = 2 * i + 1; if (c >= this.n) break;
      if (c + 1 < this.n && k[c + 1] < k[c]) c++;
      if (k[c] >= key) break;
      k[i] = k[c]; v[i] = v[c]; i = c;
    }
    k[i] = key; v[i] = val;
    return top;
  };

  // River network by invasion percolation (Stark 1991): grow a spanning tree from one outlet, always
  // invading the open neighbour of lowest "resistance". Each cell's parent is where its water goes.
  function growNetwork(resist, outlet) {
    const parent = new Int32Array(NC).fill(-1), seen = new Uint8Array(NC), order = new Int32Array(NC), h = new Heap(8 * NC);
    let m = 0; seen[outlet] = 1; h.push(resist[outlet], outlet);
    while (h.n) {
      const c = h.pop(); order[m++] = c;
      const cx = c % N, cy = (c / N) | 0;
      for (let d = 0; d < 8; d++) {
        const x = cx + DX[d], y = cy + DY[d];
        if (x < 0 || y < 0 || x >= N || y >= N) continue;
        const n = y * N + x; if (seen[n]) continue;
        seen[n] = 1; parent[n] = c; h.push(resist[n], n);
      }
    }
    return { parent, order };            // order: outlet first, every cell after its parent
  }
  function boxBlur(a, r) {
    const t = new Float64Array(NC), o = new Float64Array(NC);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      let s = 0, n = 0; for (let i = Math.max(0, x - r); i <= Math.min(N - 1, x + r); i++) { s += a[y * N + i]; n++; }
      t[y * N + x] = s / n;
    }
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      let s = 0, n = 0; for (let j = Math.max(0, y - r); j <= Math.min(N - 1, y + r); j++) { s += t[j * N + x]; n++; }
      o[y * N + x] = s / n;
    }
    return o;
  }
  // drainage area (km2) down the tree, and elevations up it from Flint's law S = k A^-theta
  function buildRelief(net, strength) {
    const { parent, order } = net, area = new Float64Array(NC).fill(CELL * CELL);
    for (let i = NC - 1; i > 0; i--) { const c = order[i]; area[parent[c]] += area[c]; }
    const z = new Float64Array(NC);
    for (let i = 1; i < NC; i++) {
      const c = order[i], p = parent[c], step = (Math.abs(p - c) === 1 || Math.abs(p - c) === N ? 1 : Math.SQRT2) * CELL * 1000;
      z[c] = z[p] + step * Math.min(0.7, 0.12 * strength[c] * Math.pow(area[c], -0.45));
    }
    return { area, z };
  }

  // the DEM as a coarser survey would see it: block means of b by b cells, bilinear back to 200 m
  function demAt(z, b) {
    if (b <= 1) return z;
    const M = N / b, cz = new Float64Array(M * M);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) cz[((y / b) | 0) * M + ((x / b) | 0)] += z[y * N + x];
    for (let k = 0; k < M * M; k++) cz[k] /= b * b;
    const at = (x, y) => cz[Math.min(M - 1, Math.max(0, y)) * M + Math.min(M - 1, Math.max(0, x))];
    const out = new Float64Array(NC);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const fx = (x + 0.5) / b - 0.5, fy = (y + 0.5) / b - 0.5, x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx - x0, ty = fy - y0;
      out[y * N + x] = (1 - ty) * ((1 - tx) * at(x0, y0) + tx * at(x0 + 1, y0)) + ty * ((1 - tx) * at(x0, y0 + 1) + tx * at(x0 + 1, y0 + 1));
    }
    return out;
  }
  // hillslope (percent), Horn's method on the DEM at the chosen resolution
  function slopeAt(zs) {
    const h = CELL * 1000, s = new Float64Array(NC);
    const at = (x, y) => zs[Math.min(N - 1, Math.max(0, y)) * N + Math.min(N - 1, Math.max(0, x))];
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const gx = ((at(x + 1, y - 1) + 2 * at(x + 1, y) + at(x + 1, y + 1)) - (at(x - 1, y - 1) + 2 * at(x - 1, y) + at(x - 1, y + 1))) / (8 * h);
      const gy = ((at(x - 1, y + 1) + 2 * at(x, y + 1) + at(x + 1, y + 1)) - (at(x - 1, y - 1) + 2 * at(x, y - 1) + at(x + 1, y - 1))) / (8 * h);
      s[y * N + x] = 100 * Math.hypot(gx, gy);
    }
    return s;
  }
  // channel slope (percent): drop over about 1 km downstream along the flow path, on the chosen DEM
  function channelSlope(zs, rec, c) {
    let k = c, len = 0;
    for (let i = 0; i < 5 && rec[k] >= 0; i++) { const r = rec[k]; len += (Math.abs(r - k) === 1 || Math.abs(r - k) === N ? 1 : Math.SQRT2) * CELL * 1000; k = r; }
    return len > 0 ? Math.max(0.05, 100 * (zs[c] - zs[k]) / len) : 0.05;
  }

  // BEC-like zones from elevation and moisture (simulated; real BEC is mapped from vegetation and climate)
  const BEC = [
    { code: "IDF", name: "dry valley Douglas-fir (IDF-like)", veg: 0.6 },
    { code: "ICH", name: "wet valley cedar-hemlock (ICH-like)", veg: 1.0 },
    { code: "MS", name: "dry montane spruce (MS-like)", veg: 0.7 },
    { code: "ESSF", name: "subalpine fir (ESSF-like)", veg: 0.4 },
    { code: "AT", name: "alpine tundra (AT-like)", veg: 0.0 },
  ];
  function becOf(elev, moist) {
    if (elev > 2150) return 4;
    if (elev > 1650) return 3;
    if (elev > 1250 && moist < 0.3) return 2;
    return moist >= 0 ? 1 : 0;
  }

  // the toy dam capacity rule, after BRAT's lines of evidence (Macfarlane and colleagues 2017)
  const RULE = {
    slope: [[2, 1], [6, 0.5], [12, 0.1], [15, 0]],         // percent
    power: [[150, 1], [300, 0.6], [600, 0]],                // stream power at Q2, W per m
    low: [[0.05, 0], [0.3, 1]],                              // low-flow index, m3/s
    maxDams: 30,                                             // dams per km at full membership
  };
  function damCapacity(slopePct, q2, lowFlow, veg) {
    const power = 9810 * q2 * slopePct / 100;
    return RULE.maxDams * ramp(slopePct, RULE.slope) * ramp(power, RULE.power) * ramp(lowFlow, RULE.low) * veg;
  }
  // Budyko curve (Fu's form, w = 2.6): runoff ratio from precipitation and potential evaporation
  function runoffRatio(p, pet) {
    const phi = pet / p, w = 2.6;
    const et = 1 + phi - Math.pow(1 + Math.pow(phi, w), 1 / w);
    return Math.max(0, 1 - et);
  }
  const q2Of = (areaKm2, pmm) => 0.47 * Math.pow(areaKm2, 0.75) * (pmm / 1000);   // regional-curve shape, m3/s
  const petOf = (elev) => Math.max(200, 650 - 0.2 * (elev - 1000));                   // mm per year

  function watershedWorld(seed, p) {
    p = Object.assign({}, WATERSHED_DEFAULTS, p || {});
    const normal = normalGen(mulberry32(subSeed(seed, "watershed")));
    const [eLong, moist0] = grfPair(5, 2.5, normal);
    const [eShort, geo0] = grfPair(0.8, 1.5, normal);
    const [mWide] = grfPair(8, 2.5, normal);
    const moist = new Float64Array(NC), geo = new Float64Array(NC), resist = new Float64Array(NC), strength = new Float64Array(NC);
    // a rough resistance field steers where the network grows; a smooth "rock strength" field steepens some ground
    const rnd = mulberry32(subSeed(seed, "percolation"));
    for (let k = 0; k < NC; k++) {
      resist[k] = 0.8 * eLong[k] + 0.45 * eShort[k] + 0.12 * rnd();
      strength[k] = Math.exp(0.35 * p.rough * eLong[k]);
      moist[k] = 0.6 * mWide[k] + 0.8 * moist0[k];
      geo[k] = geo0[k];
    }
    const outlet = (N - 1) * N + (N >> 1);                          // the middle of the south edge
    const net = growNetwork(resist, outlet), relief = buildRelief(net, strength);
    // soften hillslopes (two 3 by 3 box passes, about 200 m); valleys cut by the network survive it
    const elev = boxBlur(boxBlur(relief.z, 1), 1);
    for (let k = 0; k < NC; k++) elev[k] += 650;
    const rec = net.parent, acc = { order: net.order, area: relief.area };
    // order for accumulation passes must be upstream first
    acc.order = Int32Array.from(net.order).reverse();
    const dem = demAt(elev, Math.max(1, Math.round(p.demRes / 200)));
    const slope = slopeAt(dem), chslope = new Float64Array(NC).fill(NaN);
    const precip = new Float64Array(NC), snow = new Float64Array(NC), rr = new Float64Array(NC);
    const bfi = new Float64Array(NC), bec = new Int32Array(NC);
    const stream = new Uint8Array(NC), dams = new Float64Array(NC).fill(NaN), pwr = new Float64Array(NC).fill(NaN);
    for (let k = 0; k < NC; k++) {
      precip[k] = 750 * Math.exp(0.6 * (elev[k] - 1450) / 1000 + 0.22 * moist[k]);
      snow[k] = 0.1 + 0.8 * logistic((elev[k] - 1350) / 180);
      rr[k] = runoffRatio(precip[k], petOf(elev[k]));
      bfi[k] = 0.85 * logistic(0.3 + 0.9 * geo[k] + 0.6 * (snow[k] - 0.5));
      bec[k] = becOf(elev[k], moist[k]);
    }
    // basin-mean precipitation for each cell's contributing area (upstream first)
    const pArea = new Float64Array(NC), bArea = new Float64Array(NC);
    for (let k = 0; k < NC; k++) { pArea[k] = precip[k] * CELL * CELL; bArea[k] = bfi[k] * CELL * CELL; }
    for (let i = 0; i < NC; i++) { const c = acc.order[i], r = rec[c]; if (r >= 0) { pArea[r] += pArea[c]; bArea[r] += bArea[c]; } }
    const q2 = new Float64Array(NC), qlow = new Float64Array(NC);
    for (let k = 0; k < NC; k++) {
      const A = acc.area[k], pm = pArea[k] / A, bm = bArea[k] / A;
      q2[k] = q2Of(A, pm);
      qlow[k] = 0.06 * bm * A * (pm / 1000);            // a low-flow index scaled by basin BFI
      if (A >= p.streamKm2) {
        stream[k] = 1;
        chslope[k] = channelSlope(dem, rec, k);
        pwr[k] = 9810 * q2[k] * chslope[k] / 100;
        dams[k] = damCapacity(chslope[k], q2[k], qlow[k], BEC[bec[k]].veg);
      }
    }
    return {
      kind: "watershed", seed, params: p,
      layers: { elev, precip, snow, runoff: rr, bfi, slope, chslope, dams, power: pwr },
      inputs: { q2, qlow, becVeg: Float64Array.from(bec, (b) => BEC[b].veg) },
      bec, stream, rec, order: acc.order, area: acc.area,
      pop: { all: null, stream },
    };
  }

  const VARIABLES = {
    textbook: [
      { id: "X", label: "X", unit: "", pop: "all" },
      { id: "Y", label: "Y", unit: "", pop: "all" },
    ],
    watershed: [
      { id: "elev", label: "elevation", unit: "m", pop: "all", digits: 0 },
      { id: "precip", label: "precipitation", unit: "mm/yr", pop: "all", digits: 0 },
      { id: "snow", label: "snow fraction", unit: "", pop: "all", digits: 2 },
      { id: "runoff", label: "runoff ratio (Budyko)", unit: "", pop: "all", digits: 2 },
      { id: "bfi", label: "baseflow index", unit: "", pop: "all", digits: 2 },
      { id: "slope", label: "hillslope", unit: "%", pop: "all", digits: 1 },
      { id: "chslope", label: "channel slope", unit: "%", pop: "stream", digits: 1 },
      { id: "dams", label: "dam capacity", unit: "dams/km", pop: "stream", digits: 1 },
    ],
  };
  function makeWorld(kind, seed, params) {
    return kind === "watershed" ? watershedWorld(seed, params) : textbookWorld(seed, params);
  }

  // ---------- polygon frames: each returns {id: Int32Array per cell, nz} ----------
  function compact(raw) {
    const map = new Map(), id = new Int32Array(NC);
    for (let k = 0; k < NC; k++) {
      const r = raw[k];
      if (r === -1) { id[k] = -1; continue; }
      let z = map.get(r); if (z === undefined) { z = map.size; map.set(r, z); }
      id[k] = z;
    }
    return { id, nz: map.size };
  }
  // offsets (ox, oy) in km; size s in km
  function gridFrame(s, ox, oy) {
    const raw = new Array(NC);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const gx = Math.floor(((x + 0.5) * CELL + ox) / s), gy = Math.floor(((y + 0.5) * CELL + oy) / s);
      raw[y * N + x] = gx * 100003 + gy;
    }
    return compact(raw);
  }
  // pointy-top hexagons of equal area to an s by s square: R = s * sqrt(2 / (3 sqrt 3))
  function hexFrame(s, ox, oy) {
    const R = s * Math.sqrt(2 / (3 * Math.sqrt(3))), raw = new Array(NC);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const px = (x + 0.5) * CELL + ox, py = (y + 0.5) * CELL + oy;
      const q = (Math.sqrt(3) / 3 * px - py / 3) / R, r = (2 / 3 * py) / R;
      let cx = q, cz = r, cy = -q - r;
      let rx = Math.round(cx), ry = Math.round(cy), rz = Math.round(cz);
      const ddx = Math.abs(rx - cx), ddy = Math.abs(ry - cy), ddz = Math.abs(rz - cz);
      if (ddx > ddy && ddx > ddz) rx = -ry - rz; else if (ddy > ddz) ry = -rx - rz; else rz = -rx - ry;
      raw[y * N + x] = rx * 100003 + rz;
    }
    return compact(raw);
  }
  // nearest-seed zones; seeds as cell indices
  function voronoiFrame(seeds) {
    if (!seeds.length) return { id: new Int32Array(NC).fill(-1), nz: 0 };
    const B = 16, nb = N / B, buckets = Array.from({ length: nb * nb }, () => []);
    seeds.forEach((c, i) => { const x = c % N, y = (c / N) | 0; buckets[((y / B) | 0) * nb + ((x / B) | 0)].push(i); });
    const sx = seeds.map((c) => c % N), sy = seeds.map((c) => (c / N) | 0);
    const raw = new Int32Array(NC);
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const bx = (x / B) | 0, by = (y / B) | 0;
      let best = Infinity, bi = -1;
      for (let ring = 0; ring <= nb; ring++) {
        for (let j = by - ring; j <= by + ring; j++) for (let i = bx - ring; i <= bx + ring; i++) {
          if (i < 0 || j < 0 || i >= nb || j >= nb) continue;
          if (Math.max(Math.abs(i - bx), Math.abs(j - by)) !== ring) continue;
          for (const s of buckets[j * nb + i]) {
            const d = (sx[s] - x) ** 2 + (sy[s] - y) ** 2;
            if (d < best || (d === best && s < bi)) { best = d; bi = s; }
          }
        }
        // once a seed is found, one more ring guarantees the nearest
        if (bi >= 0 && (ring * B - B) ** 2 > best) break;
      }
      raw[y * N + x] = bi;
    }
    return compact(raw);
  }
  function randomSeeds(s, seed) {
    const rand = mulberry32(subSeed(seed, "vor")), area = (N * CELL) ** 2;
    const n = Math.max(2, Math.round(area / (s * s))), out = [];
    for (let i = 0; i < n; i++) out.push(Math.floor(rand() * N) * N + Math.floor(rand() * N));
    return out;
  }
  // sub-basins: one zone per stream segment at the drainage-area threshold, plus one per edge outlet
  function basinFrame(world, thrKm2) {
    const { rec, order, area } = world;
    const st = new Uint8Array(NC);
    for (let k = 0; k < NC; k++) st[k] = area[k] >= thrKm2 ? 1 : 0;
    const donors = new Int32Array(NC), lastDonor = new Int32Array(NC).fill(-1);
    for (let k = 0; k < NC; k++) if (st[k] && rec[k] >= 0 && st[rec[k]]) { donors[rec[k]]++; lastDonor[rec[k]] = k; }
    const seg = new Int32Array(NC).fill(-1);
    let next = 0;
    for (let i = 0; i < NC; i++) {
      const c = order[i]; if (!st[c]) continue;
      seg[c] = donors[c] === 1 ? seg[lastDonor[c]] : next++;
    }
    const raw = new Int32Array(NC).fill(-1);
    for (let i = NC - 1; i >= 0; i--) {             // downstream first
      const c = order[i];
      if (st[c]) raw[c] = seg[c];
      else if (rec[c] < 0) raw[c] = next + edgeStrip(c, thrKm2); // slivers draining off the map, grouped in strips
      else raw[c] = raw[rec[c]];
    }
    return compact(raw);
  }
  // position along the boundary, cut into strips about as long as a basin of the threshold area is wide
  function edgeStrip(c, thrKm2) {
    const x = c % N, y = (c / N) | 0;
    const p = y === 0 ? x : x === N - 1 ? N + y : y === N - 1 ? 2 * N + (N - 1 - x) : 3 * N + (N - 1 - y);
    const L = Math.max(4, Math.round(Math.sqrt(thrKm2) / CELL));
    return 1 + Math.floor(p / L);
  }
  function becFrame(world) { return compact(Int32Array.from(world.bec)); }

  function makeFrame(world, f, sampleIdx) {
    switch (f.kind) {
      case "grid": return gridFrame(f.size, f.ox, f.oy);
      case "hex": return hexFrame(f.size, f.ox, f.oy);
      case "vor": return voronoiFrame(randomSeeds(f.size, f.vseed));
      case "svor": return voronoiFrame(sampleIdx && sampleIdx.length ? Array.from(sampleIdx) : []);
      case "basin": return basinFrame(world, f.basinKm2);
      case "bec": return becFrame(world);
    }
    throw new Error("unknown frame " + f.kind);
  }

  // ---------- sampling ----------
  // population: cells where the variable is defined
  function population(world, varId) {
    const v = VARIABLES[world.kind].find((d) => d.id === varId);
    const m = v && v.pop === "stream" ? world.pop.stream : null;
    const idx = [];
    for (let k = 0; k < NC; k++) if (!m || m[k]) idx.push(k);
    return Int32Array.from(idx);
  }
  // preference covariate: watershed = access (low and near streams); textbook = the X field itself
  function prefScore(world) {
    if (world.kind === "watershed") {
      const z = Float64Array.from(world.layers.elev);
      return standardize(z).map((v) => -v);
    }
    return standardize(Float64Array.from(world.layers.X));
  }
  function drawSample(world, pop, frame, s) {
    const rand = mulberry32(subSeed(s.seed, "sample"));
    const n = Math.min(s.n, pop.length);
    if (s.design === "census") return pop;
    if (s.design === "random") {
      if (!s.beta) {                                     // partial Fisher-Yates
        const a = Int32Array.from(pop);
        for (let i = 0; i < n; i++) { const j = i + Math.floor(rand() * (a.length - i)); const t = a[i]; a[i] = a[j]; a[j] = t; }
        return a.slice(0, n);
      }
      // weighted without replacement, weight exp(beta z) (Efraimidis and Spirakis 2006): keys log(u) / w
      const z = prefScore(world), keys = new Float64Array(pop.length);
      for (let i = 0; i < pop.length; i++) keys[i] = Math.log(rand()) / Math.exp(s.beta * z[pop[i]]);
      const ord = Array.from(pop.keys()).sort((a, b) => keys[b] - keys[a]);
      return Int32Array.from(ord.slice(0, n), (i) => pop[i]);
    }
    if (s.design === "systematic") {
      // a square lattice with a random start, each point snapped to the nearest population cell
      const inPop = new Uint8Array(NC); for (const c of pop) inPop[c] = 1;
      const frac = pop.length / NC, step = Math.max(1, Math.sqrt(NC * frac / n) / Math.sqrt(frac));
      const sx0 = rand() * step, sy0 = rand() * step, got = new Set();
      for (let y = sy0; y < N; y += step) for (let x = sx0; x < N; x += step) {
        const c = nearestIn(inPop, Math.floor(x), Math.floor(y), Math.ceil(step / 2) + 1);
        if (c >= 0) got.add(c);
      }
      return Int32Array.from(got);
    }
    if (s.design === "stratified") {
      // proportional allocation to zones by largest remainder (small zones can get none), random within
      const byZone = new Map();
      for (const c of pop) { const z = frame.id[c]; if (z < 0) continue; if (!byZone.has(z)) byZone.set(z, []); byZone.get(z).push(c); }
      const zones = Array.from(byZone.keys()), out = [];
      const alloc = zones.map((z) => n * byZone.get(z).length / pop.length);
      const take = alloc.map((a) => Math.floor(a));
      let left = n - take.reduce((a, b) => a + b, 0);
      const rem = zones.map((z, i) => i).sort((a, b) => (alloc[b] - take[b]) - (alloc[a] - take[a]));
      for (const i of rem) { if (left <= 0) break; take[i]++; left--; }
      zones.forEach((z, i) => {
        const cells = byZone.get(z), m = Math.min(take[i], cells.length);
        for (let j = 0; j < m; j++) { const r = j + Math.floor(rand() * (cells.length - j)); const t = cells[j]; cells[j] = cells[r]; cells[r] = t; out.push(cells[j]); }
      });
      return Int32Array.from(out);
    }
    throw new Error("unknown design " + s.design);
  }
  function nearestIn(mask, x, y, rmax) {
    x = Math.min(N - 1, Math.max(0, x)); y = Math.min(N - 1, Math.max(0, y));
    let best = -1, bd = Infinity;
    for (let r = 0; r <= rmax; r++) {
      for (let j = y - r; j <= y + r; j++) for (let i = x - r; i <= x + r; i++) {
        if (i < 0 || j < 0 || i >= N || j >= N) continue;
        if (Math.max(Math.abs(i - x), Math.abs(j - y)) !== r) continue;
        const c = j * N + i;
        if (mask[c]) { const d = (i - x) ** 2 + (j - y) ** 2; if (d < bd) { bd = d; best = c; } }
      }
      if (best >= 0 && (r - 1) * (r - 1) >= bd) break;
    }
    return best;
  }

  // ---------- zone summaries ----------
  // per zone: population count (weight) and the mean of v over the given cells
  function zoneStats(v, cells, frame) {
    const nz = frame.nz, sum = new Float64Array(nz), cnt = new Float64Array(nz);
    for (const c of cells) { const z = frame.id[c]; if (z < 0) continue; sum[z] += v[c]; cnt[z]++; }
    const mean = new Float64Array(nz);
    for (let z = 0; z < nz; z++) mean[z] = cnt[z] ? sum[z] / cnt[z] : NaN;
    return { mean, cnt };
  }

  // ---------- estimands ----------
  // Each returns {truth, est, census, detail}. truth: from every population cell; census: the same
  // estimator fed every cell (zoning only, no sampling); est: fed the sample.
  const ESTIMANDS = {
    mean: {
      label: "regional mean",
      needs: 1,
      run(world, ctx) {
        const v = world.layers[ctx.var], { pop, frame, sample } = ctx;
        const W = zoneStats(v, pop, frame).cnt;
        const zEst = (cells) => {
          const s = zoneStats(v, cells, frame); let num = 0, den = 0;
          for (let z = 0; z < frame.nz; z++) if (s.cnt[z]) { num += W[z] * s.mean[z]; den += W[z]; }
          return num / den;
        };
        const truth = meanAt(v, pop);
        const plain = meanAt(v, sample);
        // naive standard error of the plain sample mean, as if sites were independent
        let ss = 0; for (const c of sample) ss += (v[c] - plain) ** 2;
        const naiveSE = sample.length > 1 ? Math.sqrt(ss / (sample.length - 1) / sample.length) : NaN;
        return { truth, census: zEst(pop), est: zEst(sample), detail: { plain, naiveSE } };
      },
    },
    varshare: {
      label: "between-zone share of variance",
      needs: 1,
      run(world, ctx) {
        const v = world.layers[ctx.var], { pop, frame, sample } = ctx;
        const share = (cells) => {
          const s = zoneStats(v, cells, frame);
          const m = meanAt(v, cells);
          let st = 0, sb = 0;
          for (const c of cells) st += (v[c] - m) ** 2;
          for (let z = 0; z < frame.nz; z++) if (s.cnt[z]) sb += s.cnt[z] * (s.mean[z] - m) ** 2;
          return st > 0 ? sb / st : NaN;
        };
        const c = share(pop);
        return { truth: NaN, census: c, est: share(sample), detail: {} };
      },
    },
    corr: {
      label: "correlation across zones",
      needs: 2,
      run(world, ctx) {
        const v = world.layers[ctx.var], w = world.layers[ctx.var2], { pop, frame, sample } = ctx;
        const r = (cells) => {
          const a = zoneStats(v, cells, frame), b = zoneStats(w, cells, frame), x = [], y = [];
          for (let z = 0; z < frame.nz; z++) if (a.cnt[z]) { x.push(a.mean[z]); y.push(b.mean[z]); }
          return pearson(x, y);
        };
        const truth = pearson(Array.from(pop, (c) => v[c]), Array.from(pop, (c) => w[c]));
        return { truth, census: r(pop), est: r(sample), detail: { cellR: truth } };
      },
    },
    exceed: {
      label: "share above a threshold",
      needs: 1,
      run(world, ctx) {
        const v = world.layers[ctx.var], { pop, frame, sample, thr } = ctx;
        const W = zoneStats(v, pop, frame).cnt;
        // cell first: the share of sites above, weighted by zone; zone first: zones whose mean is above
        const shares = (cells) => {
          const s = zoneStats(v, cells, frame), above = new Float64Array(frame.nz);
          for (const c of cells) { const z = frame.id[c]; if (z >= 0 && v[c] > thr) above[z]++; }
          let cf = 0, zf = 0, den = 0;
          for (let z = 0; z < frame.nz; z++) if (s.cnt[z]) { cf += W[z] * above[z] / s.cnt[z]; zf += W[z] * (s.mean[z] > thr ? 1 : 0); den += W[z]; }
          return { cf: cf / den, zf: zf / den };
        };
        let t = 0; for (const c of pop) if (v[c] > thr) t++;
        const a = shares(pop), b = shares(sample);
        const zoneFirst = ctx.method === "zone";
        return { truth: t / pop.length, census: zoneFirst ? a.zf : a.cf, est: zoneFirst ? b.zf : b.cf, detail: { cellFirst: b.cf, zoneFirst: b.zf, censusCell: a.cf, censusZone: a.zf } };
      },
    },
    rule: {
      label: "dam capacity: rule per reach or rule on zone averages",
      needs: 0, watershedOnly: true,
      run(world, ctx) {
        // total dam capacity (dams) on the network: each stream cell is about CELL km of channel
        const { frame, sample } = ctx, pop = world.__streamPop || (world.__streamPop = population(world, "dams"));
        const L = world.layers, I = world.inputs, len = CELL;
        const W = new Float64Array(frame.nz);
        for (const c of pop) { const z = frame.id[c]; if (z >= 0) W[z]++; }
        const total = (cells, zoneFirst) => {
          const nz = frame.nz, n = new Float64Array(nz), dm = new Float64Array(nz);
          const sl = new Float64Array(nz), q = new Float64Array(nz), lo = new Float64Array(nz), vg = new Float64Array(nz);
          for (const c of cells) {
            const z = frame.id[c]; if (z < 0) continue;
            n[z]++; dm[z] += L.dams[c]; sl[z] += L.chslope[c]; q[z] += I.q2[c]; lo[z] += I.qlow[c]; vg[z] += I.becVeg[c];
          }
          let tot = 0, Ls = 0, Lall = 0;
          for (let z = 0; z < nz; z++) {
            Lall += W[z] * len;
            if (!n[z]) continue;
            const perKm = zoneFirst ? damCapacity(sl[z] / n[z], q[z] / n[z], lo[z] / n[z], vg[z] / n[z]) : dm[z] / n[z];
            tot += perKm * W[z] * len;               // the zone's channel length times its rate
            Ls += W[z] * len;
          }
          // zones with no site borrow the average rate of the sampled ones (scaled by channel length)
          return Ls > 0 ? tot * Lall / Ls : NaN;
        };
        let truth = 0; for (const c of pop) truth += L.dams[c] * len;
        const zoneFirst = ctx.method === "zone";
        return { truth, census: total(pop, zoneFirst), est: total(sample, zoneFirst), detail: { cellFirst: total(sample, false), zoneFirst: total(sample, true), censusCell: total(pop, false), censusZone: total(pop, true), km: pop.length * len } };
      },
    },
    rank: {
      label: "zone rank agreement",
      needs: 1,
      run(world, ctx) {
        const v = world.layers[ctx.var], { pop, frame, sample } = ctx;
        const t = zoneStats(v, pop, frame), s = zoneStats(v, sample, frame), a = [], b = [];
        for (let z = 0; z < frame.nz; z++) if (s.cnt[z] && t.cnt[z]) { a.push(t.mean[z]); b.push(s.mean[z]); }
        // also: does the sample pick the same top zone?
        let topT = -1, topS = -1, bt = -Infinity, bs = -Infinity;
        for (let z = 0; z < frame.nz; z++) {
          if (t.cnt[z] && t.mean[z] > bt) { bt = t.mean[z]; topT = z; }
          if (s.cnt[z] && s.mean[z] > bs) { bs = s.mean[z]; topS = z; }
        }
        return { truth: 1, census: 1, est: a.length >= 3 ? spearman(a, b) : NaN, detail: { zonesCompared: a.length, sameTop: topT === topS } };
      },
    },
  };

  // ---------- one full pass ----------
  // pre (optional, used by replicate): {pop, frame} already built for this world and frame setting
  function evaluate(world, st, pre) {
    const est = ESTIMANDS[st.estimand];
    const varId = st.estimand === "rule" ? "dams" : st.var;
    const pop = pre ? pre.pop : population(world, varId);
    let frame = st.frame.kind === "svor" ? null : pre ? pre.frame : makeFrame(world, st.frame);
    // sample Voronoi and stratified designs need each other's output; stratified with svor is not allowed
    let sample;
    if (st.frame.kind === "svor") {
      const tmp = { id: new Int32Array(NC), nz: 1 };
      sample = drawSample(world, pop, tmp, Object.assign({}, st.sample, st.sample.design === "stratified" ? { design: "random" } : {}));
      if (st.sample.design === "census") sample = drawSample(world, pop, tmp, Object.assign({}, st.sample, { design: "random" }));
      frame = makeFrame(world, st.frame, sample);
    } else {
      sample = drawSample(world, pop, frame, st.sample);
    }
    const ctx = { var: varId, var2: st.var2, pop, frame, sample, thr: st.thr, method: st.method };
    const out = est.run(world, ctx);
    out.n = sample.length; out.nz = frame.nz;
    let used = 0; const seen = new Uint8Array(frame.nz);
    for (const c of sample) { const z = frame.id[c]; if (z >= 0 && !seen[z]) { seen[z] = 1; used++; } }
    out.zonesSampled = used;
    out.frame = frame; out.sample = sample; out.pop = pop;
    return out;
  }

  // ---------- replicates: redraw one source at a time ----------
  function replicate(base, source, R, onProgress) {
    const res = [];
    let world = makeWorld(base.world, base.worldSeed, base.worldParams);
    // for "sample" the world and frame are fixed (only the site draw changes), so build them once;
    // "svor" frames come from the sites, so they are still built inside evaluate
    let pre = null;
    if (source === "sample" && base.frame.kind !== "svor") {
      pre = { pop: population(world, base.estimand === "rule" ? "dams" : base.var), frame: makeFrame(world, base.frame) };
    }
    for (let r = 0; r < R; r++) {
      const st = JSON.parse(JSON.stringify(base));
      const rr = mulberry32(subSeed(base.worldSeed + 7919 * (r + 1), source));
      if (source === "world") world = makeWorld(base.world, (base.worldSeed + 104729 * (r + 1)) >>> 0, base.worldParams);
      if (source === "sample") st.sample.seed = (base.sample.seed + 7919 * (r + 1)) >>> 0;
      if (source === "zoning") {
        st.frame.ox = rr() * st.frame.size; st.frame.oy = rr() * st.frame.size;
        st.frame.vseed = (base.frame.vseed + 15485863 * (r + 1)) >>> 0;
      }
      const o = evaluate(world, st, pre);
      res.push({ truth: o.truth, census: o.census, est: o.est, n: o.n, nz: o.nz, zonesSampled: o.zonesSampled, naiveSE: o.detail.naiveSE, plain: o.detail.plain, sameTop: o.detail.sameTop });
      if (onProgress && (r % 5 === 4 || r === R - 1)) onProgress(r + 1, R);
    }
    return res;
  }

  // ---------- theory: Krige's relation for the expected between-zone share ----------
  // E[S_B / S_T] about 1 - gbar(v) / gbar(D), gbar the mean variogram within a k by k block (v) and the
  // whole torus (D). Variogram from the textbook X: unit sill split into nugget and Matérn parts.
  function krigeShare(p, kCells) {
    p = Object.assign({}, TEXTBOOK_DEFAULTS, p || {});
    const cs = torusCov(p.rhoShort, p.nu), cl = torusCov(p.rhoLong, p.nu);
    const sig = 1 - p.nugget;
    const gamma = (i, j) => {
      if (i === 0 && j === 0) return 0;
      const k = ((i + N) % N) * N + ((j + N) % N);
      return p.nugget + sig * (1 - ((1 - p.longShare) * cs[k] + p.longShare * cl[k]));
    };
    let gD = 0; for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) gD += gamma(i, j);
    gD /= NC;
    return kCells.map((k) => {
      let g = 0;
      for (let i = -(k - 1); i <= k - 1; i++) for (let j = -(k - 1); j <= k - 1; j++) g += (k - Math.abs(i)) * (k - Math.abs(j)) * gamma(i, j);
      g /= k ** 4;
      return 1 - g / gD;
    });
  }

  // ---------- summary of a set of replicates ----------
  function summarize(res, key) {
    const e = res.map((r) => r[key]).filter(Number.isFinite);
    const err = res.filter((r) => Number.isFinite(r[key]) && Number.isFinite(r.truth)).map((r) => r[key] - r.truth);
    const m = meanOf(e), sd = Math.sqrt(meanOf(e.map((x) => (x - m) ** 2)) * e.length / Math.max(1, e.length - 1));
    const bias = err.length ? meanOf(err) : NaN;
    const rmse = err.length ? Math.sqrt(meanOf(err.map((x) => x * x))) : NaN;
    return { n: e.length, mean: m, sd, bias, rmse };
  }

  const api = {
    N, CELL, NC, mulberry32, normalGen, subSeed, fft2, matern, practicalRange, torusCov, grfPair,
    meanOf, sdOf, pearson, spearman, ranks, ramp, logistic,
    textbookWorld, watershedWorld, makeWorld, growNetwork, buildRelief, demAt, slopeAt, channelSlope, damCapacity, runoffRatio, q2Of, petOf,
    BEC, RULE, VARIABLES, TEXTBOOK_DEFAULTS, WATERSHED_DEFAULTS,
    gridFrame, hexFrame, voronoiFrame, randomSeeds, basinFrame, becFrame, makeFrame,
    population, drawSample, zoneStats, ESTIMANDS, evaluate, replicate, krigeShare, summarize,
  };
  root.D3S = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
