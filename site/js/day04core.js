/* Day 4 (Clusters): clustering and space-time interaction engine for the GLM lightning night.
   Pure functions, no DOM: runs in the page, in a Web Worker and under node (tests).
   Units after load(): x, y in km (BC Albers), t in minutes from 2021-06-30 20:00 UTC.
   Code: MIT; see the repo README. */
(function (root) {
  "use strict";

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
  // in-place Fisher-Yates on any array-like; returns it
  function shuffle(arr, rand) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }
  function permutation(n, rand) {
    const p = new Int32Array(n);
    for (let i = 0; i < n; i++) p[i] = i;
    return shuffle(p, rand);
  }

  // ---------- small statistics ----------
  function median(a) {
    const n = a.length;
    if (!n) return NaN;
    const s = Array.from(a).sort((p, q) => p - q);
    return n % 2 ? s[(n - 1) / 2] : 0.5 * (s[n / 2 - 1] + s[n / 2]);
  }
  function weightedMedian(vals, w) {
    const n = vals.length;
    if (!n) return NaN;
    const idx = Array.from({ length: n }, (_, i) => i).sort((a, b) => vals[a] - vals[b]);
    let tot = 0; for (let i = 0; i < n; i++) tot += w[i];
    let acc = 0;
    for (let k = 0; k < n; k++) {
      acc += w[idx[k]];
      if (acc >= tot / 2) return vals[idx[k]];
    }
    return vals[idx[n - 1]];
  }
  // quantile of a sorted array, linear interpolation
  function quantileSorted(s, q) {
    const pos = (s.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return s[lo] + (s[hi] - s[lo]) * (pos - lo);
  }
  // least-squares slope of y on x
  function slope(xs, ys) {
    const n = xs.length;
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += xs[i]; my += ys[i]; }
    mx /= n; my /= n;
    let sxy = 0, sxx = 0;
    for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) * (xs[i] - mx); }
    return sxx > 0 ? sxy / sxx : 0;
  }

  // ---------- data ----------
  // D4GLM units: x,y 10 m; t 0.1 s; area 0.01 km2; vza, az 0.1 deg.
  function load(glm) {
    const f = glm.flash, g = glm.group, n = f.x.length, m = g.x.length;
    const x = new Float64Array(n), y = new Float64Array(n), t = new Float64Array(n);
    const area_km2 = new Float64Array(n), vza = new Float64Array(n), az = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      x[i] = f.x[i] / 100; y[i] = f.y[i] / 100; t[i] = f.t[i] / 600;
      area_km2[i] = f.area[i] * 0.01; vza[i] = f.vza[i] / 10; az[i] = f.az[i] / 10;
    }
    const gx = new Float64Array(m), gy = new Float64Array(m), gt = new Float64Array(m), gf = new Int32Array(m);
    for (let i = 0; i < m; i++) { gx[i] = g.x[i] / 100; gy[i] = g.y[i] / 100; gt[i] = g.t[i] / 600; gf[i] = g.f[i]; }
    return { x, y, t, area_km2, energy: Float64Array.from(f.energy), ng: Float64Array.from(f.ng), vza, az, gx, gy, gt, gf };
  }

  // ---------- DBSCAN in (x, y, t*tScale), matching scikit-learn ----------
  // 3D grid hash with cell size eps; neighbours are points within distance <= eps (inclusive, self included).
  function buildGrid(X, Y, Z, eps) {
    const n = X.length, cells = new Map();
    let mx = Infinity, my = Infinity, mz = Infinity;
    for (let i = 0; i < n; i++) { if (X[i] < mx) mx = X[i]; if (Y[i] < my) my = Y[i]; if (Z[i] < mz) mz = Z[i]; }
    const ix = new Int32Array(n), iy = new Int32Array(n), iz = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      ix[i] = Math.floor((X[i] - mx) / eps) + 1; iy[i] = Math.floor((Y[i] - my) / eps) + 1; iz[i] = Math.floor((Z[i] - mz) / eps) + 1;
      if (ix[i] > 131000 || iy[i] > 131000 || iz[i] > 131000) throw new Error("eps too small for the extent of the data");
      const key = cellKey(ix[i], iy[i], iz[i]);
      const c = cells.get(key);
      if (c) c.push(i); else cells.set(key, [i]);
    }
    return { cells, ix, iy, iz };
  }
  // indices are 0..131071 per axis (offset by 1 so that the -1 neighbour is valid): 2^51 keys, exact in a double
  function cellKey(a, b, c) { return (a * 131072 + b) * 131072 + c; }
  function neighbours(i, X, Y, Z, eps2, grid, out) {
    out.length = 0;
    const cx = grid.ix[i], cy = grid.iy[i], cz = grid.iz[i];
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let c = -1; c <= 1; c++) {
      const cell = grid.cells.get(cellKey(cx + a, cy + b, cz + c));
      if (!cell) continue;
      for (let q = 0; q < cell.length; q++) {
        const j = cell[q], dx = X[j] - X[i], dy = Y[j] - Y[i], dz = Z[j] - Z[i];
        if (dx * dx + dy * dy + dz * dz <= eps2) out.push(j);
      }
    }
    return out;
  }
  function dbscan(x, y, t, opts) {
    const eps = opts.eps, tScale = opts.tScale, minPts = opts.minPts, n = x.length;
    const Z = new Float64Array(n);
    for (let i = 0; i < n; i++) Z[i] = t[i] * tScale;
    const grid = buildGrid(x, y, Z, eps), eps2 = eps * eps, nb = [];
    const core = new Uint8Array(n);
    for (let i = 0; i < n; i++) core[i] = neighbours(i, x, y, Z, eps2, grid, nb).length >= minPts ? 1 : 0;
    // as sklearn's dbscan_inner: seeds in index order, stack-based expansion
    const labels = new Int32Array(n).fill(-1);
    let k = 0;
    for (let s = 0; s < n; s++) {
      if (labels[s] !== -1 || !core[s]) continue;
      const stack = [];
      let i = s;
      for (;;) {
        if (labels[i] === -1) {
          labels[i] = k;
          if (core[i]) {
            neighbours(i, x, y, Z, eps2, grid, nb);
            for (let q = 0; q < nb.length; q++) if (labels[nb[q]] === -1) stack.push(nb[q]);
          }
        }
        if (!stack.length) break;
        i = stack.pop();
      }
      k++;
    }
    return { labels, k, core };
  }

  // distance to the kth nearest OTHER point in (x, y, t*tScale), sorted ascending.
  // For the k-distance plot of DBSCAN with minPts, use k = minPts - 1 (the point itself is not counted here).
  function kdist(x, y, t, tScale, k) {
    const n = x.length, order = Array.from({ length: n }, (_, i) => i).sort((a, b) => t[a] - t[b]);
    const X = new Float64Array(n), Y = new Float64Array(n), T = new Float64Array(n);
    for (let i = 0; i < n; i++) { X[i] = x[order[i]]; Y[i] = y[order[i]]; T[i] = t[order[i]] * tScale; }
    const out = new Float64Array(n), best = new Float64Array(k);
    for (let i = 0; i < n; i++) {
      best.fill(Infinity);   // squared distances, ascending
      let l = i - 1, r = i + 1;
      for (;;) {
        const bound = best[k - 1];
        const dl = l >= 0 ? T[i] - T[l] : Infinity, dr = r < n ? T[r] - T[i] : Infinity;
        const useL = dl <= dr, dt = useL ? dl : dr;
        if (dt === Infinity || dt * dt >= bound) break;
        const j = useL ? l-- : r++;
        const dx = X[j] - X[i], dy = Y[j] - Y[i], d2 = dx * dx + dy * dy + dt * dt;
        if (d2 < bound) {
          let p = k - 1;
          while (p > 0 && best[p - 1] > d2) { best[p] = best[p - 1]; p--; }
          best[p] = d2;
        }
      }
      out[i] = Math.sqrt(best[k - 1]);
    }
    out.sort();
    return out;
  }

  // ---------- cell statistics ----------
  function cellStats(labels, k, x, y, t, area) {
    const members = Array.from({ length: k }, () => []);
    let noise = 0;
    for (let i = 0; i < labels.length; i++) { if (labels[i] < 0) noise++; else members[labels[i]].push(i); }
    const cells = [];
    for (let c = 0; c < k; c++) {
      const idx = members[c].sort((a, b) => t[a] - t[b]), n = idx.length;
      let t0 = t[idx[0]], t1 = t[idx[n - 1]], cx = 0, cy = 0, ar = 0;
      for (const i of idx) { cx += x[i]; cy += y[i]; if (area) ar += area[i]; }
      cx /= n; cy /= n;
      let ss = 0;
      for (const i of idx) ss += (x[i] - cx) * (x[i] - cx) + (y[i] - cy) * (y[i] - cy);
      const nch = Math.max(1, Math.min(8, Math.floor(n / 5))), track = [];
      for (let q = 0; q < nch; q++) {
        const a = Math.floor(q * n / nch), b = Math.floor((q + 1) * n / nch);
        let mt = 0, mx = 0, my = 0;
        for (let p = a; p < b; p++) { mt += t[idx[p]]; mx += x[idx[p]]; my += y[idx[p]]; }
        const m = b - a;
        track.push({ t: mt / m, x: mx / m, y: my / m });
      }
      const life = t1 - t0;
      cells.push({ id: c, n, t0, t1, lifetime: life, cx, cy, radius: Math.sqrt(ss / n), rate: n / Math.max(life, 1),
        meanArea: area ? ar / n : NaN, track });
    }
    return {
      cells, k, n: labels.length, noise, noiseShare: labels.length ? noise / labels.length : 0,
      medLifetime: median(cells.map((c) => c.lifetime)), medRadius: median(cells.map((c) => c.radius)),
      medRate: median(cells.map((c) => c.rate)),
    };
  }

  // ---------- self-fitted motion ----------
  // Per-cell least-squares drift of the flash positions against time (km/min * 60 = km/h);
  // median over cells weighted by n. Circular by design: the clusters were found in the ground frame.
  function fitVelocity(labels, k, x, y, t, opts) {
    const minN = (opts && opts.minN) || 10, minLife = (opts && opts.minLife) || 10;
    const members = Array.from({ length: k }, () => []);
    for (let i = 0; i < labels.length; i++) if (labels[i] >= 0) members[labels[i]].push(i);
    const us = [], vs = [], w = [];
    for (const idx of members) {
      if (idx.length < minN) continue;
      let lo = Infinity, hi = -Infinity;
      for (const i of idx) { if (t[i] < lo) lo = t[i]; if (t[i] > hi) hi = t[i]; }
      if (hi - lo < minLife) continue;
      us.push(60 * slope(idx.map((i) => t[i]), idx.map((i) => x[i])));
      vs.push(60 * slope(idx.map((i) => t[i]), idx.map((i) => y[i])));
      w.push(idx.length);
    }
    return { u: weightedMedian(us, w), v: weightedMedian(vs, w), nCells: us.length };
  }

  // ---------- Knox-style space-time interaction surface ----------
  // Counts are laid out flat as [tBin * dBins + dBin]. Pairs i<j (unordered), lag = |t_i - t_j| (min),
  // distance in the moving frame x' = x - u t/60, y' = y - v t/60 (u, v km/h).
  // Null: shuffle the times among the fixed ground locations, then transform, then count.
  function pairCounts(X, Y, T, perm, jEnd, u, v, dMax, dBins, tMax, tBins, out) {
    const n = T.length, d2max = dMax * dMax, ds = dBins / dMax, ts = tBins / tMax;
    const uk = u / 60, vk = v / 60;
    const fx = new Float64Array(n), fy = new Float64Array(n);
    for (let k = 0; k < n; k++) { const p = perm[k]; fx[k] = X[p] - uk * T[k]; fy[k] = Y[p] - vk * T[k]; }
    out.fill(0);
    // grid hash in the moving frame, cell = dMax/2, entries kept in time order; a per-cell pointer only moves forward
    const cs = dMax / 2;
    let mx = Infinity, my = Infinity, Mx = -Infinity, My = -Infinity;
    for (let k = 0; k < n; k++) {
      if (fx[k] < mx) mx = fx[k]; if (fx[k] > Mx) Mx = fx[k];
      if (fy[k] < my) my = fy[k]; if (fy[k] > My) My = fy[k];
    }
    const nx = Math.floor((Mx - mx) / cs) + 1, ny = Math.floor((My - my) / cs) + 1, ncell = nx * ny;
    const cx = new Int32Array(n), cy = new Int32Array(n), start = new Int32Array(ncell + 1), ptr = new Int32Array(ncell);
    for (let k = 0; k < n; k++) { cx[k] = Math.floor((fx[k] - mx) / cs); cy[k] = Math.floor((fy[k] - my) / cs); start[cy[k] * nx + cx[k] + 1]++; }
    for (let c = 0; c < ncell; c++) start[c + 1] += start[c];
    const list = new Int32Array(n), fill = start.slice(0, ncell);
    for (let k = 0; k < n; k++) list[fill[cy[k] * nx + cx[k]]++] = k;
    for (let c = 0; c < ncell; c++) ptr[c] = start[c];
    for (let i = 0; i < n; i++) {
      const xi = fx[i], yi = fy[i], ti = T[i], je = jEnd[i];
      const x0 = Math.max(0, cx[i] - 2), x1 = Math.min(nx - 1, cx[i] + 2), y0 = Math.max(0, cy[i] - 2), y1 = Math.min(ny - 1, cy[i] + 2);
      for (let b = y0; b <= y1; b++) for (let a = x0; a <= x1; a++) {
        const c = b * nx + a, end = start[c + 1];
        let q = ptr[c];
        while (q < end && list[q] <= i) q++;
        ptr[c] = q;
        for (; q < end; q++) {
          const j = list[q];
          if (j >= je) break;
          const dx = fx[j] - xi, dy = fy[j] - yi, d2 = dx * dx + dy * dy;
          if (d2 >= d2max) continue;
          let tb = Math.floor((T[j] - ti) * ts); if (tb >= tBins) tb = tBins - 1;
          let db = Math.floor(Math.sqrt(d2) * ds); if (db >= dBins) db = dBins - 1;
          out[tb * dBins + db]++;
        }
      }
    }
    return out;
  }
  function knox(x, y, t, opts, onProgress) {
    const o = Object.assign({ dMax: 100, dBins: 20, tMax: 180, tBins: 18, u: 0, v: 0, nPerm: 39, seed: 1 }, opts || {});
    const n = x.length, order = Array.from({ length: n }, (_, i) => i).sort((a, b) => t[a] - t[b]);
    const X = new Float64Array(n), Y = new Float64Array(n), T = new Float64Array(n), jEnd = new Int32Array(n);
    for (let i = 0; i < n; i++) { X[i] = x[order[i]]; Y[i] = y[order[i]]; T[i] = t[order[i]]; }
    // times are sorted and fixed across permutations, so the window ends are too
    for (let i = 0, j = 0; i < n; i++) { if (j < i) j = i; while (j < n && T[j] - T[i] < o.tMax) j++; jEnd[i] = j; }
    const nb = o.dBins * o.tBins, ident = new Int32Array(n);
    for (let i = 0; i < n; i++) ident[i] = i;
    const obs = pairCounts(X, Y, T, ident, jEnd, o.u, o.v, o.dMax, o.dBins, o.tMax, o.tBins, new Float64Array(nb));
    if (onProgress) onProgress(0, o.nPerm);
    const rand = mulberry32(o.seed), sims = new Array(nb), tmp = new Float64Array(nb);
    for (let b = 0; b < nb; b++) sims[b] = new Float64Array(o.nPerm);
    for (let r = 0; r < o.nPerm; r++) {
      pairCounts(X, Y, T, permutation(n, rand), jEnd, o.u, o.v, o.dMax, o.dBins, o.tMax, o.tBins, tmp);
      for (let b = 0; b < nb; b++) sims[b][r] = tmp[b];
      if (onProgress) onProgress(r + 1, o.nPerm);
    }
    const permMean = new Float64Array(nb), lo = new Float64Array(nb), hi = new Float64Array(nb), ratio = new Float64Array(nb);
    for (let b = 0; b < nb; b++) {
      const s = sims[b].sort();
      let m = 0; for (let r = 0; r < o.nPerm; r++) m += s[r];
      permMean[b] = m / o.nPerm;
      lo[b] = quantileSorted(s, 0.025); hi[b] = quantileSorted(s, 0.975);
      ratio[b] = permMean[b] > 0 ? obs[b] / permMean[b] : NaN;
    }
    const dEdges = [], tEdges = [];
    for (let i = 0; i <= o.dBins; i++) dEdges.push(i * o.dMax / o.dBins);
    for (let i = 0; i <= o.tBins; i++) tEdges.push(i * o.tMax / o.tBins);
    return { obs, permMean, lo, hi, ratio, dEdges, tEdges, nPerm: o.nPerm, dBins: o.dBins, tBins: o.tBins, u: o.u, v: o.v, n };
  }

  // ---------- simulated storm night with known truth ----------
  // Cells are born uniformly in space and time, drift with (u, v) km/h, and emit Gaussian-scattered flashes
  // (sd = radiusKm) about the moving centre during their life. A background share is uniform in space-time.
  function simStorm(seed, opts) {
    const o = Object.assign({ nCells: 40, radiusKm: 6, lifetimeMin: 40, u: 0, v: 50, flashesPerCell: 80,
      backgroundShare: 0.1, spanMin: 360, boxKm: 400 }, opts || {});
    const rand = mulberry32(seed), gauss = normalGen(rand);
    const nCore = o.nCells * o.flashesPerCell, nBg = Math.round(nCore * o.backgroundShare / (1 - o.backgroundShare));
    const n = nCore + nBg, x = new Float64Array(n), y = new Float64Array(n), t = new Float64Array(n);
    const cell = new Int32Array(n).fill(-1), births = [];
    let p = 0;
    for (let c = 0; c < o.nCells; c++) {
      const bx = rand() * o.boxKm, by = rand() * o.boxKm, bt = rand() * Math.max(0, o.spanMin - o.lifetimeMin);
      births.push({ x: bx, y: by, t: bt });
      for (let f = 0; f < o.flashesPerCell; f++, p++) {
        const dt = rand() * o.lifetimeMin;
        t[p] = bt + dt; cell[p] = c;
        x[p] = bx + o.u * dt / 60 + o.radiusKm * gauss();
        y[p] = by + o.v * dt / 60 + o.radiusKm * gauss();
      }
    }
    for (; p < n; p++) { x[p] = rand() * o.boxKm; y[p] = rand() * o.boxKm; t[p] = rand() * o.spanMin; }
    return { x, y, t, cell, births, opts: o };
  }

  const api = { mulberry32, normalGen, shuffle, permutation, median, weightedMedian, quantileSorted, slope,
    load, dbscan, kdist, cellStats, fitVelocity, knox, simStorm };
  root.D4C = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : this);
