// Day 4 page: one storm night of GOES-17 lightning, clustered. Computation is in day04core.js (and its worker); this file draws and wires.
(function () {
  "use strict";
  const C = window.D4C, GLM = window.D4GLM, ERA = window.D4ERA5, BASE = window.D4BASE;
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  // panels are dark in both page themes, as on Days 1 to 3
  const COL = { ground: "#0c1822", river: "#7fb7d6", amber: "#ffb454", ink: "#e9f1f5", muted: "#8aa0ae", noise: "#8a98a3",
    line: "rgba(233,241,245,.62)", faint: "rgba(233,241,245,.14)", neutral: "#3b4650" };
  const CELLCOL = ["#7fb7d6", "#ffb454", "#e57373", "#81c995", "#c39bd3", "#f2e86d", "#6fd6c9", "#f08fb0", "#a3b8ff", "#d6a26f", "#9be564", "#ff9e6d"];
  const fmt = (v, d = 0) => (Number.isFinite(v) ? v.toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–");
  const MINUS = "−";
  const sgn = (v, d = 1) => (v < 0 ? MINUS : "") + fmt(Math.abs(v), d);
  const REDUCED = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const HOME = { cx: 1146, cy: 920, w: 580 };

  // ---------- data ----------
  const D = C.load(GLM), N = D.x.length;
  let TMAX = 0; for (let i = 0; i < N; i++) if (D.t[i] > TMAX) TMAX = D.t[i];
  TMAX = Math.ceil(TMAX);
  const BB = { x0: BASE.bbox[0] / 1000, y0: BASE.bbox[1] / 1000, x1: BASE.bbox[2] / 1000, y1: BASE.bbox[3] / 1000 };   // km, EPSG:3005
  const toKm = (a) => { const o = new Float32Array(a.length); for (let i = 0; i < a.length; i++) o[i] = a[i] / 10; return o; };   // 100 m units to km
  const GEO = { coast: BASE.coast.map(toKm), lakes: BASE.lakes.map(toKm), rivers: BASE.rivers.map(toKm), places: BASE.places.map((p) => ({ name: p.name, x: p.x / 10, y: p.y / 10 })) };
  const GS = new Int32Array(N + 1);                       // groups of each flash, as a CSR list
  for (let i = 0; i < D.gf.length; i++) GS[D.gf[i] + 1]++;
  for (let i = 0; i < N; i++) GS[i + 1] += GS[i];
  const GL = new Int32Array(D.gf.length), gfill = GS.slice(0, N);
  for (let i = 0; i < D.gf.length; i++) GL[gfill[D.gf[i]]++] = i;
  const WHISK_KM = 3;                                      // cloud-top height error assumed for the parallax whisker
  const T0 = Date.UTC(2021, 5, 30, 20, 0), MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");
  function clk(t, off) { const d = new Date(T0 + t * 60000 + off * 3600000); return d.getUTCDate() + " " + MON[d.getUTCMonth()] + " " + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()); }
  const hhmm = (t, off) => clk(t, off).slice(-5);

  // ---------- state (everything needed to replay the page exactly) ----------
  const DEFAULT = { band: "auto", eps: 8, tScale: 1, minPts: 6, win: 0, t: 300, tracks: true, parallax: false,
    frame: "era5", cu: 50, cd: 0, nPerm: 39, dots: false, view: null };
  const clone = (o) => JSON.parse(JSON.stringify(o));
  function sanitize(o) {                                   // never throws: anything odd falls back to the default
    const s = clone(DEFAULT);
    try {
      if (!o || typeof o !== "object") return s;
      const num = (v, lo, hi, d) => { v = typeof v === "string" && v.trim() === "" ? NaN : +v; return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d; };
      const one = (v, list, d) => (list.includes(v) ? v : d);
      s.band = one(o.band, ["auto", "cells", "flashes"], s.band);
      s.eps = Math.round(num(o.eps, 2, 25, s.eps) * 2) / 2;
      s.tScale = Math.round(num(o.tScale, 0.1, 3, s.tScale) * 10) / 10;
      s.minPts = Math.round(num(o.minPts, 3, 30, s.minPts));
      s.win = one(+o.win, [0, 10, 30, 60], s.win);
      s.t = Math.round(num(o.t, 0, TMAX, s.t));
      s.tracks = typeof o.tracks === "boolean" ? o.tracks : s.tracks;
      s.parallax = typeof o.parallax === "boolean" ? o.parallax : s.parallax;
      s.frame = one(o.frame, ["ground", "era5", "fit", "custom"], s.frame);
      s.cu = Math.round(num(o.cu, 0, 120, s.cu));
      s.cd = Math.round(num(o.cd, 0, 360, s.cd)) % 360;
      s.nPerm = one(+o.nPerm, [39, 99], s.nPerm);
      s.dots = typeof o.dots === "boolean" ? o.dots : s.dots;
      if (o.view && typeof o.view === "object") {
        const w = num(o.view.w, 12, 650, NaN), cx = num(o.view.cx, BB.x0, BB.x1, NaN), cy = num(o.view.cy, BB.y0, BB.y1, NaN);
        if (Number.isFinite(w) && Number.isFinite(cx) && Number.isFinite(cy)) s.view = { cx: Math.round(cx * 10) / 10, cy: Math.round(cy * 10) / 10, w: Math.round(w * 10) / 10 };
      }
    } catch (e) { return clone(DEFAULT); }
    return s;
  }
  let S = clone(DEFAULT);

  // ---------- workers (one for clustering, one for the Knox surface), with an in-page fallback ----------
  function Runner() {
    let w = null, id = 0, first = true;
    const pend = new Map(), self = this;
    function local(m, h) {
      try {
        if (m.type === "cluster") {
          const r = C.dbscan(D.x, D.y, D.t, m.params), stats = C.cellStats(r.labels, r.k, D.x, D.y, D.t, D.area_km2);
          h({ id: m.id, type: "cluster", labels: r.labels, k: r.k, core: r.core, stats, kdist: C.kdist(D.x, D.y, D.t, m.params.tScale, Math.max(1, m.params.minPts - 1)) });
        } else if (m.type === "knox") {
          const o = Object.assign({}, m.opts, { nPerm: Math.min(m.opts.nPerm, 19) });
          h({ id: m.id, type: "knox", res: C.knox(D.x, D.y, D.t, o, null) });
        } else if (m.type === "fit") h({ id: m.id, type: "fit", res: C.fitVelocity(m.labels, m.k, D.x, D.y, D.t, m.opts) });
      } catch (err) { h({ id: m.id, type: "error", message: String(err && err.message || err) }); }
    }
    try {
      w = new Worker("js/day04worker.js");
      w.onmessage = (e) => { const m = e.data, p = pend.get(m.id); if (p) { p.h(m); if (m.type !== "progress") pend.delete(m.id); } };
      w.onerror = () => { w = null; const all = [...pend.values()]; pend.clear(); all.forEach((p) => setTimeout(() => local(p.m, p.h), 10)); };
    } catch (e) { w = null; }
    self.ask = (msg, h) => {
      msg.id = ++id;
      if (!w) { setTimeout(() => local(msg, h), 10); return msg.id; }
      if (first) { msg.glm = { flash: GLM.flash, group: { x: [], y: [], t: [], f: [] } }; first = false; }   // workers use flashes only
      pend.set(msg.id, { h, m: msg });
      w.postMessage(msg);
      return msg.id;
    };
    self.usesWorker = () => !!w;
  }
  const rc = new Runner(), rk = new Runner();

  // ---------- clustering ----------
  let CL = null, FIT = null, clusterId = 0, fitId = 0, knoxId = 0, KNOX = null;
  const KCACHE = new Map();
  function runCluster() {
    const p = { eps: S.eps, tScale: S.tScale, minPts: S.minPts };
    $("d4-cl-note").textContent = "clustering…";
    clusterId = rc.ask({ type: "cluster", params: p }, (m) => {
      if (m.id !== clusterId) return;
      if (m.type === "error") { $("d4-cl-note").textContent = "Clustering failed: " + m.message; return; }
      CL = { p, labels: m.labels, k: m.k, stats: m.stats, kdist: m.kdist };
      $("d4-cl-note").textContent = "";
      updateReadouts(); renderKd(); schedule();
      fitId = rc.ask({ type: "fit", labels: m.labels, k: m.k }, (f) => {
        if (f.id !== fitId || f.type !== "fit") return;
        FIT = f.res; renderVec(); if (S.frame === "fit") runKnox();
      });
    });
  }
  function updateReadouts() {
    const st = CL.stats;
    $("r4-cells").textContent = fmt(st.k);
    $("r4-noise").textContent = fmt(st.noiseShare * 100) + "%";
    $("r4-life").textContent = Number.isFinite(st.medLifetime) ? fmt(st.medLifetime) + " min" : "–";
    $("r4-rad").textContent = Number.isFinite(st.medRadius) ? fmt(st.medRadius, 1) + " km" : "–";
    $("r4-rate").textContent = Number.isFinite(st.medRate) ? fmt(st.medRate, 1) + " /min" : "–";
  }

  // ---------- storm frame and the Knox surface ----------
  const bearing = (u, v) => ((Math.atan2(u, v) * 180 / Math.PI) + 360) % 360;
  function frameVel() {
    if (S.frame === "ground") return [0, 0];
    if (S.frame === "era5") return [ERA.night.u_kmh, ERA.night.v_kmh];
    if (S.frame === "custom") return [S.cu * Math.sin(S.cd * Math.PI / 180), S.cu * Math.cos(S.cd * Math.PI / 180)];
    return FIT && Number.isFinite(FIT.u) && Number.isFinite(FIT.v) ? [FIT.u, FIT.v] : null;
  }
  const FRAME_NAME = { ground: "Ground frame", era5: "Storm frame, ERA5 steering", fit: "Storm frame, self-fitted (circular)", custom: "Storm frame, custom" };
  function runKnox() {
    const v = frameVel();
    if (!v) { $("d4-prog").textContent = FIT ? "The cells are too few or too short-lived to fit a motion: loosen the DBSCAN settings." : "Waiting for the cell fit…"; return; }
    const key = [S.frame, v[0].toFixed(2), v[1].toFixed(2), S.nPerm].join("|");
    if (KCACHE.has(key)) { KNOX = KCACHE.get(key); renderHeat(); renderVec(); $("d4-prog").textContent = ""; return; }
    const started = performance.now(), nPerm = S.nPerm, frame = S.frame;
    $("d4-prog").textContent = "Permutation 0 of " + nPerm + "…";
    knoxId = rk.ask({ type: "knox", opts: { u: v[0], v: v[1], nPerm, seed: 1 } }, (m) => {
      if (m.id !== knoxId) return;
      if (m.type === "progress") { $("d4-prog").textContent = "Permutation " + m.i + " of " + m.R + "…"; return; }
      if (m.type === "error") { $("d4-prog").textContent = "Could not compute the surface: " + m.message; return; }
      const ms = performance.now() - started, r = m.res;
      r.frame = frame; r.key = key; r.ms = ms;
      KCACHE.set(key, r); KNOX = r;
      $("d4-tools").dataset.knoxMs = String(Math.round(ms));
      $("d4-prog").textContent = "Done: " + r.nPerm + " permutations in " + fmt(ms / 1000, 1) + " s" + (rk.usesWorker() ? "." : " (run in the page, so fewer permutations).");
      renderHeat(); renderVec();
    });
  }
  // share of the excess pairs (observed minus permutation mean, lags up to 60 min) that lie within 15 km
  function concentration(r) {
    let near = 0, all = 0;
    for (let tb = 0; tb < r.tBins; tb++) {
      if (r.tEdges[tb + 1] > 60) break;
      for (let db = 0; db < r.dBins; db++) { const e = r.obs[tb * r.dBins + db] - r.permMean[tb * r.dBins + db]; all += e; if (r.dEdges[db + 1] <= 15) near += e; }
    }
    return all > 0 ? near / all : NaN;
  }

  // ---------- colour for observed / expected ----------
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, f) => { const A = hex(a), B = hex(b); return "rgb(" + A.map((v, i) => Math.round(v + (B[i] - v) * f)).join(",") + ")"; };
  const BLUE = "#2f6fa8", HOT1 = "#ffb454", HOT2 = "#fff1c7";
  function ratioColour(r) {
    if (!Number.isFinite(r)) return COL.neutral;
    const t = Math.max(-2, Math.min(4, Math.log2(Math.max(r, 1e-6))));    // 1/4 to 16 times the expected count
    if (t >= 0) return t <= 2 ? mix(COL.neutral, HOT1, t / 2) : mix(HOT1, HOT2, (t - 2) / 2);
    return mix(COL.neutral, BLUE, -t / 2);
  }

  // ---------- svg helpers ----------
  function el(tag, attrs, text, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function sizeSvg(svg, aspect, minW) {
    const r = svg.getBoundingClientRect(), W = Math.max(minW || 260, Math.round(r.width || 300)), H = Math.round(W * aspect);
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.replaceChildren();
    return [W, H];
  }

  // k-distance plot
  function renderKd() {
    const svg = $("d4-kd"); if (!CL) return;
    const [W, H] = sizeSvg(svg, 0.7, 260);
    const m = { l: 44, r: 10, t: 10, b: 36 }, pw = W - m.l - m.r, ph = H - m.t - m.b, kd = CL.kdist, n = kd.length, YM = 40;
    const X = (i) => m.l + pw * i / (n - 1), Y = (v) => m.t + ph * (1 - Math.min(v, YM) / YM);
    for (const v of [0, 10, 20, 30, 40]) { el("line", { x1: m.l, x2: m.l + pw, y1: Y(v), y2: Y(v), stroke: COL.faint }, null, svg); el("text", { x: m.l - 6, y: Y(v) + 3.5, "text-anchor": "end", class: "tk" }, String(v), svg); }
    let d = "";
    const step = Math.max(1, Math.floor(n / pw));
    for (let i = 0; i < n; i += step) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(kd[n - 1 - i]).toFixed(1);
    el("path", { d, fill: "none", stroke: COL.river, "stroke-width": 1.6 }, null, svg);
    el("line", { x1: m.l, x2: m.l + pw, y1: Y(S.eps), y2: Y(S.eps), stroke: COL.amber, "stroke-width": 1.4, "stroke-dasharray": "5 3" }, null, svg);
    el("text", { x: m.l + pw - 4, y: Y(S.eps) - 5, "text-anchor": "end", class: "lg", style: "fill:" + COL.amber }, "eps " + fmt(S.eps, 1) + " km", svg);
    el("text", { x: m.l + pw / 2, y: H - 6, "text-anchor": "middle", class: "ax" }, "flashes, farthest neighbour first", svg);
    el("text", { x: 12, y: m.t + ph / 2, "text-anchor": "middle", class: "ax", transform: "rotate(-90 12 " + (m.t + ph / 2) + ")" }, "km to the " + (CL.p.minPts - 1) + "th neighbour", svg);
    let above = 0; for (let i = 0; i < n; i++) if (kd[i] > S.eps) above++;
    $("d4-kd-line").textContent = fmt(above) + " of " + fmt(n) + " flashes (" + fmt(100 * above / n) + "%) have their " + (CL.p.minPts - 1) + "th neighbour farther than eps, so they cannot be core points.";
  }

  // Knox heat map
  const heatG = { m: { l: 50, r: 8, t: 8, b: 42 } };
  function renderHeat() {
    const svg = $("d4-heat"); if (!KNOX) return;
    const r = KNOX, [W, H] = sizeSvg(svg, 0.66, 280), m = heatG.m;
    const pw = W - m.l - m.r, ph = H - m.t - m.b - 14, cw = pw / r.dBins, ch = ph / r.tBins;
    heatG.W = W; heatG.H = H; heatG.cw = cw; heatG.ch = ch; heatG.ph = ph;
    let sig = 0, nOut = 0, nTot = 0;
    for (let tb = 0; tb < r.tBins; tb++) for (let db = 0; db < r.dBins; db++) {
      const b = tb * r.dBins + db, o = r.obs[b], pm = r.permMean[b];
      let q = r.ratio[b]; if (!Number.isFinite(q) && o > 0) q = 16;
      const x = m.l + db * cw, y = m.t + ph - (tb + 1) * ch;
      if (o === 0 && pm === 0) continue;
      nTot++;
      el("rect", { x, y, width: cw + 0.4, height: ch + 0.4, fill: ratioColour(q) }, null, svg);
      if (Number.isFinite(q)) sig += q * (b % 7 + 1);
      const cx = x + cw / 2, cy = y + ch / 2;
      const outHi = o > r.hi[b], outLo = o < r.lo[b]; if (outHi || outLo) nOut++;
      if (!S.dots) continue;
      if (outHi) el("circle", { cx, cy, r: Math.min(2.6, cw / 5), fill: COL.ink, stroke: COL.ground, "stroke-width": 0.8 }, null, svg);
      else if (outLo) el("circle", { cx, cy, r: Math.min(2.4, cw / 5), fill: "none", stroke: COL.ink, "stroke-width": 1 }, null, svg);
    }
    for (let d = 0; d <= 100; d += 20) el("text", { x: m.l + pw * d / 100, y: m.t + ph + 14, "text-anchor": "middle", class: "tk" }, String(d), svg);
    for (let t = 0; t <= 180; t += 30) el("text", { x: m.l - 6, y: m.t + ph - ph * t / 180 + 3.5, "text-anchor": "end", class: "tk" }, String(t), svg);
    el("text", { x: m.l + pw / 2, y: m.t + ph + 28, "text-anchor": "middle", class: "ax" }, "distance between the two flashes (km)", svg);
    el("text", { x: 11, y: m.t + ph / 2, "text-anchor": "middle", class: "ax", transform: "rotate(-90 11 " + (m.t + ph / 2) + ")" }, "time lag (min)", svg);
    el("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "none", stroke: COL.faint }, null, svg);
    // colour key: observed / expected pairs, log scale
    const ky = H - 14, kw = Math.min(160, pw - 150), kx = m.l;
    const gr = el("linearGradient", { id: "d4-grad" }, null, el("defs", {}, null, svg));
    for (let i = 0; i <= 12; i++) el("stop", { offset: (i / 12 * 100) + "%", "stop-color": ratioColour(Math.pow(2, -2 + 6 * i / 12)) }, null, gr);
    el("rect", { x: kx, y: ky - 8, width: kw, height: 8, fill: "url(#d4-grad)" }, null, svg);
    [[-2, "¼"], [0, "1"], [2, "4"], [4, "16"]].forEach(([t, s]) => el("text", { x: kx + kw * (t + 2) / 6, y: ky + 10, "text-anchor": "middle", class: "tk" }, s, svg));
    el("text", { x: kx + kw + 8, y: ky, class: "tk" }, "observed ÷ expected", svg);
    $("d4-dots-n").textContent = S.dots ? fmt(nOut) + " of " + fmt(r.dBins * r.tBins) + " cells are marked." : "";
    svg.dataset.frame = r.frame; svg.dataset.sig = String(Math.round(sig)); svg.dataset.nperm = String(r.nPerm);
    $("d4-knox-name").textContent = FRAME_NAME[r.frame] + ": " + (r.u === 0 && r.v === 0 ? "no motion removed." : "removing " + fmt(Math.hypot(r.u, r.v)) + " km/h toward " + fmt(bearing(r.u, r.v)) + "°.");
    conclusion();
  }
  function conclusion() {
    const rows = [...KCACHE.values()].filter((r) => r.nPerm === KNOX.nPerm);
    const order = ["ground", "era5", "fit", "custom"];
    rows.sort((a, b) => order.indexOf(a.frame) - order.indexOf(b.frame));
    const tb = $("d4-conc").querySelector("tbody"); tb.replaceChildren();
    for (const r of rows) {
      const tr = document.createElement("tr"); if (r.key === KNOX.key) tr.className = "cur";
      const th = document.createElement("th"); th.textContent = FRAME_NAME[r.frame].replace("Storm frame, ", "Storm, "); tr.appendChild(th);
      const td1 = document.createElement("td"); td1.textContent = r.u === 0 && r.v === 0 ? "none" : fmt(Math.hypot(r.u, r.v)) + " km/h, " + fmt(bearing(r.u, r.v)) + "°"; tr.appendChild(td1);
      const td2 = document.createElement("td"), c = concentration(r); td2.textContent = Number.isFinite(c) ? fmt(c * 100) + "%" : "–"; tr.appendChild(td2);
      tb.appendChild(tr);
    }
  }
  function heatHover(e) {
    const tip = $("d4-tip"), svg = $("d4-heat"); if (!KNOX || !heatG.cw) return;
    const r = svg.getBoundingClientRect(), sx = heatG.W / r.width, m = heatG.m;
    const px = (e.clientX - r.left) * sx, py = (e.clientY - r.top) * sx;
    const db = Math.floor((px - m.l) / heatG.cw), tb = Math.floor((m.t + heatG.ph - py) / heatG.ch);
    if (db < 0 || db >= KNOX.dBins || tb < 0 || tb >= KNOX.tBins) { tip.hidden = true; return; }
    const b = tb * KNOX.dBins + db, k = KNOX;
    const where = k.obs[b] > k.hi[b] ? "above the 95% band" : k.obs[b] < k.lo[b] ? "below the 95% band" : "inside the 95% band";
    tip.innerHTML = "<b>" + k.dEdges[db] + " to " + k.dEdges[db + 1] + " km, " + k.tEdges[tb] + " to " + k.tEdges[tb + 1] + " min</b><br>observed " + fmt(k.obs[b]) +
      "<br>expected " + fmt(k.permMean[b], 1) + "<br>ratio " + (Number.isFinite(k.ratio[b]) ? fmt(k.ratio[b], 2) : "–") + ", " + where;
    tip.hidden = false;
    const w = svg.parentElement.getBoundingClientRect();
    tip.style.left = Math.max(0, Math.min(e.clientX - w.left + 12, w.width - 200)) + "px"; tip.style.top = Math.max(0, e.clientY - w.top - 8) + "px";
  }

  // motion vectors: ERA5 steering, fitted, custom
  function renderVec() {
    const svg = $("d4-vec"), W = 220, H = 220, cx = 110, cy = 112, sc = 0.95;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H); svg.replaceChildren();
    el("circle", { cx, cy, r: 60 * sc, fill: "none", stroke: COL.faint }, null, svg);
    el("circle", { cx, cy, r: 30 * sc, fill: "none", stroke: COL.faint }, null, svg);
    el("line", { x1: cx, y1: 14, x2: cx, y2: H - 8, stroke: COL.faint }, null, svg);
    el("line", { x1: 10, y1: cy, x2: W - 10, y2: cy, stroke: COL.faint }, null, svg);
    el("text", { x: cx + 5, y: 22, class: "tk" }, "N (grid)", svg);
    el("text", { x: cx + 62 * sc + 2, y: cy - 3, class: "tk" }, "60 km/h", svg);
    const arrow = (u, v, colour, dash, label) => {
      if (!Number.isFinite(u) || !Number.isFinite(v)) return;
      const x = cx + u * sc, y = cy - v * sc, a = Math.atan2(y - cy, x - cx), hl = 9;
      el("line", { x1: cx, y1: cy, x2: x, y2: y, stroke: colour, "stroke-width": 2.4, "stroke-dasharray": dash || "none" }, null, svg);
      el("path", { d: "M" + x + " " + y + "L" + (x - hl * Math.cos(a - 0.4)) + " " + (y - hl * Math.sin(a - 0.4)) + "L" + (x - hl * Math.cos(a + 0.4)) + " " + (y - hl * Math.sin(a + 0.4)) + "Z", fill: colour }, null, svg);
      el("text", { x: x + (u >= 0 ? 6 : -6), y: y + (v >= 0 ? -6 : 14), "text-anchor": u >= 0 ? "start" : "end", class: "lg", style: "fill:" + colour }, label, svg);
    };
    arrow(ERA.night.u_kmh, ERA.night.v_kmh, COL.amber, null, "ERA5");
    if (FIT) arrow(FIT.u, FIT.v, COL.river, "5 3", "fit");
    if (S.frame === "custom") { const v = frameVel(); arrow(v[0], v[1], COL.ink, "2 3", "custom"); }
    el("circle", { cx, cy, r: 2.5, fill: COL.ink }, null, svg);
    $("d4-v-era").textContent = fmt(ERA.night.speed_kmh) + " km/h toward " + fmt(ERA.night.dir_to_deg) + "° (u " + sgn(ERA.night.u_kmh) + ", v " + sgn(ERA.night.v_kmh) + ")";
    $("d4-v-fit").textContent = FIT && Number.isFinite(FIT.u) ? fmt(Math.hypot(FIT.u, FIT.v)) + " km/h toward " + fmt(bearing(FIT.u, FIT.v)) + "° (u " + sgn(FIT.u) + ", v " + sgn(FIT.v) + "; " + FIT.nCells + " cells)" : FIT ? "no cell qualifies at these settings" : "…";
  }

  // covariate small multiples (one axis each)
  const COVS = [
    { k: "n", name: "Flashes near each hour", zero: true, bars: true },
    { k: "cape", name: "CAPE (J/kg)", zero: true },
    { k: "shear_ms", name: "Bulk shear 925 to 500 hPa (m/s)", zero: false },
    { k: "lapse_ckm", name: "Lapse rate 850 to 500 hPa (°C/km)", zero: false },
    { k: "speed_kmh", name: "Steering wind (km/h)", zero: false },
  ];
  let covBands = [];
  function renderCov() {
    const host = $("d4-cov"); host.replaceChildren(); covBands = [];
    const H = ERA.hourly;
    const svgs = COVS.map((c) => { const wrap = document.createElement("div"), svg = el("svg", { class: "wide", role: "img", "aria-label": c.name + " by hour" }); wrap.appendChild(svg); host.appendChild(wrap); return svg; });
    COVS.forEach((c, ci) => {
      const svg = svgs[ci];
      const [W, Ht] = sizeSvg(svg, 0.62, 200), m = { l: 38, r: 8, t: 26, b: 22 }, pw = W - m.l - m.r, ph = Ht - m.t - m.b;
      const vals = H[c.k], fin = vals.filter(Number.isFinite);
      let lo = c.zero ? 0 : Math.min(...fin), hi = Math.max(...fin);
      if (!c.zero) { const p = (hi - lo) * 0.15 || 1; lo -= p; hi += p; }
      const X = (h) => m.l + pw * (h - 0.5) / 11, Y = (v) => m.t + ph * (1 - (v - lo) / (hi - lo));
      const band = el("rect", { x: 0, y: m.t, width: 0, height: ph, fill: COL.amber, opacity: 0.2, display: "none" }, null, svg); covBands.push({ band, X, lo: m.l, hi: m.l + pw });
      el("text", { x: 4, y: 13, class: "lg" }, c.name, svg);
      [lo, hi].forEach((v) => { el("text", { x: m.l - 4, y: Y(v) + 3.5, "text-anchor": "end", class: "tk" }, fmt(v, hi - lo < 20 ? 1 : 0), svg); el("line", { x1: m.l, x2: m.l + pw, y1: Y(v), y2: Y(v), stroke: COL.faint }, null, svg); });
      if (c.bars) vals.forEach((v, i) => el("rect", { x: X(H.h[i]) - pw / 22 + 1, y: Y(v), width: pw / 11 - 2, height: Math.max(0, Y(lo) - Y(v)), fill: COL.river }, null, svg));
      else {
        let d = ""; vals.forEach((v, i) => { if (Number.isFinite(v)) d += (d ? "L" : "M") + X(H.h[i]).toFixed(1) + " " + Y(v).toFixed(1); });
        el("path", { d, fill: "none", stroke: COL.river, "stroke-width": 1.8 }, null, svg);
        vals.forEach((v, i) => { if (Number.isFinite(v)) el("circle", { cx: X(H.h[i]), cy: Y(v), r: 2.4, fill: COL.river }, null, svg); });
      }
      [2, 4, 6, 8, 10].forEach((h) => el("text", { x: X(h), y: Ht - 6, "text-anchor": "middle", class: "tk" }, pad((20 + h) % 24), svg));
      el("text", { x: m.l + pw, y: Ht - 6, "text-anchor": "end", class: "tk" }, "UTC", svg);
    });
    markCov();
  }
  function markCov() {
    for (const c of covBands) {
      if (S.win === 0) { c.band.setAttribute("display", "none"); continue; }
      const x0 = Math.max(c.lo, c.X(S.t / 60)), x1 = Math.min(c.hi, c.X(Math.min(S.t + S.win, TMAX) / 60));
      if (x1 <= x0) { c.band.setAttribute("display", "none"); continue; }
      c.band.setAttribute("x", x0); c.band.setAttribute("width", Math.max(1.5, x1 - x0)); c.band.setAttribute("display", "inline");
    }
  }

  // ---------- map ----------
  const cv = $("d4-map"), ctx = cv.getContext("2d");
  let VW = 300, VH = 240, DPR = 1, relief = null, reliefOk = false, raf = 0, HOV = -1, viewCount = -1, firstDrawn = false;
  const W_MIN = 12, W_MAX = 650;
  const bandNow = () => (S.band !== "auto" ? S.band : S.view && S.view.w <= 120 ? "flashes" : "cells");
  function resize() {
    const r = cv.getBoundingClientRect(); VW = Math.max(200, r.width); VH = Math.max(160, r.height);
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.round(VW * DPR); cv.height = Math.round(VH * DPR);
    if (!S.view) S.view = clone(HOME);
    schedule();
  }
  const sc = () => VW / S.view.w;
  function clampView() { const v = S.view; v.w = Math.min(W_MAX, Math.max(W_MIN, v.w)); v.cx = Math.min(BB.x1, Math.max(BB.x0, v.cx)); v.cy = Math.min(BB.y1, Math.max(BB.y0, v.cy)); }
  function zoomAt(px, py, f) {
    const v = S.view, s = sc(), X = v.cx + (px - VW / 2) / s, Y = v.cy - (py - VH / 2) / s;
    v.w /= f; clampView(); const s2 = sc(); v.cx = X - (px - VW / 2) / s2; v.cy = Y + (py - VH / 2) / s2; clampView(); viewChanged();
  }
  function panBy(dx, dy) { const s = sc(); S.view.cx -= dx / s; S.view.cy += dy / s; clampView(); viewChanged(); }
  function viewChanged() { const v = S.view; v.cx = Math.round(v.cx * 10) / 10; v.cy = Math.round(v.cy * 10) / 10; v.w = Math.round(v.w * 10) / 10; schedule(); saveHash(); bandNote(); }
  const inWin = (i) => S.win === 0 || (D.t[i] >= S.t && D.t[i] < S.t + S.win);
  const colourOf = (i) => (CL && CL.labels[i] >= 0 ? CELLCOL[(CL.labels[i] * 5) % CELLCOL.length] : COL.noise);
  function schedule() { if (!raf) raf = requestAnimationFrame(draw); }
  function bandNote() {
    const b = bandNow();
    cv.dataset.band = b;
    $("d4-band-note").textContent = (S.band === "auto" ? "Auto: " : "Set by hand: ") + (b === "cells" ? "flashes coloured by cell" : "each flash at the size the satellite measured") + ". The map is " + fmt(S.view.w) + " km across.";
  }
  function draw() {
    raf = 0; if (!S.view) return;
    const v = S.view, s = sc(), band = bandNow();
    const px = (X) => (X - v.cx) * s + VW / 2, py = (Y) => VH / 2 - (Y - v.cy) * s;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0); ctx.fillStyle = COL.ground; ctx.fillRect(0, 0, VW, VH);
    if (reliefOk) { ctx.save(); ctx.globalAlpha = 0.34; ctx.imageSmoothingQuality = "high"; ctx.drawImage(relief, px(BB.x0), py(BB.y1), (BB.x1 - BB.x0) * s, (BB.y1 - BB.y0) * s); ctx.restore(); }
    const path = (a, close) => { ctx.moveTo(px(a[0]), py(a[1])); for (let i = 2; i < a.length; i += 2) ctx.lineTo(px(a[i]), py(a[i + 1])); if (close) ctx.closePath(); };
    ctx.lineJoin = "round";
    ctx.beginPath(); GEO.lakes.forEach((a) => path(a, true)); ctx.fillStyle = "rgba(127,183,214,.16)"; ctx.fill(); ctx.strokeStyle = "rgba(127,183,214,.4)"; ctx.lineWidth = 0.8; ctx.stroke();
    ctx.beginPath(); GEO.rivers.forEach((a) => path(a, false)); ctx.strokeStyle = "rgba(127,183,214,.34)"; ctx.lineWidth = 0.8; ctx.stroke();
    ctx.beginPath(); GEO.coast.forEach((a) => path(a, false)); ctx.strokeStyle = "rgba(233,241,245,.34)"; ctx.lineWidth = 1; ctx.stroke();
    ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.textBaseline = "middle";
    for (const p of GEO.places) {
      const x = px(p.x), y = py(p.y); if (x < -40 || x > VW + 40 || y < -10 || y > VH + 10) continue;
      ctx.fillStyle = "rgba(233,241,245,.6)"; ctx.beginPath(); ctx.arc(x, y, 2.2, 0, 6.2832); ctx.fill();
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(12,24,34,.85)"; ctx.strokeText(p.name, x + 6, y); ctx.fillStyle = "rgba(233,241,245,.72)"; ctx.fillText(p.name, x + 6, y);
    }
    // flashes in the window
    const t0 = S.t, w = S.win, margin = band === "flashes" ? 60 * s : 6;
    let nView = 0; const vis = [];
    for (let i = 0; i < N; i++) {
      if (!inWin(i)) continue;
      const x = px(D.x[i]), y = py(D.y[i]);
      if (x < -margin || x > VW + margin || y < -margin || y > VH + margin) continue;
      if (x >= 0 && x <= VW && y >= 0 && y <= VH) nView++;
      vis.push(i);
    }
    if (nView !== viewCount) { viewCount = nView; $("r4-view").textContent = fmt(nView); }
    const alpha = (i) => (w === 0 ? 1 : 0.3 + 0.7 * (D.t[i] - t0) / w);
    if (band === "cells") {
      for (const noise of [true, false]) for (const i of vis) {
        const isN = !(CL && CL.labels[i] >= 0); if (isN !== noise) continue;
        ctx.globalAlpha = (isN ? 0.6 : 0.88) * alpha(i); ctx.fillStyle = colourOf(i);
        ctx.beginPath(); ctx.arc(px(D.x[i]), py(D.y[i]), isN ? 1.5 : 2.7, 0, 6.2832); ctx.fill();
      }
      ctx.globalAlpha = 1;
    } else {
      for (const i of vis) {
        const r = Math.sqrt(D.area_km2[i] / Math.PI) * s, c = colourOf(i), a = alpha(i);
        ctx.beginPath(); ctx.arc(px(D.x[i]), py(D.y[i]), r, 0, 6.2832);
        ctx.globalAlpha = 0.025 * a; ctx.fillStyle = c; ctx.fill();
        ctx.globalAlpha = 0.4 * a; ctx.strokeStyle = c; ctx.lineWidth = 1; ctx.stroke();
      }
      ctx.fillStyle = COL.ink;
      for (const i of vis) { ctx.globalAlpha = 0.9 * alpha(i); for (let g = GS[i]; g < GS[i + 1]; g++) { const q = GL[g]; ctx.beginPath(); ctx.arc(px(D.gx[q]), py(D.gy[q]), 1.4, 0, 6.2832); ctx.fill(); } }
      ctx.globalAlpha = 1;
    }
    // cell tracks
    if (S.tracks && CL) {
      ctx.lineWidth = 1.1; ctx.globalAlpha = 0.7;
      for (const c of CL.stats.cells) {
        const tr = c.track; if (tr.length < 2) continue;
        ctx.beginPath(); let started = false;
        if (w !== 0 && (c.t1 < t0 || c.t0 > t0 + w)) continue;   // only cells alive in the window
        for (const p of tr) { if (w !== 0 && p.t < t0) continue; if (w !== 0 && p.t > t0 + w) break; if (!started) { ctx.moveTo(px(p.x), py(p.y)); started = true; } else ctx.lineTo(px(p.x), py(p.y)); }
        if (!started) continue;
        ctx.strokeStyle = CELLCOL[(c.id * 5) % CELLCOL.length]; ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    // parallax whiskers: toward the satellite, tan(view zenith) times 3 km
    if (S.parallax) {
      ctx.strokeStyle = "rgba(233,241,245,.8)"; ctx.lineWidth = 1; ctx.beginPath();
      for (const i of vis) {
        const L = Math.tan(D.vza[i] * Math.PI / 180) * WHISK_KM, a = D.az[i] * Math.PI / 180;
        ctx.moveTo(px(D.x[i]), py(D.y[i])); ctx.lineTo(px(D.x[i] + L * Math.sin(a)), py(D.y[i] + L * Math.cos(a)));
      }
      ctx.stroke();
    }
    if (HOV >= 0 && inWin(HOV)) { ctx.strokeStyle = COL.amber; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(px(D.x[HOV]), py(D.y[HOV]), band === "flashes" ? Math.sqrt(D.area_km2[HOV] / Math.PI) * s + 2 : 6, 0, 6.2832); ctx.stroke(); }
    // scale bar and grid north
    const target = 90 / s, nice = [1, 2, 5, 10, 20, 50, 100, 200].reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
    const bx = 12, by = VH - 14, bl = nice * s;
    ctx.strokeStyle = COL.ink; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by); ctx.lineTo(bx + bl, by); ctx.lineTo(bx + bl, by - 4); ctx.stroke();
    ctx.fillStyle = COL.ink; ctx.textBaseline = "alphabetic"; ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillText(nice + " km", bx, by - 8);
    const nx = VW - 22, ny = 32; ctx.beginPath(); ctx.moveTo(nx, ny - 14); ctx.lineTo(nx - 5, ny + 2); ctx.lineTo(nx, ny - 2); ctx.lineTo(nx + 5, ny + 2); ctx.closePath(); ctx.fillStyle = COL.amber; ctx.fill();
    ctx.fillStyle = COL.ink; ctx.textAlign = "center"; ctx.fillText("N", nx, ny + 14); ctx.textAlign = "start";
    if (!firstDrawn && reliefOk) { firstDrawn = true; $("d4-tools").dataset.firstMapMs = String(Math.round(performance.now())); }
    cv.dataset.drawn = String((+cv.dataset.drawn || 0) + 1);
  }
  relief = new Image();
  relief.onload = () => { reliefOk = true; schedule(); };
  relief.src = "img/day04_relief.webp";

  // pointer handling: drag to pan, wheel and pinch to zoom, hover or tap to read a flash
  const ptrs = new Map(); let moved = 0, pinch = 0;
  const pos = (e) => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  function pick(x, y) {
    const v = S.view, s = sc(), band = bandNow(); let best = -1, bd = 1e9;
    for (let i = 0; i < N; i++) {
      if (!inWin(i)) continue;
      const dx = (D.x[i] - v.cx) * s + VW / 2 - x, dy = VH / 2 - (D.y[i] - v.cy) * s - y, d = Math.hypot(dx, dy);
      const lim = band === "flashes" ? Math.max(8, Math.sqrt(D.area_km2[i] / Math.PI) * s * 0.5) : 10;
      if (d < lim && d < bd) { bd = d; best = i; }
    }
    return best;
  }
  function showFlash(i) {
    HOV = i; schedule();
    if (i < 0) { $("d4-info").textContent = "Hover or tap a flash to read it."; return; }
    const L = Math.tan(D.vza[i] * Math.PI / 180) * WHISK_KM, lab = CL ? CL.labels[i] : -1;
    $("d4-info").textContent = "Flash " + fmt(i + 1) + " · " + clk(D.t[i], 0) + " UTC (" + hhmm(D.t[i], -7) + " PDT) · " + (lab >= 0 ? "cell " + lab : "noise") + " · area " + fmt(D.area_km2[i]) + " km² · " +
      fmt(D.ng[i]) + " groups · seen " + fmt(D.vza[i], 1) + "° from the vertical · whisker " + fmt(L, 1) + " km toward " + fmt((D.az[i] + 360) % 360) + "°";
  }
  cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, pos(e)); moved = 0; if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); } });
  cv.addEventListener("pointermove", (e) => {
    const p = pos(e);
    if (ptrs.has(e.pointerId)) {
      const prev = ptrs.get(e.pointerId); ptrs.set(e.pointerId, p);
      if (ptrs.size === 1) { moved += Math.abs(p[0] - prev[0]) + Math.abs(p[1] - prev[1]); if (moved > 4) panBy(p[0] - prev[0], p[1] - prev[1]); }
      else if (ptrs.size === 2) {
        const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch > 0 && d > 0) zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d / pinch);
        pinch = d; moved = 99;
      }
    } else if (e.pointerType !== "touch") showFlash(pick(p[0], p[1]));
  });
  cv.addEventListener("pointerup", (e) => { const was = ptrs.size; ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = 0; if (was === 1 && moved <= 4) { const p = pos(e); showFlash(pick(p[0], p[1])); } });
  cv.addEventListener("pointercancel", (e) => { ptrs.delete(e.pointerId); pinch = 0; });
  cv.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch" && !ptrs.size) showFlash(-1); });
  cv.addEventListener("wheel", (e) => { e.preventDefault(); const p = pos(e); zoomAt(p[0], p[1], Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0016))); }, { passive: false });
  cv.addEventListener("keydown", (e) => {
    const k = e.key, st = 0.15 * VW;
    if (k === "ArrowLeft") panBy(st, 0); else if (k === "ArrowRight") panBy(-st, 0); else if (k === "ArrowUp") panBy(0, st); else if (k === "ArrowDown") panBy(0, -st);
    else if (k === "+" || k === "=") zoomAt(VW / 2, VH / 2, 1.5); else if (k === "-" || k === "_") zoomAt(VW / 2, VH / 2, 1 / 1.5); else return;
    e.preventDefault();
  });
  $("d4-zin").addEventListener("click", () => zoomAt(VW / 2, VH / 2, 1.6));
  $("d4-zout").addEventListener("click", () => zoomAt(VW / 2, VH / 2, 1 / 1.6));
  $("d4-zreset").addEventListener("click", () => { S.view = clone(HOME); viewChanged(); });

  // ---------- time: scrubber, window, play ----------
  let playing = false, last = 0;
  function clockText() {
    if (S.win === 0) return "Whole night: " + clk(0, 0) + " to " + hhmm(TMAX, 0) + " UTC (Pacific daylight time, " + hhmm(0, -7) + " to " + hhmm(TMAX, -7) + ")";
    const e = Math.min(S.t + S.win, TMAX);
    return clk(S.t, 0) + " to " + hhmm(e, 0) + " UTC (Pacific daylight time, " + hhmm(S.t, -7) + " to " + hhmm(e, -7) + ")";
  }
  function tick(now) {
    if (!playing) return;
    const dt = Math.min(100, now - last); last = now;
    S.t += dt * 0.012; if (S.t >= TMAX) { S.t = TMAX; setPlaying(false); }
    $("d4-t").value = String(Math.round(S.t)); $("d4-clock").textContent = clockText(); markCov(); schedule();
    if (playing) requestAnimationFrame(tick);
  }
  function setPlaying(on) {
    playing = on; $("d4-play").textContent = on ? "Pause" : "Play"; $("d4-play").setAttribute("aria-pressed", String(on));
    if (on) { if (S.win === 0) { S.win = 30; syncUI(); } if (S.t >= TMAX - 1) S.t = 0; last = performance.now(); requestAnimationFrame(tick); } else saveHash();
  }

  // ---------- controls ----------
  let hashTimer = 0, cTimer = 0, kTimer = 0;
  function saveHash() { clearTimeout(hashTimer); hashTimer = setTimeout(() => { try { history.replaceState(null, "", "#" + encodeURIComponent(JSON.stringify(S))); } catch (e) { /* file:// or sandbox */ } }, 300); }
  function paintSeg(id, val) { for (const b of $(id).querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.k === String(val))); }
  function syncUI() {
    paintSeg("d4-band", S.band); paintSeg("d4-win", S.win); paintSeg("d4-frame", S.frame); paintSeg("d4-nperm", S.nPerm);
    $("d4-eps").value = S.eps; $("d4-eps-v").textContent = fmt(S.eps, 1) + " km";
    $("d4-ts").value = S.tScale; $("d4-ts-v").textContent = fmt(S.tScale, 1) + " km/min = " + fmt(S.tScale * 60) + " km/h";
    $("d4-mp").value = S.minPts; $("d4-mp-v").textContent = String(S.minPts);
    $("d4-t").max = TMAX; $("d4-t").value = S.t; $("d4-t").disabled = S.win === 0;
    $("d4-play").disabled = REDUCED; $("d4-reduced").hidden = !REDUCED;
    $("d4-tracks").checked = S.tracks; $("d4-par").checked = S.parallax; $("d4-dots").checked = S.dots; $("d4-par-note").hidden = !S.parallax;
    $("d4-custom").hidden = S.frame !== "custom"; $("d4-cu").value = S.cu; $("d4-cd").value = S.cd;
    $("d4-cu-v").textContent = S.cu + " km/h"; $("d4-cd-v").textContent = S.cd + "°";
    $("d4-clock").textContent = clockText();
    if (S.view) bandNote();
    markCov();
  }
  function seg(id, key, conv) {
    $(id).addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S[key] = conv ? conv(b.dataset.k) : b.dataset.k; changed(key); });
  }
  function changed(key) {
    if (key === "win" && S.win !== 0 && S.t > TMAX - S.win) S.t = Math.max(0, TMAX - S.win);
    if (key === "win" && S.win === 0 && playing) setPlaying(false);
    syncUI();
    if (key === "eps" || key === "tScale" || key === "minPts") { clearTimeout(cTimer); cTimer = setTimeout(runCluster, 140); if (key === "eps" && CL) renderKd(); }
    else if (key === "frame" || key === "cu" || key === "cd" || key === "nPerm") { clearTimeout(kTimer); kTimer = setTimeout(runKnox, 160); if (S.frame === "custom") renderVec(); }
    schedule(); saveHash();
  }
  seg("d4-band", "band"); seg("d4-win", "win", Number); seg("d4-frame", "frame"); seg("d4-nperm", "nPerm", Number);
  [["d4-eps", "eps", parseFloat], ["d4-ts", "tScale", parseFloat], ["d4-mp", "minPts", (v) => parseInt(v, 10)], ["d4-cu", "cu", parseFloat], ["d4-cd", "cd", parseFloat], ["d4-t", "t", parseFloat]].forEach(([id, key, f]) =>
    $(id).addEventListener("input", () => { S[key] = f($(id).value); changed(key); }));
  $("d4-tracks").addEventListener("change", () => { S.tracks = $("d4-tracks").checked; changed("tracks"); });
  $("d4-par").addEventListener("change", () => { S.parallax = $("d4-par").checked; changed("parallax"); });
  $("d4-dots").addEventListener("change", () => { S.dots = $("d4-dots").checked; renderHeat(); saveHash(); });
  $("d4-play").addEventListener("click", () => setPlaying(!playing));
  $("d4-heat").addEventListener("pointermove", heatHover);
  $("d4-heat").addEventListener("pointerdown", heatHover);
  $("d4-heat").addEventListener("pointerleave", () => { $("d4-tip").hidden = true; });

  // ---------- settings as JSON, the address, the try-it list ----------
  async function copyJson() {
    const txt = JSON.stringify(S, null, 1); $("d4-json").value = txt;
    try { await navigator.clipboard.writeText(txt); $("d4-json-note").textContent = "Copied, and shown in the box. Paste it back (or share the page address) to replay exactly."; }
    catch (e) { $("d4-json-note").textContent = "Copy it from the box."; }
  }
  $("d4-copy").addEventListener("click", copyJson);
  $("d4-load").addEventListener("click", () => {
    try { loadState(JSON.parse($("d4-json").value)); $("d4-json-note").textContent = "Loaded."; }
    catch (e) { $("d4-json-note").textContent = "That is not valid settings JSON: " + e.message; }
  });
  function loadState(o) {
    if (playing) setPlaying(false);
    S = sanitize(o);
    if (!S.view) S.view = clone(HOME);
    clampView(); syncUI(); runCluster(); clearTimeout(kTimer); runKnox(); renderVec(); schedule(); saveHash();
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-try]"); if (!b) return;
    let o; try { o = JSON.parse(b.getAttribute("data-try")); } catch (err) { return; }
    const go = o && o._go ? o._go : "d4-tools";
    loadState(o);
    const t = $(go); if (t) t.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth" });
  });

  // ---------- start ----------
  let start = null;
  try { if (location.hash.length > 1) start = JSON.parse(decodeURIComponent(location.hash.slice(1))); } catch (e) { start = null; }
  S = sanitize(start);
  resize(); clampView(); syncUI(); renderCov(); renderVec(); showFlash(-1);
  runCluster(); runKnox();
  let lastW = 0;
  const relayout = () => { const w = Math.round($("d4-tools").getBoundingClientRect().width); if (w === lastW) return; lastW = w; resize(); renderKd(); renderHeat(); renderCov(); };
  lastW = Math.round($("d4-tools").getBoundingClientRect().width);
  if (window.ResizeObserver) { let rt = 0; new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(relayout, 80); }).observe($("d4-tools")); }
  else window.addEventListener("resize", relayout);
})();
