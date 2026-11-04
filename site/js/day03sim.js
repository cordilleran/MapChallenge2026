// Day 3 page: the MAUP lab on simulated worlds. Computation is in day03simcore.js (and its worker); this file draws and wires.
(function () {
  "use strict";
  const C = window.D3S, N = C.N, CELL = C.CELL, NC = C.NC;
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const COL = { ground: "#0c1822", river: "#7fb7d6", amber: "#ffb454", ink: "#e9f1f5", muted: "#8aa0ae", line: "rgba(233,241,245,.62)", faint: "rgba(233,241,245,.12)" };
  const fmt = (v, d = 0) => (Number.isFinite(v) ? v.toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–");
  const SIZES = [0.6, 1, 1.4, 2, 3, 4, 5, 6, 8, 10, 12.8];            // km; every one a whole number of 200 m cells
  const BASINS = [2, 5, 10, 25, 50, 100, 250];                           // km2
  const PREF_LABEL = { watershed: "toward low ground (easy access)", textbook: "toward high values of X" };

  // ---------- state (everything needed to replay the page exactly) ----------
  const DEFAULT = {
    world: "textbook", worldSeed: 11, worldParams: {}, var: "X", var2: "Y",
    estimand: "mean", thr: 0.6, method: "cell", paint: "cells",
    frame: { kind: "grid", size: 4, ox: 0, oy: 0, vseed: 1, basinKm2: 25 },
    sample: { design: "random", n: 200, seed: 9, beta: 0 },
  };
  let S = JSON.parse(JSON.stringify(DEFAULT));
  let world = null, out = null, hill = null, curves = null, reps = {}, layerRange = {};

  // ---------- worker ----------
  let worker = null, jobId = 0;
  try { worker = new Worker("js/day03simworker.js"); } catch (e) { worker = null; }
  const pending = new Map();
  if (worker) worker.onmessage = (e) => { const m = e.data, h = pending.get(m.id); if (h) h(m); };
  function ask(msg, handler) {
    msg.id = ++jobId;
    if (!worker) {           // no worker (a local file, or an old browser): run here, smaller
      setTimeout(() => {
        try {
          if (msg.type === "rep") handler({ type: "rep", source: msg.source, res: C.replicate(msg.base, msg.source, Math.min(msg.R, 40)) });
          else handler(curvesHere(msg));
        } catch (err) { handler({ type: "error", message: err.message }); }
      }, 10);
      return msg.id;
    }
    pending.set(msg.id, (m) => { handler(m); if (m.type !== "progress") pending.delete(msg.id); });
    worker.postMessage(msg);
    return msg.id;
  }
  function curvesHere(m) {
    const o = { type: "curves", sizes: m.sizes, points: [], sweep: null, theory: null };
    for (const s of m.sizes) { const st = clone(m.base); if (st.frame.kind === "basin") st.frame.basinKm2 = s; else st.frame.size = s; const r = C.evaluate(world, st); o.points.push({ census: r.census, est: r.est, truth: r.truth }); }
    if (m.sweep) {           // 6 x 6 offsets of the frame, as the worker does
      const K = 6; o.sweep = [];
      for (let i = 0; i < K; i++) for (let j = 0; j < K; j++) {
        const st = clone(m.base); st.frame.ox = (i + 0.5) / K * st.frame.size; st.frame.oy = (j + 0.5) / K * st.frame.size;
        const r = C.evaluate(world, st); o.sweep.push({ census: r.census, est: r.est, truth: r.truth });
      }
    }
    if (m.theory) o.theory = C.krigeShare(m.base.worldParams, m.sizes.map((s) => Math.round(s / CELL)));
    return o;
  }
  const clone = (o) => JSON.parse(JSON.stringify(o));

  // ---------- helpers on the current world ----------
  const varsOf = () => C.VARIABLES[S.world];
  const vdef = (id) => varsOf().find((v) => v.id === id) || { id, label: id, unit: "", digits: 2 };
  const mapVar = () => (S.estimand === "rule" ? "dams" : S.var);
  function digitsOf(id) { const d = vdef(id).digits; return d === undefined ? 2 : d; }
  function rangeOf(id) {
    if (layerRange[id]) return layerRange[id];
    const a = Array.from(world.layers[id]).filter(Number.isFinite).sort((x, y) => x - y);
    const q = (p) => a[Math.min(a.length - 1, Math.floor(p * a.length))];
    return (layerRange[id] = { lo: q(0.02), hi: q(0.98), p50: q(0.5), p75: q(0.75), min: a[0], max: a[a.length - 1] });
  }
  function buildWorld() {
    world = C.makeWorld(S.world, S.worldSeed, S.worldParams);
    layerRange = {}; hill = null; reps = {};
    if (world.kind === "watershed") {
      const z = world.layers.elev; hill = new Float32Array(NC);
      const h = CELL * 1000, az = 315 * Math.PI / 180, alt = 45 * Math.PI / 180;
      for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
        const at = (i, j) => z[Math.min(N - 1, Math.max(0, j)) * N + Math.min(N - 1, Math.max(0, i))];
        const gx = (at(x + 1, y) - at(x - 1, y)) / (2 * h), gy = (at(x, y + 1) - at(x, y - 1)) / (2 * h);
        const slope = Math.atan(1.6 * Math.hypot(gx, gy)), aspect = Math.atan2(gy, -gx);
        hill[y * N + x] = Math.max(0, Math.sin(alt) * Math.cos(slope) + Math.cos(alt) * Math.sin(slope) * Math.cos(az - aspect));
      }
    }
  }

  // ---------- colour: one hue, dark to ice (sequential) ----------
  const STOPS = [[15, 34, 48], [31, 82, 112], [79, 145, 182], [150, 199, 224], [236, 247, 251]];
  function ramp(t) {
    t = Math.min(1, Math.max(0, t)) * (STOPS.length - 1);
    const i = Math.min(STOPS.length - 2, Math.floor(t)), f = t - i, a = STOPS[i], b = STOPS[i + 1];
    return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])];
  }

  // ---------- map ----------
  const map = $("s3-map"), mg = map.getContext("2d");
  const cellCanvas = document.createElement("canvas"); cellCanvas.width = N; cellCanvas.height = N;
  const cg = cellCanvas.getContext("2d");
  const edgeCanvas = document.createElement("canvas"), eg = edgeCanvas.getContext("2d");
  let MW = 0, DPR = 1;
  function sizeMap() {
    const w = map.parentElement.clientWidth;
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    MW = Math.round(w * DPR); map.width = MW; map.height = MW; map.style.height = w + "px";
    edgeCanvas.width = MW; edgeCanvas.height = MW;
  }
  function paintValues() {
    // value per cell to paint: the cell itself, or its zone's mean (every cell, or the sample)
    const id = mapVar(), v = world.layers[id], f = out.frame;
    if (S.paint === "cells") return v;
    const cells = S.paint === "census" ? out.pop : out.sample;
    const zs = C.zoneStats(v, cells, f), p = new Float64Array(NC).fill(NaN);
    for (const c of out.pop) { const z = f.id[c]; if (z >= 0 && zs.cnt[z]) p[c] = zs.mean[z]; }
    return p;
  }
  function drawMap() {
    const id = mapVar(), r = rangeOf(id), vals = paintValues(), img = cg.createImageData(N, N), d = img.data;
    const popMask = new Uint8Array(NC); for (const c of out.pop) popMask[c] = 1;
    for (let k = 0; k < NC; k++) {
      const o = k * 4, sh = hill ? 0.5 + 0.5 * hill[k] : 1;
      let rgb;
      if (!popMask[k]) rgb = [40 * sh + 10, 52 * sh + 12, 60 * sh + 14];                 // not in the population: relief only
      else if (!Number.isFinite(vals[k])) rgb = [24, 34, 42];                             // a zone with no site
      else { const c = ramp((vals[k] - r.lo) / (r.hi - r.lo || 1)); const s2 = hill ? 0.72 + 0.28 * hill[k] : 1; rgb = [c[0] * s2, c[1] * s2, c[2] * s2]; }
      d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = 255;
      if (popMask[k] && vdef(id).pop === "stream") { d[o] = Math.min(255, rgb[0] * 1.15); }
    }
    cg.putImageData(img, 0, 0);
    mg.imageSmoothingEnabled = vdef(id).pop !== "stream" && S.paint === "cells";
    mg.drawImage(cellCanvas, 0, 0, MW, MW);
    // zone edges at display resolution: where the left or upper neighbour is a different zone
    const zid = out.frame.id, ed = eg.createImageData(MW, MW), e = ed.data, k = N / MW;
    const zonePx = Math.sqrt(NC / Math.max(1, out.nz)) / k, edgeA = Math.round(165 * Math.min(1, Math.max(0.2, (zonePx - 2) / 10)));
    let prev = new Int32Array(MW).fill(-2), row = new Int32Array(MW);
    for (let py = 0; py < MW; py++) {
      const cy = Math.min(N - 1, Math.floor((py + 0.5) * k));
      for (let px = 0; px < MW; px++) row[px] = zid[cy * N + Math.min(N - 1, Math.floor((px + 0.5) * k))];
      for (let px = 0; px < MW; px++) {
        const z = row[px], l = px ? row[px - 1] : z, u = py ? prev[px] : z;
        if (l !== z || u !== z) { const o = (py * MW + px) * 4; e[o] = 233; e[o + 1] = 241; e[o + 2] = 245; e[o + 3] = edgeA; }
      }
      const t = prev; prev = row; row = t;
    }
    eg.putImageData(ed, 0, 0);
    mg.drawImage(edgeCanvas, 0, 0);
    // sites
    if (S.sample.design !== "census") {
      const rr = Math.max(1.6, 2.4 * DPR * Math.min(1, 300 / Math.max(1, out.sample.length)) + 0.8 * DPR);
      mg.fillStyle = COL.amber; mg.strokeStyle = COL.ground; mg.lineWidth = 1 * DPR;
      for (const c of out.sample) {
        const x = ((c % N) + 0.5) / N * MW, y = (((c / N) | 0) + 0.5) / N * MW;
        mg.beginPath(); mg.arc(x, y, rr, 0, 2 * Math.PI); mg.fill(); mg.stroke();
      }
    }
    // scale bar (10 km) and north arrow
    const bar = 10 / (N * CELL) * MW, x0 = 12 * DPR, y0 = MW - 14 * DPR;
    mg.fillStyle = "rgba(12,24,34,.72)"; mg.fillRect(x0 - 6 * DPR, y0 - 18 * DPR, bar + 12 * DPR, 26 * DPR);
    mg.strokeStyle = COL.ink; mg.lineWidth = 1.5 * DPR; mg.beginPath(); mg.moveTo(x0, y0 - 4 * DPR); mg.lineTo(x0, y0); mg.lineTo(x0 + bar, y0); mg.lineTo(x0 + bar, y0 - 4 * DPR); mg.stroke();
    mg.fillStyle = COL.ink; mg.font = `${10 * DPR}px "IBM Plex Mono", monospace`; mg.fillText("10 km", x0 + 2 * DPR, y0 - 6 * DPR);
    const nx = MW - 18 * DPR, ny = 16 * DPR;
    mg.beginPath(); mg.moveTo(nx, ny - 8 * DPR); mg.lineTo(nx + 5 * DPR, ny + 6 * DPR); mg.lineTo(nx, ny + 3 * DPR); mg.lineTo(nx - 5 * DPR, ny + 6 * DPR); mg.closePath(); mg.fillStyle = COL.amber; mg.fill();
    mg.fillStyle = COL.ink; mg.fillText("N", nx - 3.5 * DPR, ny + 18 * DPR);
    drawLegend(id, r);
  }
  function drawLegend(id, r) {
    const s = $("s3-legend"); while (s.firstChild) s.removeChild(s.firstChild);
    const W = 260, H = 34; s.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const add = (n, a, txt) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (txt !== undefined) e.textContent = txt; s.appendChild(e); return e; };
    const g = add("linearGradient", { id: "s3-grad" });
    STOPS.forEach((c, i) => {
      const st = document.createElementNS(NS, "stop");
      st.setAttribute("offset", i / (STOPS.length - 1)); st.setAttribute("stop-color", `rgb(${c.join(",")})`);
      g.appendChild(st);
    });
    add("rect", { x: 8, y: 4, width: W - 16, height: 9, fill: "url(#s3-grad)", rx: 1 });
    const dg = digitsOf(id), u = vdef(id).unit;
    add("text", { x: 8, y: 27, class: "tk" }, fmt(r.lo, dg));
    add("text", { x: W - 8, y: 27, class: "tk", "text-anchor": "end" }, fmt(r.hi, dg) + (u ? " " + u : ""));
    add("text", { x: W / 2, y: 27, class: "tk", "text-anchor": "middle" }, vdef(id).label);
  }

  // ---------- readouts ----------
  const EST_TEXT = {
    mean: "the population mean over every cell",
    varshare: "the share of variance between zones (no single true value: it belongs to the zoning)",
    corr: "the correlation across zones, against the correlation across cells",
    exceed: "the share of the population above the threshold",
    rule: "total dam capacity on the network (dams)",
    rank: "how well zone values from the sites rank the zones (1 = same order as every cell)",
  };
  function fmtEst(v) {
    if (!Number.isFinite(v)) return "–";
    if (S.estimand === "mean") return fmt(v, digitsOf(S.var)) + (vdef(S.var).unit ? " " + vdef(S.var).unit : "");
    if (S.estimand === "exceed") return fmt(100 * v, 1) + " %";
    if (S.estimand === "rule") return fmt(v, 0);
    return fmt(v, 2);
  }
  function readouts() {
    $("r-truth").textContent = S.estimand === "varshare" ? "n/a" : fmtEst(out.truth);
    $("r-census").textContent = fmtEst(out.census);
    $("r-est").textContent = S.sample.design === "census" ? fmtEst(out.census) : fmtEst(out.est);
    const est = S.sample.design === "census" ? out.census : out.est;
    const err = est - (S.estimand === "varshare" ? out.census : out.truth);
    let errTxt = "–";
    if (Number.isFinite(err)) {
      if (S.estimand === "exceed") errTxt = (err >= 0 ? "+" : "−") + fmt(Math.abs(100 * err), 1) + " pts";
      else if (S.estimand === "mean" || S.estimand === "rule") {
        // a percentage only where the truth is clearly away from zero (lognormal values, or the dam total); the textbook X has mean 0
        const base = out.truth, showPct = S.estimand === "rule" || S.worldParams.marginal === "lognormal";
        errTxt = (err >= 0 ? "+" : "−") + fmtEst(Math.abs(err)).replace(/ .*/, "") + (showPct && Number.isFinite(base) && Math.abs(base) > 1e-9 ? ` (${err >= 0 ? "+" : "−"}${fmt(Math.abs(100 * err / base), 1)} %)` : "");
      }
      else errTxt = (err >= 0 ? "+" : "−") + fmt(Math.abs(err), 2);
    }
    $("r-err").textContent = errTxt;
    $("r-errk").textContent = S.estimand === "varshare" ? "Sites minus every cell" : "Sites minus truth";
    const n = out.sample.length, unit = vdef(mapVar()).pop === "stream" ? "stream cells (200 m reaches)" : "cells";
    let line = `Estimating ${EST_TEXT[S.estimand]}. ${fmt(out.nz)} zones; `;
    line += S.sample.design === "census" ? `every one of ${fmt(out.pop.length)} ${unit} is measured.` : `${fmt(n)} sites among ${fmt(out.pop.length)} ${unit}; ${out.zonesSampled} of ${out.nz} zones hold a site.`;
    if (S.estimand === "corr") line += ` Across cells r = ${fmt(out.truth, 2)}.`;
    if ((S.estimand === "exceed" || S.estimand === "rule") && S.sample.design !== "census") line += ` Showing the ${S.method === "zone" ? "zone-first" : "cell-first"} result; the other way reads ${fmtEst(S.method === "zone" ? out.detail.cellFirst : out.detail.zoneFirst)} from the sites.`;
    if ((S.estimand === "exceed" || S.estimand === "rule") && S.sample.design === "census") line += ` Every cell, ${S.method === "zone" ? "zone first" : "cell first"}; the other way reads ${fmtEst(S.method === "zone" ? out.detail.censusCell : out.detail.censusZone)}.`;
    if (S.estimand === "varshare" && S.sample.design !== "census") {
      const one = C.zoneStats(world.layers[S.var], out.sample, out.frame).cnt.filter((c) => c === 1).length;
      if (one) line += ` ${one} zones hold a single site, and a single site has no variance within its zone, so the share from sites is pushed toward 1.`;
    }
    if (S.estimand === "rank" && Number.isFinite(out.est)) line += ` ${out.detail.zonesCompared} zones compared; the sites ${out.detail.sameTop ? "pick" : "miss"} the true top zone.`;
    if (S.estimand === "mean" && S.sample.design !== "census") line += ` Plain mean of the sites: ${fmtEst(out.detail.plain)}.`;
    $("r-line").textContent = line;
  }

  // ---------- small SVG helpers ----------
  function svgReset(s, W, H) { while (s.firstChild) s.removeChild(s.firstChild); s.setAttribute("viewBox", `0 0 ${W} ${H}`); }
  function el(s, name, a, txt) { const e = document.createElementNS(NS, name); for (const k in a) e.setAttribute(k, a[k]); if (txt !== undefined) e.textContent = txt; s.appendChild(e); return e; }
  function niceTicks(lo, hi, n) {
    const span = hi - lo || 1, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || mag * 10;
    const out = [], v0 = Math.ceil(lo / step) * step;
    for (let i = 0; i < 40; i++) { const v = v0 + i * step; if (v > hi + step * 1e-6) break; out.push(+v.toPrecision(12)); }   // bounded: equal values must not spin
    let dec = 0; while (dec < 10 && Math.abs(Math.round(step * 10 ** dec) - step * 10 ** dec) > 1e-6) dec++;
    out.dec = dec;                                                  // decimals the step needs (0.25 needs 2)
    return out;
  }
  // a range at least 1e-6 of its size wide, so equal values (a census) still get an axis
  function widen(lo, hi, frac) {
    const scale = Math.max(Math.abs(lo), Math.abs(hi), 1e-9);
    if (hi - lo < 1e-6 * scale) { const c = (lo + hi) / 2, h = Math.max(0.05 * scale, 1e-6); return [c - h, c + h]; }
    const pad = (hi - lo) * frac; return [lo - pad, hi + pad];
  }
  const tip = $("s3-tip");
  function showTip(evt, html) {
    tip.innerHTML = html; tip.hidden = false;
    const r = tip.parentElement.getBoundingClientRect();
    tip.style.left = Math.min(r.width - 220, Math.max(0, evt.clientX - r.left + 12)) + "px";
    tip.style.top = (evt.clientY - r.top + 12) + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  function scaleY(vals) {
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (S.estimand === "exceed") { lo = Math.min(lo, 0); }
    if (S.estimand === "varshare" || S.estimand === "rank") { lo = Math.min(lo, 0); hi = Math.max(hi, 1); }
    if (S.estimand === "corr") { lo = Math.min(lo, -1); hi = Math.max(hi, 1); }
    return widen(lo, hi, 0.08);
  }
  const asShown = (v) => (S.estimand === "exceed" ? 100 * v : v);

  // ---------- scale curve: the estimand against zone size ----------
  function drawCurve() {
    const s = $("s3-curve"), W = 420, H = 230, L = 52, R = 14, T = 26, B = 36;
    svgReset(s, W, H);
    const kind = S.frame.kind;
    if (!curves || kind === "svor" || kind === "bec") {
      el(s, "text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "ax" }, kind === "bec" ? "BEC zones have one size: the land sets it." : kind === "svor" ? "Sample Voronoi zones are set by the sites." : "computing…");
      return;
    }
    const xs = curves.sizes, pts = curves.points, logx = (v) => Math.log(v);
    const xlo = logx(xs[0]), xhi = logx(xs[xs.length - 1]);
    const X = (v) => L + (logx(v) - xlo) / (xhi - xlo) * (W - L - R);
    const all = [];
    pts.forEach((p) => { if (Number.isFinite(p.census)) all.push(asShown(p.census)); if (S.sample.design !== "census" && Number.isFinite(p.est)) all.push(asShown(p.est)); });
    if (Number.isFinite(out.truth) && S.estimand !== "varshare" && S.estimand !== "rank") all.push(asShown(out.truth));
    if (curves.theory) curves.theory.forEach((v) => all.push(v));
    if (!all.length) return;
    const [ylo, yhi] = scaleY(all), Y = (v) => H - B - (v - ylo) / (yhi - ylo) * (H - B - T);
    const yt = niceTicks(ylo, yhi, 4);
    for (const t of yt) { el(s, "line", { x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: COL.faint }); el(s, "text", { x: L - 6, y: Y(t) + 3, "text-anchor": "end", class: "tk" }, fmt(t, yt.dec)); }
    xs.forEach((v) => el(s, "text", { x: X(v), y: H - B + 14, "text-anchor": "middle", class: "tk" }, fmt(v, v < 2 && kind !== "basin" ? 1 : 0)));
    el(s, "text", { x: (L + W - R) / 2, y: H - 6, "text-anchor": "middle", class: "ax" }, kind === "basin" ? "sub-basin threshold (km², log scale)" : "zone size (km, log scale)");
    if (Number.isFinite(out.truth) && S.estimand !== "varshare" && S.estimand !== "rank") {
      el(s, "line", { x1: L, x2: W - R, y1: Y(asShown(out.truth)), y2: Y(asShown(out.truth)), stroke: COL.ink, "stroke-dasharray": "4 3" });
      el(s, "text", { x: W - R, y: Y(asShown(out.truth)) - 4, "text-anchor": "end", class: "tk" }, S.estimand === "corr" ? "r across cells" : "truth");
    }
    const path = (key, col, dash) => {
      let d = ""; pts.forEach((p, i) => { if (Number.isFinite(p[key])) d += (d ? "L" : "M") + X(xs[i]).toFixed(1) + "," + Y(asShown(p[key])).toFixed(1); });
      if (d) el(s, "path", Object.assign({ d, fill: "none", stroke: col, "stroke-width": 2 }, dash ? { "stroke-dasharray": dash } : {}));
    };
    if (curves.theory) {
      let d = ""; curves.theory.forEach((v, i) => { d += (i ? "L" : "M") + X(xs[i]).toFixed(1) + "," + Y(v).toFixed(1); });
      el(s, "path", { d, fill: "none", stroke: COL.muted, "stroke-width": 6, "stroke-opacity": 0.35, "stroke-linecap": "round" });
    }
    path("census", COL.river);
    if (S.sample.design !== "census") path("est", COL.amber);
    pts.forEach((p, i) => {
      for (const [key, col] of [["census", COL.river], ["est", COL.amber]]) {
        if (key === "est" && S.sample.design === "census") continue;
        if (!Number.isFinite(p[key])) continue;
        const c = el(s, "circle", { cx: X(xs[i]), cy: Y(asShown(p[key])), r: 3.5, fill: col, stroke: COL.ground, "stroke-width": 1 });
        const hit = el(s, "circle", { cx: X(xs[i]), cy: Y(asShown(p[key])), r: 9, fill: "transparent" });
        hit.addEventListener("pointerenter", (e) => showTip(e, `<b>${kind === "basin" ? fmt(xs[i]) + " km² threshold" : fmt(xs[i], 1) + " km zones"}</b><br>every cell, by zone: ${fmtEst(p.census)}` + (S.sample.design !== "census" ? `<br>sites, by zone: ${fmtEst(p.est)}` : "") + (curves.theory ? `<br>Krige's expectation: ${fmt(curves.theory[i], 2)}` : "")));
        hit.addEventListener("pointerleave", hideTip);
        void c;
      }
    });
    const cur = kind === "basin" ? S.frame.basinKm2 : S.frame.size;
    el(s, "line", { x1: X(cur), x2: X(cur), y1: T, y2: H - B, stroke: COL.amber, "stroke-opacity": 0.4 });
    let lx = L + 6;
    const key = (col, label, wide) => { el(s, "rect", { x: lx, y: 9, width: 12, height: wide ? 5 : 3, fill: col, "fill-opacity": wide ? 0.5 : 1 }); el(s, "text", { x: lx + 16, y: 14, class: "tk" }, label); lx += 22 + label.length * 6.1; };
    key(COL.river, "every cell");
    if (S.sample.design !== "census") key(COL.amber, "sites");
    if (curves.theory) key(COL.muted, "Krige's curve", true);
    else if (S.estimand === "varshare" && S.world === "textbook" && S.worldParams.marginal === "lognormal") el(s, "text", { x: W - R, y: T + 12, "text-anchor": "end", class: "tk" }, "theory band applies to normal values");
  }

  // ---------- offset sweep strip ----------
  function drawSweep() {
    const s = $("s3-sweep"), W = 420, H = 52;
    svgReset(s, W, H);
    const shiftable = S.frame.kind === "grid" || S.frame.kind === "hex";
    if (!shiftable || !curves || !curves.sweep) {
      el(s, "text", { x: W / 2, y: 30, "text-anchor": "middle", class: "tk" }, shiftable ? "computing…" : "This frame cannot be shifted.");
      $("r-sweep").textContent = ""; return;
    }
    const key = S.sample.design === "census" ? "census" : "est";
    const v = curves.sweep.map((p) => asShown(p[key])).filter(Number.isFinite);
    const ref = S.estimand === "varshare" || S.estimand === "rank" ? null : asShown(out.truth);
    const cur = asShown(S.sample.design === "census" ? out.census : out.est);
    const all = v.concat(ref !== null && Number.isFinite(ref) ? [ref] : [], Number.isFinite(cur) ? [cur] : []);
    let [lo, hi] = widen(Math.min(...all), Math.max(...all), 0.1);
    const X = (x) => 12 + (x - lo) / (hi - lo) * (W - 24);
    el(s, "line", { x1: 12, x2: W - 12, y1: 22, y2: 22, stroke: "rgba(233,241,245,.2)" });
    const st5 = niceTicks(lo, hi, 4);
    for (const t of st5) el(s, "text", { x: X(t), y: 46, "text-anchor": "middle", class: "tk" }, fmt(t, st5.dec));
    if (ref !== null && Number.isFinite(ref)) el(s, "line", { x1: X(ref), x2: X(ref), y1: 8, y2: 34, stroke: COL.ink, "stroke-width": 2 });
    curves.sweep.forEach((p, i) => {
      const x = asShown(p[key]); if (!Number.isFinite(x)) return;
      const c = el(s, "circle", { cx: X(x), cy: 22, r: 3.2, fill: S.sample.design === "census" ? "rgba(127,183,214,.45)" : "rgba(255,180,84,.4)" });
      c.addEventListener("pointerenter", (e) => showTip(e, `shift ${i + 1} of 36: ${fmtEst(p[key])}`)); c.addEventListener("pointerleave", hideTip);
    });
    if (Number.isFinite(cur)) el(s, "circle", { cx: X(cur), cy: 22, r: 5.5, fill: "none", stroke: S.sample.design === "census" ? COL.river : COL.amber, "stroke-width": 2 });
    const vv = curves.sweep.map((p) => p[key]).filter(Number.isFinite);
    $("r-sweep").textContent = vv.length ? `The same ${S.frame.kind === "grid" ? "grid" : "hexagons"} shifted to 36 positions: ${fmtEst(Math.min(...vv))} to ${fmtEst(Math.max(...vv))}${ref !== null ? " (white bar: the truth)" : ""}.` : "";
  }

  // ---------- replicates: rainclouds by source ----------
  const SOURCES = [
    { id: "world", label: "new worlds", R: 100, note: "same settings, new random world each time" },
    { id: "sample", label: "new samples", R: 200, note: "same world and zones, new sites" },
    { id: "zoning", label: "new zonings", R: 200, note: "same world and sites, zones shifted or reseeded" },
  ];
  function kde(vals, lo, hi, n) {
    const m = C.meanOf(vals), sd = Math.sqrt(C.meanOf(vals.map((v) => (v - m) ** 2)));
    const q = vals.slice().sort((a, b) => a - b), iqr = q[Math.floor(0.75 * q.length)] - q[Math.floor(0.25 * q.length)];
    let bw = 0.9 * Math.min(sd, iqr / 1.34 || sd) * Math.pow(vals.length, -0.2);
    if (!(bw > 0)) bw = (hi - lo) / 50 || 1;
    const xs = [], ys = [];
    for (let i = 0; i < n; i++) { const x = lo + i * (hi - lo) / (n - 1); let s = 0; for (const v of vals) { const d = (x - v) / bw; s += Math.exp(-0.5 * d * d); } xs.push(x); ys.push(s); }
    return { xs, ys };
  }
  function drawReps() {
    const s = $("s3-reps"), W = 860, rowH = 70, T = 26, B = 34, L = 130, R = 20;
    const rows = SOURCES.filter((src) => reps[src.id] && reps[src.id].res);
    const H = T + B + Math.max(1, SOURCES.length) * rowH;
    svgReset(s, W, H);
    const key = S.sample.design === "census" ? "census" : "est";
    const all = [];
    for (const src of rows) for (const r of reps[src.id].res) { if (Number.isFinite(r[key])) all.push(asShown(r[key])); if (S.estimand !== "varshare" && S.estimand !== "rank" && Number.isFinite(r.truth)) all.push(asShown(r.truth)); }
    if (Number.isFinite(out.truth) && S.estimand !== "varshare" && S.estimand !== "rank") all.push(asShown(out.truth));
    SOURCES.forEach((src, i) => {
      const y = T + i * rowH + rowH / 2;
      el(s, "text", { x: 8, y: y - 4, class: "lg" }, src.label);
      el(s, "text", { x: 8, y: y + 11, class: "tk" }, reps[src.id] && reps[src.id].busy ? `running ${reps[src.id].i || 0} / ${src.R}` : reps[src.id] && reps[src.id].res ? `${reps[src.id].res.length} runs` : "not run yet");
    });
    if (!all.length) { el(s, "text", { x: (L + W) / 2, y: T + rowH * 1.5, "text-anchor": "middle", class: "ax" }, "Run a source to see where the estimate lands."); return; }
    let [lo, hi] = widen(Math.min(...all), Math.max(...all), 0.06);
    const X = (v) => L + (v - lo) / (hi - lo) * (W - L - R);
    const rt = niceTicks(lo, hi, 7);
    for (const t of rt) { el(s, "line", { x1: X(t), x2: X(t), y1: T, y2: H - B, stroke: COL.faint }); el(s, "text", { x: X(t), y: H - B + 14, "text-anchor": "middle", class: "tk" }, fmt(t, rt.dec)); }
    el(s, "text", { x: (L + W - R) / 2, y: H - 6, "text-anchor": "middle", class: "ax" }, (S.sample.design === "census" ? "every cell, by zone: " : "sites, by zone: ") + C.ESTIMANDS[S.estimand].label + (S.estimand === "exceed" ? " (%)" : ""));
    if (Number.isFinite(out.truth) && S.estimand !== "varshare" && S.estimand !== "rank") {
      el(s, "line", { x1: X(asShown(out.truth)), x2: X(asShown(out.truth)), y1: T - 6, y2: H - B, stroke: COL.ink, "stroke-width": 1.5, "stroke-dasharray": "4 3" });
      el(s, "text", { x: X(asShown(out.truth)), y: T - 10, "text-anchor": "middle", class: "tk" }, "truth, this world");
    }
    SOURCES.forEach((src, i) => {
      const rp = reps[src.id]; if (!rp || !rp.res) return;
      const y = T + i * rowH + rowH / 2, v = rp.res.map((r) => asShown(r[key])).filter(Number.isFinite);
      if (!v.length) return;
      if (src.id === "world" && S.estimand !== "varshare" && S.estimand !== "rank") {
        const tm = C.meanOf(rp.res.map((r) => asShown(r.truth)).filter(Number.isFinite));
        el(s, "line", { x1: X(tm), x2: X(tm), y1: y - rowH / 2 + 6, y2: y + rowH / 2 - 6, stroke: COL.muted, "stroke-width": 2 });
        el(s, "text", { x: X(tm) + 4, y: y + rowH / 2 - 8, class: "tk" }, "mean over worlds");
      }
      const k = kde(v, lo, hi, 140); const mx = Math.max(...k.ys);
      let d = ""; k.xs.forEach((x, j) => { d += (j ? "L" : "M") + X(x).toFixed(1) + "," + (y - 4 - k.ys[j] / mx * 24).toFixed(1); });
      d += `L${X(hi)},${y - 4}L${X(lo)},${y - 4}Z`;
      el(s, "path", { d, fill: S.sample.design === "census" ? "rgba(127,183,214,.42)" : "rgba(255,180,84,.38)", stroke: "none" });
      const q = v.slice().sort((a, b) => a - b), qq = (p) => q[Math.min(q.length - 1, Math.floor(p * q.length))];
      el(s, "line", { x1: X(qq(0.05)), x2: X(qq(0.95)), y1: y + 2, y2: y + 2, stroke: COL.ink, "stroke-opacity": 0.6 });
      el(s, "rect", { x: X(qq(0.25)), y: y - 1, width: Math.max(1, X(qq(0.75)) - X(qq(0.25))), height: 6, fill: "none", stroke: COL.ink, "stroke-width": 1 });
      el(s, "line", { x1: X(qq(0.5)), x2: X(qq(0.5)), y1: y - 2, y2: y + 6, stroke: COL.ink, "stroke-width": 2 });
      v.forEach((x, j) => el(s, "circle", { cx: X(x), cy: y + 12 + ((j * 7919) % 11), r: 1.6, fill: S.sample.design === "census" ? COL.river : COL.amber, "fill-opacity": 0.55 }));
      const hit = el(s, "rect", { x: L, y: y - rowH / 2, width: W - L - R, height: rowH, fill: "transparent" });
      const sm = C.summarize(rp.res.map((r) => ({ truth: S.estimand === "varshare" || S.estimand === "rank" ? NaN : r.truth, est: r[key] })), "est");
      hit.addEventListener("pointerenter", (e) => showTip(e, `<b>${src.label}</b> (${src.note})<br>median ${fmtEst(qq(0.5) / (S.estimand === "exceed" ? 100 : 1))}; middle 90 %: ${fmtEst(qq(0.05) / (S.estimand === "exceed" ? 100 : 1))} to ${fmtEst(qq(0.95) / (S.estimand === "exceed" ? 100 : 1))}<br>SD ${fmt(sm.sd, 3)}`));
      hit.addEventListener("pointerleave", hideTip);
    });
    repTable();
  }
  function repTable() {
    const key = S.sample.design === "census" ? "census" : "est", rows = [];
    const scale = S.estimand === "exceed" ? 100 : 1, dg = S.estimand === "mean" ? digitsOf(S.var) : S.estimand === "rule" ? 0 : S.estimand === "exceed" ? 1 : 3;
    for (const src of SOURCES) {
      const rp = reps[src.id]; if (!rp || !rp.res) continue;
      const noTruth = S.estimand === "varshare" || S.estimand === "rank";
      const sm = C.summarize(rp.res.map((r) => ({ truth: noTruth ? NaN : r.truth, est: r[key] })), "est");
      let extra = "";
      if (S.estimand === "mean" && S.sample.design !== "census" && src.id !== "zoning") {
        // the plain mean of the sites: its spread against the independent-sites formula
        const nse = C.meanOf(rp.res.map((r) => r.naiveSE).filter(Number.isFinite));
        const pl = rp.res.map((r) => r.plain).filter(Number.isFinite), pm = C.meanOf(pl);
        const psd = Math.sqrt(C.meanOf(pl.map((x) => (x - pm) ** 2)) * pl.length / Math.max(1, pl.length - 1));
        extra = `${fmt(nse, dg)} against ${fmt(psd, dg)} (× ${fmt(psd / nse, 1)})`;
      }
      if (S.estimand === "rank") { const st = rp.res.filter((r) => r.sameTop).length; extra = `same top zone in ${fmt(100 * st / rp.res.length)} %`; }
      rows.push(`<tr><th>${src.label}</th><td>${rp.res.length}</td><td>${fmt(sm.mean * scale, dg)}</td><td>${noTruth ? "–" : fmt(sm.bias * scale, dg)}</td><td>${fmt(sm.sd * scale, dg)}</td><td>${noTruth ? "–" : fmt(sm.rmse * scale, dg)}</td><td>${extra || "–"}</td></tr>`);
    }
    const lastHead = S.estimand === "rank" ? "Top zone" : "Plain mean: textbook SE against actual spread";
    $("s3-reptable").innerHTML = rows.length ? `<table><thead><tr><th>Redraw</th><th>Runs</th><th>Mean</th><th>Bias</th><th>SD</th><th>RMSE</th><th>${lastHead}</th></tr></thead><tbody>${rows.join("")}</tbody></table>` : "";
  }
  function runSource(src) {
    if (reps[src.id] && reps[src.id].busy) return;
    const snapshot = clone(S); reps[src.id] = { busy: true, i: 0 }; drawReps();
    ask({ type: "rep", base: snapshot, source: src.id, R: src.R }, (m) => {
      if (JSON.stringify(snapshot) !== JSON.stringify(S)) return;              // settings changed meanwhile: drop
      if (m.type === "progress") { reps[src.id].i = m.i; drawReps(); return; }
      if (m.type === "error") { reps[src.id] = null; $("s3-repnote").textContent = "Replicates failed: " + m.message; drawReps(); return; }
      reps[src.id] = { res: m.res }; drawReps();
    });
  }

  // ---------- formulas (plain words, maths, the live code) ----------
  const WORDS = {
    mean: ["Each zone's sites give that zone a mean. The regional number weights each zone by its share of the population (area, or channel length), over the zones that hold a site. With every cell measured, this is the true mean whatever the zones: an average of averages, weighted by size, is the average.",
      "Ŷ = Σ<sub>z∈S</sub> W<sub>z</sub> ȳ<sub>z</sub> ⁄ Σ<sub>z∈S</sub> W<sub>z</sub>, &nbsp; S = zones with a site, W<sub>z</sub> = cells in zone z"],
    varshare: ["How much of the total variation lies between zone means rather than within zones. Bigger zones average more away, so the share falls as zones grow. For a known covariance there is an expected value: Krige's relation, drawn as the grey band when every cell is measured on a grid.",
      "S<sub>T</sub> = Σ<sub>i</sub>(y<sub>i</sub> − ȳ)², &nbsp; S<sub>B</sub> = Σ<sub>z</sub> n<sub>z</sub>(ȳ<sub>z</sub> − ȳ)², &nbsp; share = S<sub>B</sub> ⁄ S<sub>T</sub> ≈ 1 − γ̄(v,v) ⁄ γ̄(D,D)"],
    corr: ["Pearson's r between the zone means of two variables, each zone counted once. Averaging strips out noise that the two variables do not share, so r usually climbs with zone size; on this world, where the variables disagree at short range and agree at long range, it can change sign.",
      "r = Σ<sub>z</sub>(x̄<sub>z</sub> − x̄)(ȳ<sub>z</sub> − ȳ) ⁄ √(Σ<sub>z</sub>(x̄<sub>z</sub> − x̄)² Σ<sub>z</sub>(ȳ<sub>z</sub> − ȳ)²)"],
    exceed: ["The share of the population above a threshold, two ways. Cell first: the share of each zone's sites above it, weighted by zone. Zone first: a zone counts wholly if its mean is above it, as a coarse map of zone averages would show. A threshold of a mean is not the mean of a threshold.",
      "cell first: Σ W<sub>z</sub> p̂<sub>z</sub> ⁄ Σ W<sub>z</sub>, &nbsp; p̂<sub>z</sub> = share of the zone's sites above t; &nbsp; zone first: Σ W<sub>z</sub> 𝟙[ȳ<sub>z</sub> > t] ⁄ Σ W<sub>z</sub>"],
    rule: ["Dam capacity per km of stream from four lines of evidence after BRAT: channel slope, stream power at the two-year flood, a low-flow index and riparian vegetation, each a 0 to 1 membership, multiplied. Cell first: the rule on every 200 m reach, then summed. Zone first: the rule on each zone's average inputs, as a coarse planning layer would. Zones with no site take the average rate of sampled zones.",
      "D = 30 · m<sub>S</sub>(S) · m<sub>Ω</sub>(γ Q<sub>2</sub> S) · m<sub>L</sub>(Q<sub>low</sub>) · v &nbsp; dams/km; &nbsp; total = Σ<sub>z</sub> D̄<sub>z</sub> L<sub>z</sub> × L ⁄ L<sub>sampled</sub>"],
    rank: ["Would you fund the right zones? Spearman's rank correlation between each zone's value from its sites and its value from every cell, over zones with a site; and whether the sites pick the same top zone. Small zones hold few sites and rank noisily; big zones rank well but say less.",
      "ρ = corr(rank(ȳ<sub>z</sub><sup>sites</sup>), rank(ȳ<sub>z</sub><sup>all</sup>))"],
  };
  function formulas() {
    const w = WORDS[S.estimand];
    $("f-words").textContent = w[0];
    $("f-maths").innerHTML = w[1];
    let code = C.ESTIMANDS[S.estimand].run.toString();
    if (S.estimand === "rule") code = C.damCapacity.toString() + "\n\n" + code;
    $("f-code").textContent = code;
  }

  // ---------- update cycle ----------
  let curvesTimer = 0, queued = false, needCurves = false;
  function update(withCurves) {
    needCurves = needCurves || withCurves;
    if (queued) return; queued = true;
    requestAnimationFrame(() => {
      queued = false;
      out = C.evaluate(world, S);
      drawMap(); readouts(); formulas();
      if (needCurves) {
        needCurves = false; curves = null; drawCurve(); drawSweep();
        reps = {}; drawReps(); $("s3-reptable").innerHTML = ""; $("s3-repnote").textContent = "";
        clearTimeout(curvesTimer);
        curvesTimer = setTimeout(requestCurves, 120);
      }
      saveHash();
    });
  }
  function requestCurves() {
    const kind = S.frame.kind; if (kind === "svor" || kind === "bec") { curves = { sizes: [], points: [] }; drawCurve(); drawSweep(); return; }
    const snapshot = clone(S);
    const theory = S.world === "textbook" && S.estimand === "varshare" && kind === "grid" && S.sample.design === "census" && S.worldParams.marginal !== "lognormal";   // Krige's relation is for the Gaussian field
    ask({ type: "curves", base: snapshot, sizes: kind === "basin" ? BASINS : SIZES, sweep: kind === "grid" || kind === "hex", theory }, (m) => {
      if (JSON.stringify(snapshot) !== JSON.stringify(S) || m.type !== "curves") return;
      curves = m; drawCurve(); drawSweep();
    });
  }

  // ---------- controls ----------
  function seg(id, value) { document.querySelectorAll(`#${id} button`).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === value))); }
  function fillVars() {
    const opts = varsOf().map((v) => `<option value="${v.id}">${v.label}${v.unit ? " (" + v.unit + ")" : ""}</option>`).join("");
    $("s3-var").innerHTML = opts; $("s3-var2").innerHTML = opts;
    $("s3-var").value = S.var; $("s3-var2").value = S.var2;
  }
  function syncControls() {
    seg("s3-world", S.world); seg("s3-frame", S.frame.kind); seg("s3-design", S.sample.design); seg("s3-est", S.estimand); seg("s3-method", S.method); seg("s3-paint", S.paint);
    fillVars();
    document.querySelectorAll("#s3-est button[data-k=rule]").forEach((b) => { b.hidden = S.world !== "watershed"; });
    document.querySelectorAll("#s3-frame button[data-k=basin], #s3-frame button[data-k=bec]").forEach((b) => { b.hidden = S.world !== "watershed"; });
    $("s3-var").disabled = S.estimand === "rule";
    $("s3-var2wrap").hidden = S.estimand !== "corr";
    $("s3-thrwrap").hidden = S.estimand !== "exceed";
    $("s3-methodwrap").hidden = !(S.estimand === "exceed" || S.estimand === "rule");
    const fk = S.frame.kind, sz = $("s3-size");
    $("s3-sizewrap").hidden = fk === "svor" || fk === "bec";
    if (fk === "basin") { sz.max = BASINS.length - 1; sz.value = Math.max(0, BASINS.indexOf(S.frame.basinKm2)); $("s3-size-v").textContent = `sub-basins from ${fmt(S.frame.basinKm2)} km²`; }
    else { sz.max = SIZES.length - 1; sz.value = Math.max(0, SIZES.indexOf(S.frame.size)); $("s3-size-v").textContent = `${fmt(S.frame.size, S.frame.size < 2 ? 1 : 0)} km (${fmt(S.frame.size * S.frame.size, 1)} km²)`; }
    $("s3-size-k").textContent = fk === "basin" ? "threshold" : "size";
    $("s3-shift").hidden = !(fk === "grid" || fk === "hex");
    $("s3-reshuffle").hidden = fk !== "vor";
    const des = S.sample.design;
    $("s3-nwrap").hidden = des === "census"; $("s3-n").value = S.sample.n; $("s3-n-v").textContent = fmt(S.sample.n);
    $("s3-betawrap").hidden = des !== "random"; $("s3-beta").value = S.sample.beta; $("s3-beta-v").textContent = S.sample.beta ? `${fmt(S.sample.beta, 1)} ${PREF_LABEL[S.world]}` : "none (simple random)";
    $("s3-redraw").hidden = des === "census";
    if (S.estimand === "exceed") {
      const r = rangeOf(S.var), t = $("s3-thr"); t.min = r.min; t.max = r.max; t.step = (r.max - r.min) / 200; t.value = S.thr;
      $("s3-thr-v").textContent = fmt(S.thr, digitsOf(S.var)) + (vdef(S.var).unit ? " " + vdef(S.var).unit : "");
    }
    $("s3-seed-v").textContent = `world ${S.worldSeed}`;
    $("s3-tbwrap").hidden = S.world !== "textbook";
    if (S.world === "textbook") {
      const p = Object.assign({}, C.TEXTBOOK_DEFAULTS, S.worldParams);
      for (const k of ["rhoShort", "rhoLong", "longShare", "corShort", "corLong", "nugget"]) { $("tb-" + k).value = p[k]; $("tb-" + k + "-v").textContent = fmt(p[k], 2); }
      $("tb-nu").value = p.nu; $("tb-marginal").value = p.marginal;
      $("tb-range").textContent = `correlation falls to 0.05 at about ${fmt(C.practicalRange(p.rhoShort, p.nu), 1)} km (short part) and ${fmt(C.practicalRange(p.rhoLong, p.nu), 1)} km (long part)`;
    }
    $("s3-wsdemwrap").hidden = S.world !== "watershed";
    if (S.world === "watershed") { const r = (S.worldParams.demRes || 200); $("ws-dem").value = r; $("ws-dem-v").textContent = `${fmt(r)} m`; }
  }
  function setWorld(k) {
    S.world = k; S.worldParams = {};
    if (k === "textbook") { S.var = "X"; S.var2 = "Y"; if (S.estimand === "rule") S.estimand = "mean"; if (S.frame.kind === "basin" || S.frame.kind === "bec") S.frame.kind = "grid"; }
    else { S.var = "precip"; S.var2 = "elev"; }
    buildWorld(); defaultThr(); syncControls(); update(true);
  }
  function defaultThr() { const r = rangeOf(S.estimand === "rule" ? "dams" : S.var); S.thr = +r.p75.toPrecision(3); }
  document.querySelectorAll("#s3-world button").forEach((b) => b.addEventListener("click", () => setWorld(b.dataset.k)));
  $("s3-newworld").addEventListener("click", () => { S.worldSeed = (S.worldSeed * 48271) % 2147483647; buildWorld(); syncControls(); update(true); });
  document.querySelectorAll("#s3-frame button").forEach((b) => b.addEventListener("click", () => {
    S.frame.kind = b.dataset.k; S.frame.ox = 0; S.frame.oy = 0;
    if (b.dataset.k === "svor" && S.sample.design === "census") S.sample.design = "random";
    if (b.dataset.k === "svor" && S.sample.design === "stratified") S.sample.design = "random";
    syncControls(); update(true);
  }));
  document.querySelectorAll("#s3-design button").forEach((b) => b.addEventListener("click", () => {
    if (S.frame.kind === "svor" && (b.dataset.k === "census" || b.dataset.k === "stratified")) { $("s3-design-note").textContent = "Sample Voronoi zones are made from the sites, so they need random or systematic sites."; return; }
    $("s3-design-note").textContent = "";
    S.sample.design = b.dataset.k; syncControls(); update(true);
  }));
  document.querySelectorAll("#s3-est button").forEach((b) => b.addEventListener("click", () => {
    S.estimand = b.dataset.k;
    if (S.estimand === "exceed") defaultThr();
    if (S.estimand === "corr" && S.var2 === S.var) S.var2 = varsOf().find((v) => v.id !== S.var && v.pop === "all").id;
    syncControls(); update(true);
  }));
  document.querySelectorAll("#s3-method button").forEach((b) => b.addEventListener("click", () => { S.method = b.dataset.k; syncControls(); update(true); }));
  document.querySelectorAll("#s3-paint button").forEach((b) => b.addEventListener("click", () => { S.paint = b.dataset.k; syncControls(); update(false); }));
  $("s3-var").addEventListener("change", (e) => {
    S.var = e.target.value;
    if (S.estimand === "exceed") defaultThr();
    if (vdef(S.var).pop === "stream" && S.estimand === "corr") S.estimand = "mean";
    syncControls(); update(true);
  });
  $("s3-var2").addEventListener("change", (e) => { S.var2 = e.target.value; update(true); });
  $("s3-size").addEventListener("input", (e) => {
    if (S.frame.kind === "basin") S.frame.basinKm2 = BASINS[+e.target.value]; else { S.frame.size = SIZES[+e.target.value]; S.frame.ox = 0; S.frame.oy = 0; }
    syncControls(); update(true);
  });
  $("s3-reshuffle").addEventListener("click", () => { S.frame.vseed = (S.frame.vseed * 16807 + 1) % 2147483647; update(true); });
  $("s3-n").addEventListener("input", (e) => { S.sample.n = +e.target.value; $("s3-n-v").textContent = fmt(S.sample.n); update(true); });
  $("s3-beta").addEventListener("input", (e) => { S.sample.beta = +e.target.value; syncControls(); update(true); });
  $("s3-redraw").addEventListener("click", () => { S.sample.seed = (S.sample.seed * 16807 + 7) % 2147483647; update(true); });
  $("s3-thr").addEventListener("input", (e) => { S.thr = +(+e.target.value).toPrecision(4); $("s3-thr-v").textContent = fmt(S.thr, digitsOf(S.var)) + (vdef(S.var).unit ? " " + vdef(S.var).unit : ""); update(true); });
  for (const k of ["rhoShort", "rhoLong", "longShare", "corShort", "corLong", "nugget"]) {
    $("tb-" + k).addEventListener("change", (e) => { S.worldParams[k] = +e.target.value; buildWorld(); syncControls(); update(true); });
    $("tb-" + k).addEventListener("input", (e) => { $("tb-" + k + "-v").textContent = fmt(+e.target.value, 2); });
  }
  $("tb-nu").addEventListener("change", (e) => { S.worldParams.nu = +e.target.value; buildWorld(); syncControls(); update(true); });
  $("tb-marginal").addEventListener("change", (e) => { S.worldParams.marginal = e.target.value; buildWorld(); syncControls(); update(true); });
  $("ws-dem").addEventListener("change", (e) => { S.worldParams.demRes = +e.target.value; buildWorld(); syncControls(); update(true); });
  $("ws-dem").addEventListener("input", (e) => { $("ws-dem-v").textContent = `${fmt(+e.target.value)} m`; });
  SOURCES.forEach((src) => $("s3-run-" + src.id).addEventListener("click", () => runSource(src)));
  $("s3-run-all").addEventListener("click", () => SOURCES.forEach(runSource));

  // drag or arrow keys shift a grid or hexagon layout
  let drag = null;
  map.addEventListener("pointerdown", (e) => {
    if (S.frame.kind !== "grid" && S.frame.kind !== "hex") { hover(e); return; }
    drag = { x: e.clientX, y: e.clientY, ox: S.frame.ox, oy: S.frame.oy }; map.setPointerCapture(e.pointerId);
  });
  map.addEventListener("pointermove", (e) => {
    if (drag) {
      const k = N * CELL / map.clientWidth, s = S.frame.size;
      S.frame.ox = (((drag.ox - (e.clientX - drag.x) * k) % s) + s) % s; S.frame.oy = (((drag.oy - (e.clientY - drag.y) * k) % s) + s) % s;
      update(false);
    } else hover(e);
  });
  map.addEventListener("pointerup", (e) => { if (drag) { const moved = Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) >= 5; drag = null; if (moved) update(true); else hover(e); } });
  map.addEventListener("pointercancel", () => { drag = null; });
  map.addEventListener("pointerleave", () => { $("s3-info").textContent = "Hover or tap the map to read a cell and its zone."; });
  map.addEventListener("keydown", (e) => {
    if (S.frame.kind !== "grid" && S.frame.kind !== "hex") return;
    const d = { ArrowLeft: [1, 0], ArrowRight: [-1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[e.key]; if (!d) return;
    e.preventDefault(); const s = S.frame.size;
    S.frame.ox = (((S.frame.ox + d[0] * 0.4) % s) + s) % s; S.frame.oy = (((S.frame.oy + d[1] * 0.4) % s) + s) % s; update(true);
  });
  let zcache = null;
  function hover(e) {
    const r = map.getBoundingClientRect(), x = Math.floor((e.clientX - r.left) / r.width * N), y = Math.floor((e.clientY - r.top) / r.height * N);
    if (x < 0 || y < 0 || x >= N || y >= N) return;
    const c = y * N + x, id = mapVar(), v = world.layers[id][c], z = out.frame.id[c], dg = digitsOf(id), u = vdef(id).unit ? " " + vdef(id).unit : "";
    let t = Number.isFinite(v) ? `This cell: ${vdef(id).label} ${fmt(v, dg)}${u}` : "This cell is not on the stream network";
    if (S.world === "watershed") t += ` · ${fmt(world.layers.elev[c])} m · ${C.BEC[world.bec[c]].code}-like · drains ${fmt(world.area[c], 1)} km²`;
    if (z >= 0) {
      if (!zcache || zcache.out !== out || zcache.id !== id) zcache = { out, id, all: C.zoneStats(world.layers[id], out.pop, out.frame), smp: C.zoneStats(world.layers[id], out.sample, out.frame) };   // once per update
      const all = zcache.all, smp = zcache.smp;
      t += `. Its zone: ${fmt(all.cnt[z])} ${vdef(id).pop === "stream" ? "reaches" : "cells"}, mean ${fmt(all.mean[z], dg)}${u}`;
      if (S.sample.design !== "census") t += smp.cnt[z] ? `; ${smp.cnt[z]} site${smp.cnt[z] > 1 ? "s" : ""} read ${fmt(smp.mean[z], dg)}${u}.` : "; no site.";
    }
    $("s3-info").textContent = t;
  }

  // ---------- settings as JSON (and in the address), replayable ----------
  let hashTimer = 0;
  function saveHash() {                                  // 300 ms after the last change
    clearTimeout(hashTimer);
    hashTimer = setTimeout(() => { try { history.replaceState(null, "", "#" + encodeURIComponent(JSON.stringify(S))); } catch (e) { /* file:// or sandbox */ } }, 300);
  }
  // accept only known keys and values; clamp numbers to the sliders' ranges; anything bad falls back to DEFAULT
  const TB_RANGE = { rhoShort: [0.2, 2], rhoLong: [2, 12], longShare: [0, 1], corShort: [-0.95, 0.95], corLong: [-0.95, 0.95], nugget: [0, 0.8] };
  const num = (v, lo, hi, dflt) => { v = typeof v === "string" && v.trim() !== "" ? +v : v; return typeof v === "number" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : dflt; };
  const pick = (v, list, dflt) => (list.includes(v) ? v : dflt);
  const seedOf = (v, dflt) => Math.round(num(v, 1, 2147483646, dflt));
  function sanitize(o) {
    const d = clone(DEFAULT);
    if (!o || typeof o !== "object" || Array.isArray(o)) return d;
    const f = o.frame && typeof o.frame === "object" ? o.frame : {}, sm = o.sample && typeof o.sample === "object" ? o.sample : {}, wp = o.worldParams && typeof o.worldParams === "object" ? o.worldParams : {};
    const vars = C.VARIABLES.textbook.filter((v) => v.pop === "all").map((v) => v.id);
    const ests = Object.keys(C.ESTIMANDS).filter((k) => k !== "rule");
    const s = d;
    s.world = "textbook";                                // the watershed world is held for a later day (D59)
    s.worldSeed = seedOf(o.worldSeed, d.worldSeed);
    s.var = pick(o.var, vars, d.var); s.var2 = pick(o.var2, vars, d.var2);
    s.estimand = pick(o.estimand, ests, d.estimand);
    s.method = pick(o.method, ["cell", "zone"], d.method);
    s.paint = pick(o.paint, ["cells", "census", "sample"], d.paint);
    s.frame.kind = pick(f.kind, ["grid", "hex", "vor", "svor"], d.frame.kind);
    s.frame.size = SIZES.includes(f.size) ? f.size : d.frame.size;
    const sz = s.frame.size;
    s.frame.ox = num(f.ox, 0, sz, 0) % sz; s.frame.oy = num(f.oy, 0, sz, 0) % sz;
    s.frame.vseed = seedOf(f.vseed, d.frame.vseed);
    s.frame.basinKm2 = d.frame.basinKm2;
    s.sample.design = pick(sm.design, ["census", "random", "systematic", "stratified"], d.sample.design);
    if (s.frame.kind === "svor" && (s.sample.design === "census" || s.sample.design === "stratified")) s.sample.design = "random";
    s.sample.n = Math.round(num(sm.n, 20, 600, d.sample.n));
    s.sample.seed = seedOf(sm.seed, d.sample.seed);
    s.sample.beta = num(sm.beta, 0, 3, d.sample.beta);
    for (const k in TB_RANGE) if (k in wp) s.worldParams[k] = num(wp[k], TB_RANGE[k][0], TB_RANGE[k][1], C.TEXTBOOK_DEFAULTS[k]);
    if ("nu" in wp) s.worldParams.nu = pick(+wp.nu, [0.5, 1.5, 2.5], C.TEXTBOOK_DEFAULTS.nu);
    if ("marginal" in wp) s.worldParams.marginal = pick(wp.marginal, ["normal", "lognormal"], C.TEXTBOOK_DEFAULTS.marginal);
    s.thr = num(o.thr, -1e9, 1e9, d.thr);
    return s;
  }
  function loadState(o) {
    let ok = true;
    try { S = sanitize(o); buildWorld(); const r = rangeOf(S.var); S.thr = Math.min(r.max, Math.max(r.min, S.thr)); }
    catch (e) { ok = false; S = clone(DEFAULT); buildWorld(); }
    syncControls(); update(true);
    return ok;
  }
  $("s3-copy").addEventListener("click", async () => {
    const txt = JSON.stringify(S, null, 1);
    $("s3-json").value = txt;                            // always fill the box
    try { await navigator.clipboard.writeText(txt); $("s3-json-note").textContent = "Copied, and shown in the box. Paste it back (or share the page address) to replay exactly."; }
    catch (e) { $("s3-json-note").textContent = "Copy it from the box."; }
  });
  $("s3-load").addEventListener("click", () => {
    try { loadState(JSON.parse($("s3-json").value)); $("s3-json-note").textContent = "Loaded."; }
    catch (e) { $("s3-json-note").textContent = "That is not valid settings JSON: " + e.message; }
  });
  // the try-it list comes after this script in the page, so listen on the document
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-try]"); if (!b) return;
    let o = null; try { o = JSON.parse(b.dataset.try); } catch (err) { o = null; }
    loadState(o); $("s3-tools").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });

  // ---------- start ----------
  window.addEventListener("resize", () => { sizeMap(); if (out) drawMap(); });
  sizeMap();
  let start = null;
  try { if (location.hash.length > 1) start = JSON.parse(decodeURIComponent(location.hash.slice(1))); } catch (e) { start = null; }
  if (start) loadState(start); else { buildWorld(); syncControls(); update(true); }
})();
