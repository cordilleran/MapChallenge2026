// Corpus geography app: canvas map, linked matrix and topic table (design decisions D124 to D137).
import { load, view, scopeCounts, topics, termCounts, ee, greatCircle, cluster, bundle, SCOPES, SETTINGS, NO_ORIGIN } from "./core.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (x) => (x >= 10 ? Math.round(x).toLocaleString() : x.toFixed(1));
const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "–");
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const SET_LABEL = { rural: "Rural", mixed: "Mixed", urban: "Urban", unclear: "Unclear", not_applicable: "Not applicable" };
const SCOPE_LABEL = { site: "Site", "multi-site": "Multi-site", regional: "Regional", global: "Global", "local-implicit": "Local, unnamed", "non-spatial": "Non-spatial" };
const KIND_LABEL = { area: "area", feature: "natural feature", settlement: "settlement" };
const CLEAR = ["urban", "mixed", "rural"];
const SET_VAR = { urban: "--urban", mixed: "--mixed", rural: "--rural", unclear: "--unclear", not_applicable: "--na" };
const KIND_VAR = { area: "--area", feature: "--feature", settlement: "--settle" };
const XW = ee(180, 0)[0];
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- state (mirrored in the URL hash) ----------
const S = { c: "day09", scopes: new Set(SCOPES), dir: "studies", origin: "all", body: true, col: "setting", level: "subfield", regions: "wb", sel: null, selLabel: "" };
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("c")) S.c = h.get("c").replace(/[^a-z0-9_]/gi, "");
  if (h.get("s")) S.scopes = new Set(h.get("s").split(",").filter((s) => SCOPES.includes(s)));
  if (!S.scopes.size) S.scopes = new Set(SCOPES);
  if (["studies", "written"].includes(h.get("dir"))) S.dir = h.get("dir");
  if (["all", "corr"].includes(h.get("o"))) S.origin = h.get("o");
  if (["setting", "kind"].includes(h.get("col"))) S.col = h.get("col");
  if (["field", "subfield", "topic"].includes(h.get("t"))) S.level = h.get("t");
  if (["m49", "wb"].includes(h.get("r"))) S.regions = h.get("r");
  if (h.get("b") === "0") S.body = false;
  S.selHash = h.get("sel") || "";
  const at = (h.get("at") || "").split(",").map(Number);
  if (at.length === 3 && at.every(Number.isFinite)) S.at = at;
}
function writeHash() {
  const h = new URLSearchParams({ c: S.c, s: [...S.scopes].join(","), dir: S.dir, o: S.origin, b: S.body ? "1" : "0", col: S.col, t: S.level, r: S.regions });
  // table selections are shareable; map clicks are not (they depend on zoom)
  if (S.sel && S.sel.kind === "topic") h.set("sel", `${S.sel.level}:${M.vocab[[...S.sel.ids][0]]}`);
  else if (S.sel && S.sel.kind === "origin" && S.sel.region) h.set("sel", "region:" + S.sel.region);
  history.replaceState(null, "", "#" + h.toString());
}

// ---------- data ----------
readHash();
const [world, corpus, borders] = await Promise.all([
  fetch("data/world50.json").then((r) => r.json()),
  fetch(`data/${S.c}.json`).then((r) => r.json()),
  fetch("data/borders.json").then((r) => r.json()).catch(() => ({ country: [], lakes: [] })),
]);
const M = load(corpus, world);
// the owner's local build: cite keys and titles from a local-only file (D128); absent on the public site
// only asked for on localhost or a Tailscale address (the 100.64/10 shared range), never on the public site, even if the file were there
const PRIVATE_HOST = (() => {
  const h = location.hostname, o = h.split(".").map(Number);
  return h === "localhost" || h === "127.0.0.1" || (o.length === 4 && o[0] === 100 && o[1] >= 64 && o[1] <= 127);
})();
const PRIV = PRIVATE_HOST ? await fetch(`data/${S.c}_private.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null) : null;
$("sim-badge").hidden = !/SIMULATED/.test(M.note);
$("note").textContent = M.note;
$("n-papers").textContent = M.papers.length.toLocaleString();
const COUNTRIES = world.rows.map(([iso, name, region, sub, lx, ly, rings]) => {
  const path = new Path2D();
  let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
  for (const r of rings) r.forEach(([lo, la], i) => {
    const [x, y] = ee(lo, la);
    i ? path.lineTo(x, y) : path.moveTo(x, y);
    a = Math.min(a, x); b = Math.min(b, y); c = Math.max(c, x); d = Math.max(d, y);
  });
  return { iso, name, path, bbox: [a, b, c, d] };
});
// land borders and lakes (D139): lines only where two units share a border on land; the coast is the land fill's own hairline
function linePath(lines, path = new Path2D(), close = false) {
  for (const l of lines) { l.forEach(([lo, la], i) => { const [x, y] = ee(lo, la); i ? path.lineTo(x, y) : path.moveTo(x, y); }); if (close) path.closePath(); }
  return path;
}
const LAND = new Path2D(); for (const c of COUNTRIES) LAND.addPath(c.path);
const BORDER_LINES = linePath(borders.country), LAKES = linePath(borders.lakes, new Path2D(), true);
const PLACES_BY_ISO = {}, PLACES_BY_CODE = {};
M.places.forEach((p, i) => { (PLACES_BY_ISO[p.iso] ||= []).push(i); (PLACES_BY_CODE[p.code] ||= []).push(i); });
// provinces and states, fetched per country once the map is zoomed in (spec R2)
const ADM1 = new Map(), ADM1_SET = new Set(M.admin1), ADM1_LINES = new Map();
function admin1Lines(iso) {
  if (!ADM1_SET.has(iso) || ADM1_LINES.has(iso)) return ADM1_LINES.get(iso);
  ADM1_LINES.set(iso, null);
  fetch(`data/admin1/${iso}_lines.json`).then((r) => r.json()).then((lines) => { ADM1_LINES.set(iso, linePath(lines)); draw(); }).catch(() => {});
  return null;
}
function admin1For(iso) {
  if (!ADM1_SET.has(iso) || ADM1.has(iso)) return ADM1.get(iso);
  ADM1.set(iso, null);
  fetch(`data/admin1/${iso}.json`).then((r) => r.json()).then((feats) => {
    ADM1.set(iso, feats.map(([gn, name, rings]) => {
      const path = new Path2D();
      for (const r of rings) r.forEach(([lo, la], i) => { const [x, y] = ee(lo, la); i ? path.lineTo(x, y) : path.moveTo(x, y); });
      return { code: "a1:" + gn, name, path, iso };
    }));
    draw();
  }).catch(() => {});
  return null;
}
const PROV_ZOOM = 3;

// ---------- canvas and view transform ----------
const cv = $("map"), ctx = cv.getContext("2d");
let W = 0, H = 0, DPR = 1, k0 = 1, k = 1, vx = 0, vy = 0;
function resize() {
  DPR = window.devicePixelRatio || 1;
  const r = cv.getBoundingClientRect();
  W = r.width; H = r.height;
  cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
  const atWorld = Math.abs(k - k0) < 1e-9 || k === 1;   // stay at the world view when the box resizes
  k0 = Math.min(W / (2 * XW * 1.02), H / (2 * 1.32 * 1.05));
  if (atWorld || k < k0) k = k0;
  if (S.at && W > 0) { [vx, vy] = ee(S.at[0], S.at[1]); k = k0 * S.at[2]; S.at = null; }
  const r0 = R_MAX; R_MAX = Math.max(10, Math.min(24, W / 40));   // smaller symbols on a small map
  if (r0 !== R_MAX && V) legend();
  draw();
}
const toScreen = (x, y) => [W / 2 + (x - vx) * k, H / 2 - (y - vy) * k];
const toWorld = (sx, sy) => [vx + (sx - W / 2) / k, vy - (sy - H / 2) / k];
function setWorldTransform() { ctx.setTransform(DPR * k, 0, 0, -DPR * k, DPR * (W / 2 - vx * k), DPR * (H / 2 + vy * k)); }
let anim = 0;
function zoomAt(f, sx = W / 2, sy = H / 2) {
  cancelAnimationFrame(anim);
  const [wx, wy] = toWorld(sx, sy);
  k = Math.max(k0, Math.min(k0 * 60, k * f));
  vx = wx - (sx - W / 2) / k; vy = wy + (sy - H / 2) / k;
  draw();
}
// glide to a centre and zoom (instant when the reader asks for reduced motion)
function flyTo(tx, ty, tk) {
  cancelAnimationFrame(anim);
  tk = Math.max(k0, Math.min(k0 * 40, tk));
  if (REDUCED) { vx = tx; vy = ty; k = tk; draw(); return; }
  const [x0, y0, ka] = [vx, vy, k], t0 = performance.now(), T = 450;
  const step = (now) => {
    const f = Math.min(1, (now - t0) / T), e = f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2;
    vx = x0 + (tx - x0) * e; vy = y0 + (ty - y0) * e; k = ka * Math.pow(tk / ka, e);
    render();
    if (f < 1) anim = requestAnimationFrame(step);
  };
  anim = requestAnimationFrame(step);
}
// fit the view to a set of projected points, with a margin; a lone point gets a regional zoom
function fitTo(pts) {
  if (!pts.length) return;
  let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
  for (const [x, y] of pts) { a = Math.min(a, x); b = Math.min(b, y); c = Math.max(c, x); d = Math.max(d, y); }
  const pad = 48, kk = Math.min((W - 2 * pad) / Math.max(c - a, 1e-3), (H - 2 * pad) / Math.max(d - b, 1e-3), k0 * 12);
  flyTo((a + c) / 2, (b + d) / 2, kk);
}
const goTo = (lon, lat, z) => { const [x, y] = ee(lon, lat); flyTo(x, y, k0 * z); };

// ---------- colour and size ----------
// a mark's colour: by the settings its papers state (most common clear one, grey when most are unclear), or by place kind
function settingOf(r) {
  if (!r) return "unclear";
  const clear = CLEAR.reduce((a, s) => a + r[s], 0), all = SETTINGS.reduce((a, s) => a + r[s], 0);
  if (!all) return "unclear";
  if (clear / all < 0.5) return r.not_applicable > r.unclear ? "not_applicable" : "unclear";
  return CLEAR.reduce((best, s) => (r[s] > r[best] ? s : best), "rural");
}
const colourOf = (C, set, kind) => (S.col === "setting" ? C[set] : C[kind]);
// one size scale for every circle on the map: area is proportional to papers (D126), reference set per filter
let WREF = 1, R_MAX = 24, LOCAL = 0, LEGEND_LOCAL = -1;
const radius = (w) => Math.max(2.5, R_MAX * Math.sqrt(w / WREF));

// ---------- drawing ----------
const inView = (c, x0, y0, x1, y1) => !(c.bbox[2] < x0 || c.bbox[0] > x1 || c.bbox[3] < y0 || c.bbox[1] > y1);
let V = null, hits = [], raf = 0;
function draw() { cancelAnimationFrame(raf); raf = requestAnimationFrame(render); }
function compute() {
  V = view(M, S);
  const w0 = cluster([...V.origin.entries()].map(([pl, w]) => ({ id: pl, x: M.places[pl].x, y: M.places[pl].y, w })), 5);
  WREF = Math.max(1, ...w0.map((c) => c.w), ...[...V.study.entries()].filter(([pl]) => !M.places[pl].big).map(([, w]) => w));
}
const zoomLevel = () => Math.max(3, Math.min(14, Math.round(Math.log2(k / k0)) + 5));

function render() {
  if (!V) compute();
  const C = { land: css("--land"), hi: css("--land-hi"), border: css("--border"), coast: css("--coast"), prov: css("--prov"), ocean: css("--ocean"),
    area: css("--area"), feature: css("--feature"), settlement: css("--settle"), origin: css("--origin"), ring: css("--ring"),
    urban: css("--urban"), mixed: css("--mixed"), rural: css("--rural"), unclear: css("--unclear-mark"), not_applicable: css("--na") };
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = C.ocean; ctx.fillRect(0, 0, cv.width, cv.height);
  // land: a faint tint marks countries studied at all under the filter
  const studied = new Set();
  for (const [pl] of V.study) studied.add(M.places[pl].iso);
  const [x0, y1] = toWorld(0, 0), [x1, y0] = toWorld(W, H);
  setWorldTransform();
  for (const c of COUNTRIES) { if (!inView(c, x0, y0, x1, y1)) continue; ctx.fillStyle = studied.has(c.iso) ? C.hi : C.land; ctx.fill(c.path); }
  // lakes cut out of the land; one hairline marks coasts and shores
  ctx.fillStyle = C.ocean; ctx.fill(LAKES);
  ctx.lineWidth = 0.5 / k; ctx.strokeStyle = C.coast;
  for (const c of COUNTRIES) if (inView(c, x0, y0, x1, y1)) ctx.stroke(c.path);
  ctx.stroke(LAKES);
  // borders only where two units meet on land, clipped to the land so no end runs into the sea:
  // provinces dashed first, countries solid over them (D139)
  ctx.save(); ctx.clip(LAND);
  if (k / k0 >= PROV_ZOOM) {
    ctx.lineWidth = 0.9 / k; ctx.setLineDash([5 / k, 3 / k]); ctx.strokeStyle = C.prov;
    for (const c of COUNTRIES) {
      if (!ADM1_SET.has(c.iso) || !inView(c, x0, y0, x1, y1)) continue;
      admin1For(c.iso); // province shapes stay loaded for hover and selection
      const lines = admin1Lines(c.iso);
      if (lines) ctx.stroke(lines);
    }
    ctx.setLineDash([]);
  }
  ctx.lineWidth = (k / k0 >= PROV_ZOOM ? 1.3 : 0.8) / k; ctx.strokeStyle = C.border;
  ctx.stroke(BORDER_LINES);
  ctx.restore();
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  hits = [];

  // origins, clustered by zoom in nested cells; arcs bundle into the same cells
  const level = zoomLevel();
  const pts = [...V.origin.entries()].map(([pl, w]) => ({ id: pl, x: M.places[pl].x, y: M.places[pl].y, w }));
  const cl = cluster(pts, level).sort((a, b) => b.w - a.w);
  const size = (2 * XW) / 2 ** level, cellOf = (x, y) => Math.floor(x / size) + ":" + Math.floor(y / size);
  const anchor = new Map(cl.map((c) => [cellOf(M.places[c.ids[0]].x, M.places[c.ids[0]].y), c]));

  // places studied: circles for areas, triangles for natural features, diamonds for settlements; translucent so overlaps show
  const studies = [...V.study.entries()].sort((a, b) => b[1] - a[1]);
  for (const [pl, w] of studies) {
    const p = M.places[pl];
    if (p.big) continue;                       // continents and oceans are counted, not drawn
    const [sx, sy] = toScreen(p.x, p.y);
    if (sx < -40 || sy < -40 || sx > W + 40 || sy > H + 40) continue;
    const r = radius(w), col = colourOf(C, settingOf(V.studySet.get(pl)), p.kind);
    shape(p.kind, sx, sy, r);
    ctx.globalAlpha = 0.42; ctx.fillStyle = col; ctx.fill();
    ctx.globalAlpha = 1; ctx.lineWidth = 1.4; ctx.strokeStyle = col; ctx.stroke();
    hits.push({ sx, sy, r: r + 4, kind: "place", ids: [pl], w });
  }
  // arcs: every bundle of a selection; otherwise the strongest, more of them as you zoom in
  // continents and oceans have no meaningful point, so their links are counted but not drawn
  const drawable = new Map([...V.arcSet].filter(([key]) => !M.places[+key.split(">")[1]].big));
  const bundles = bundle(M, drawable, level).sort((a, b) => b.w - a.w);
  const cap = S.sel ? bundles.length : Math.round(Math.min(400, 40 * Math.sqrt(k / k0)));
  // a bundle whose two ends share a cell stays local at this zoom: counted in the legend, not drawn
  const allW = bundles.reduce((a, g) => a + g.w, 0);
  LOCAL = allW ? bundles.filter((g) => g.self).reduce((a, g) => a + g.w, 0) / allW : 0;
  const shown = bundles.filter((g) => !g.self).slice(0, cap);
  const amax = shown.length ? shown[0].w : 1;
  ctx.lineCap = "round";
  for (const g of shown.slice().reverse()) {
    const o0 = M.places[g.o[0]], a = anchor.get(cellOf(o0.x, o0.y));
    const from = a ? [M.places[a.ids[0]].lon, M.places[a.ids[0]].lat] : g.from;
    const fromXY = a ? [a.x, a.y] : null;
    const { segs, om } = greatCircle(from, g.to);
    const kind = Object.entries(g.kind).sort((p, q) => q[1] - p[1])[0][0];
    ctx.strokeStyle = colourOf(C, settingOf(g.set), kind);
    ctx.globalAlpha = (S.sel ? 0.8 : 0.55) * (1 - 0.55 * om / Math.PI);   // long arcs fade
    ctx.lineWidth = 0.8 + 6 * Math.sqrt(g.w / amax);
    for (const seg of segs) {
      ctx.beginPath();
      seg.forEach(([x, y], i) => {
        // the first point sits on the cluster's dot rather than its first member
        const [sx, sy] = i === 0 && fromXY && seg === segs[0] ? toScreen(...fromXY) : toScreen(x, y);
        i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy);
      });
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;

  for (const c of cl) {
    const [sx, sy] = toScreen(c.x, c.y);
    if (sx < -30 || sy < -30 || sx > W + 30 || sy > H + 30) continue;
    const r = radius(c.w);
    ctx.beginPath(); ctx.arc(sx, sy, r, 0, 2 * Math.PI);
    ctx.globalAlpha = 0.3; ctx.fillStyle = C.origin; ctx.fill(); ctx.globalAlpha = 1;
    ctx.lineWidth = 1.6; ctx.strokeStyle = C.origin; ctx.stroke();
    ctx.beginPath(); ctx.arc(sx, sy, 1.6, 0, 2 * Math.PI); ctx.fillStyle = C.origin; ctx.fill();
    hits.push({ sx, sy, r: r + 4, kind: "origin", ids: c.ids, w: c.w });
  }
  linesNote();
}
function linesNote() {
  const el = $("lg-lines");
  if (!el || Math.round(LOCAL * 100) === LEGEND_LOCAL) return;
  LEGEND_LOCAL = Math.round(LOCAL * 100);
  el.textContent = `Lines: ${S.sel ? "every link of the selection" : "the strongest links, more as you zoom in"}; links with both ends in one cluster merge and are not drawn (${LEGEND_LOCAL}% of the weight at this zoom)`;
}
function shape(kind, x, y, r) {
  ctx.beginPath();
  if (kind === "feature") { const s = r * 1.25; ctx.moveTo(x, y - s); ctx.lineTo(x + s * 0.94, y + s * 0.6); ctx.lineTo(x - s * 0.94, y + s * 0.6); ctx.closePath(); }
  else if (kind === "settlement") { const s = r * 1.2; ctx.moveTo(x, y - s); ctx.lineTo(x + s, y); ctx.lineTo(x, y + s); ctx.lineTo(x - s, y); ctx.closePath(); }
  else ctx.arc(x, y, r, 0, 2 * Math.PI);
}

// ---------- picking, tooltip and selection ----------
function pick(sx, sy) {
  let best = null, bd = Infinity;
  for (const h of hits) { const d = Math.hypot(h.sx - sx, h.sy - sy); if (d < h.r && d < bd) { bd = d; best = h; } }
  if (best) return best;
  setWorldTransform();                      // isPointInPath takes device pixels; the path is transformed
  const c = COUNTRIES.find((c) => ctx.isPointInPath(c.path, sx * DPR, sy * DPR));
  let prov = null;
  if (c && k / k0 >= PROV_ZOOM && ADM1.get(c.iso)) prov = ADM1.get(c.iso).find((f) => ctx.isPointInPath(f.path, sx * DPR, sy * DPR));
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  if (prov) return { kind: "province", code: prov.code, iso: c.iso, name: `${prov.name}, ${c.name}` };
  return c ? { kind: "country", iso: c.iso, name: c.name } : null;
}
function composition(code) {
  const a = M.areas[code];
  if (!a || !a.composition) return "";
  const [, , lr, pu, pt, pr] = a.composition, f = (x) => Math.round(100 * x) + "%";
  return `<span class="m">Its people: ${pu == null ? "–" : f(pu) + " in urban centres, " + f(pt) + " in towns, " + f(pr) + " rural"} (land ${f(lr)} rural)</span>`;
}
function settingLine(r) {
  if (!r) return "";
  const parts = SETTINGS.filter((s) => r[s] >= 0.05).map((s) => `${fmt(r[s])} ${SET_LABEL[s].toLowerCase()}`);
  return parts.length ? `<span class="m">Setting stated: ${parts.join(", ")}</span>` : "";
}
function describe(h) {
  if (h.kind === "country" || h.kind === "province") return `<b>${esc(h.name)}</b><span class="m">Click: papers ${S.dir === "studies" ? "that study it" : "written in it"}</span>${composition(h.kind === "province" ? h.code : h.iso)}`;
  const names = h.ids.slice(0, 3).map((i) => M.places[i].name);
  const more = h.ids.length > 3 ? ` and ${h.ids.length - 3} more` : "";
  const p0 = M.places[h.ids[0]];
  const head = h.kind === "origin" ? `Written from ${h.ids.length > 1 ? h.ids.length + " institutions" : "here"}` : `Studied: ${KIND_LABEL[p0.kind]}${p0.kind === "settlement" && p0.ur ? ", " + p0.ur + " 1 km cell" : ""}`;
  const ids = view(M, { ...S, sel: { kind: h.kind === "origin" ? "origin" : "place", ids: new Set(h.ids) } }).ids;
  const tp = ids.length >= 3 || PRIV ? topics(M, ids).map(([t, n]) => `${esc(t)} (${n})`).join(", ") : "";
  return `<b>${esc(names.join("; "))}${more}</b><span class="m">${head} · ${fmt(h.w)} papers (weighted)</span>${h.kind === "place" ? settingLine(V.studySet.get(h.ids[0])) + composition(p0.code) : ""}${tp ? `<span class="tp">${tp}</span>` : ""}`;
}
function select(h) {
  if (!h) { S.sel = null; S.selLabel = ""; }
  else if (h.kind === "country" || h.kind === "province") {
    const codes = (h.kind === "province" ? PLACES_BY_CODE[h.code] : PLACES_BY_ISO[h.iso]) || [];
    const ids = codes.filter((i) => (S.dir === "studies" ? M.places[i].kind !== "institution" : M.places[i].kind === "institution"));
    S.sel = ids.length ? { kind: S.dir === "studies" ? "place" : "origin", ids: new Set(ids) } : { kind: "place", ids: new Set() };
    S.selLabel = `${S.dir === "studies" ? "Papers that study" : "Papers written in"} ${h.name}`;
  } else {
    S.sel = { kind: h.kind === "origin" ? "origin" : "place", ids: new Set(h.ids) };
    const nm = h.ids.length > 1 ? `${M.places[h.ids[0]].name} and ${h.ids.length - 1} nearby` : M.places[h.ids[0]].name;
    S.selLabel = `${h.kind === "origin" ? "Papers written at" : "Papers that study"} ${nm}`;
  }
  update();
}
// after a selection from a table, frame what it touches: the institutions for a region, the places studied for a topic
function frameSelection() {
  const pts = [];
  if (S.sel.kind === "origin") for (const [pl] of V.origin) pts.push([M.places[pl].x, M.places[pl].y]);
  else for (const [pl] of V.study) if (!M.places[pl].big) pts.push([M.places[pl].x, M.places[pl].y]);
  if (!pts.length) for (const [pl] of V.origin) pts.push([M.places[pl].x, M.places[pl].y]);
  if (pts.length) fitTo(pts);
}

let drag = null;
const pointers = new Map();
cv.addEventListener("pointerdown", (e) => { cancelAnimationFrame(anim); cv.setPointerCapture(e.pointerId); pointers.set(e.pointerId, [e.offsetX, e.offsetY]); drag = { x: e.offsetX, y: e.offsetY, vx, vy, moved: false }; });
let lastTip = "";
cv.addEventListener("pointermove", (e) => {
  if (pointers.has(e.pointerId)) {
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, [e.offsetX, e.offsetY]);
    if (pointers.size === 2) {               // pinch
      const [a, b] = [...pointers.values()];
      const other = [...pointers.entries()].find(([id]) => id !== e.pointerId)[1];
      const d0 = Math.hypot(prev[0] - other[0], prev[1] - other[1]), d1 = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (d0 > 0) zoomAt(d1 / d0, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
      drag.moved = true; return;
    }
    if (drag) {
      const dx = e.offsetX - drag.x, dy = e.offsetY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      vx = drag.vx - dx / k; vy = drag.vy + dy / k; draw();
    }
    return;
  }
  const h = pick(e.offsetX, e.offsetY), tip = $("tip");
  if (!h) { tip.hidden = true; lastTip = ""; return; }
  // describe() filters every paper, so only rebuild the tip when the hovered mark changes
  const key = [h.kind, h.ids ? h.ids.join(",") : h.id, h.code, h.iso, V.n, S.col].join("|");
  if (key !== lastTip) { tip.innerHTML = describe(h); lastTip = key; }
  tip.hidden = false;
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = (e.offsetX + 14 + tw > W ? Math.max(4, e.offsetX - tw - 14) : e.offsetX + 14) + "px";
  tip.style.top = (e.offsetY + 14 + th > H ? Math.max(4, e.offsetY - th - 14) : e.offsetY + 14) + "px";
});
cv.addEventListener("pointerup", (e) => {
  pointers.delete(e.pointerId);
  if (drag && !drag.moved && pointers.size === 0) select(pick(e.offsetX, e.offsetY));
  if (pointers.size === 0) drag = null;
});
cv.addEventListener("pointerleave", () => { $("tip").hidden = true; });
cv.addEventListener("wheel", (e) => { e.preventDefault(); zoomAt(Math.pow(1.2, -e.deltaY / 100), e.offsetX, e.offsetY); }, { passive: false });
cv.addEventListener("keydown", (e) => {
  const step = 60 / k;
  const keys = { ArrowLeft: () => { vx -= step; }, ArrowRight: () => { vx += step; }, ArrowUp: () => { vy += step; }, ArrowDown: () => { vy -= step; }, "+": () => zoomAt(1.4), "=": () => zoomAt(1.4), "-": () => zoomAt(1 / 1.4), Escape: () => select(null) };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); draw(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.sel && e.target === document.body) select(null); });
$("zin").onclick = () => zoomAt(1.5);
$("zout").onclick = () => zoomAt(1 / 1.5);
$("zworld").onclick = () => flyTo(0, 0, k0);
$("zbc").onclick = () => goTo(-125, 54, 7);
$("zsel").onclick = () => S.sel && frameSelection();

// ---------- controls ----------
const SC = scopeCounts(M), scMax = Math.max(...Object.values(SC));
$("scopes").innerHTML = SCOPES.map((s) => `<button type="button" class="scope" data-k="${s}" aria-pressed="true">${SCOPE_LABEL[s]}<span class="n">${SC[s].toLocaleString()}</span><span class="bar" style="width:${Math.max(2, 56 * SC[s] / scMax)}px"></span></button>`).join("");
$("scopes").addEventListener("click", (e) => {
  const b = e.target.closest(".scope"); if (!b) return;
  const s = b.dataset.k;
  if (e.shiftKey || e.altKey) S.scopes = new Set([s]);           // shift-click: only this one
  else if (S.scopes.has(s) && S.scopes.size > 1) S.scopes.delete(s); else S.scopes.add(s);
  update();
});
$("scope-all").onclick = () => { S.scopes = new Set(SCOPES); update(); };
for (const [id, key] of [["dir", "dir"], ["org", "origin"], ["col", "col"], ["level", "level"], ["body", "body"], ["regs", "regions"]]) {
  $(id).addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S[key] = key === "body" ? b.dataset.k === "1" : b.dataset.k;
    if (key === "dir" || (key === "regions" && S.sel && S.sel.region) || (key === "level" && S.sel && S.sel.kind === "topic")) S.sel = null, S.selLabel = "";
    update();
  });
}

// ---------- legend ----------
function legend() {
  LEGEND_LOCAL = -1;                         // the rebuilt key has an empty lines note; let linesNote() fill it again
  const sw = (shape, col, r = 5) => {
    const d = shape === "tri" ? `<path d="M0,-6 L5.6,3.6 L-5.6,3.6Z"/>` : shape === "dia" ? `<path d="M0,-6 L6,0 L0,6 L-6,0Z"/>` : `<circle r="${r}"/>`;
    return `<svg width="16" height="16" viewBox="-8 -8 16 16" aria-hidden="true"><g fill="${col}" fill-opacity="0.42" stroke="${col}" stroke-width="1.4">${d}</g></svg>`;
  };
  const ink = "var(--muted)";
  const shapes = [[sw("dot", "var(--origin)"), "Institutions (merged by zoom)"], [sw("dot", ink), "Area studied"], [sw("tri", ink), "Natural feature"], [sw("dia", ink), "Settlement"]];
  const cols = S.col === "setting"
    ? [...CLEAR.map((s) => [`<i class="chip" style="background:var(${SET_VAR[s]})"></i>`, SET_LABEL[s]]), [`<i class="chip" style="background:var(--unclear-mark)"></i>`, "Mostly unclear"]]
    : Object.entries(KIND_VAR).map(([kd, v]) => [`<i class="chip" style="background:var(${v})"></i>`, KIND_LABEL[kd][0].toUpperCase() + KIND_LABEL[kd].slice(1)]);
  // size key: three round values under the reference
  const nice = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].filter((x) => x <= WREF);
  const keys = [nice[0], nice[Math.floor(nice.length / 2)], nice[nice.length - 1]].filter((x, i, a) => x && a.indexOf(x) === i);
  const rr = keys.map(radius), hmax = 2 * Math.max(...rr) + 2;
  const sizes = `<svg width="${rr.reduce((a, r) => a + 2 * r + 30, 0)}" height="${hmax}" aria-hidden="true">` + keys.map((x, i) => {
    const cx = rr.slice(0, i).reduce((a, r) => a + 2 * r + 30, 0) + rr[i] + 1;
    return `<circle cx="${cx}" cy="${hmax - rr[i] - 1}" r="${rr[i]}" fill="none" stroke="var(--muted)"/><text x="${cx + rr[i] + 4}" y="${hmax - 2}" font-size="11" fill="var(--muted)">${x}</text>`;
  }).join("") + "</svg>";
  $("legend").innerHTML =
    `<div class="lg"><span class="lh">Shape</span>${shapes.map(([s, t]) => `<span>${s}${t}</span>`).join("")}</div>` +
    `<div class="lg"><span class="lh">Colour: ${S.col === "setting" ? "setting its papers state" : "kind of place studied"}</span>${cols.map(([s, t]) => `<span>${s}${t}</span>`).join("")}</div>` +
    `<div class="lg"><span class="lh">Size: papers</span>${sizes}<span class="m" id="lg-lines"></span></div>`;
}

// ---------- side panel ----------
function selDetail() {
  const lab = new Map();
  for (const i of V.ids) for (const l of M.papers[i].labels || []) if (l !== "none") lab.set(l, (lab.get(l) || 0) + 1);
  const top = [...lab.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([l, n]) => `${esc(l)} ${n}`).join(", ");
  let out = top ? `<div class="m">Setting words: ${top}</div>` : "";
  if (PRIV) {
    const items = V.ids.slice(0, 40).map((i) => PRIV[M.papers[i].id]).filter(Boolean)
      .map(([key, title]) => `<li><code>${esc(key)}</code> ${esc(title || "")}</li>`).join("");
    out += `<details class="papers"><summary>Papers (${V.ids.length}${V.ids.length > 40 ? ", first 40" : ""})</summary><ul>${items}</ul></details>`;
  }
  return out;
}
const miniBar = (r, n) => `<span class="mini" role="img" aria-label="${SETTINGS.filter((s) => r[s]).map((s) => `${SET_LABEL[s]} ${r[s]}`).join(", ")}">${SETTINGS.filter((s) => r[s]).map((s) => `<i style="flex:${r[s]};background:var(${s === "unclear" ? "--unclear-mark" : SET_VAR[s]})"></i>`).join("")}</span>`;
let showAllTopics = false;
function topicTable() {
  const tc = [...termCounts(M, V.keep, S.level).entries()].filter(([, r]) => PRIV || r.n >= 3).sort((a, b) => b[1].n - a[1].n);
  const selT = S.sel && S.sel.kind === "topic" ? S.sel.ids : null;
  const rows = showAllTopics ? tc : tc.slice(0, 12);
  const none = V.keep.filter((i) => M.papers[i].subfield == null).length;
  $("topics").innerHTML = `<thead><tr><th scope="col">${{ field: "Field", subfield: "Subfield", topic: "Topic" }[S.level]}</th><th scope="col">Papers</th><th scope="col">Setting</th></tr></thead><tbody>` +
    rows.map(([t, r]) => `<tr data-t="${t}" tabindex="0" aria-selected="${!!(selT && selT.has(t))}"><th scope="row" class="row" title="${esc(M.vocab[t])}">${esc(M.vocab[t])}</th><td>${r.n}</td><td>${miniBar(r)}</td></tr>`).join("") + "</tbody>";
  $("topics-more").hidden = tc.length <= 12;
  $("topics-more").textContent = showAllTopics ? "Show the top 12" : `Show all ${tc.length}`;
  $("topics-note").textContent = `OpenAlex primary topic, by its ${S.level}. ${none.toLocaleString()} papers in the filter have none here (no DOI, no OpenAlex match${PRIV ? "" : ", or a term shared by fewer than 3 papers, which this public page leaves out"}). Select a row to filter the map.`;
}
$("topics-more").onclick = () => { showAllTopics = !showAllTopics; topicTable(); };
function selectTopic(tr) {
  if (!tr) return;
  const t = Number(tr.dataset.t);
  if (S.sel && S.sel.kind === "topic" && S.sel.ids.has(t)) { select(null); return; }
  S.sel = { kind: "topic", level: S.level, ids: new Set([t]) }; S.selLabel = `Papers on ${M.vocab[t]}`;
  update(); frameSelection();
}
$("topics").addEventListener("click", (e) => selectTopic(e.target.closest("tr[data-t]")));
$("topics").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectTopic(e.target.closest("tr[data-t]")); } });

function update() {
  compute();
  writeHash();
  document.querySelectorAll(".scope").forEach((b) => b.setAttribute("aria-pressed", S.scopes.has(b.dataset.k)));
  for (const [id, val] of [["dir", S.dir], ["org", S.origin], ["col", S.col], ["level", S.level], ["body", S.body ? "1" : "0"], ["regs", S.regions]])
    document.querySelectorAll(`#${id} button`).forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === val));
  $("scope-all").hidden = S.scopes.size === SCOPES.length;
  $("zsel").hidden = !S.sel;
  $("sel").innerHTML = S.sel ? `<b>${esc(S.selLabel)}</b>: ${V.n.toLocaleString()} of ${V.nScope.toLocaleString()} papers in the filter.${selDetail()}<div class="selbtns"><button type="button" id="clear">Clear selection</button></div>` : "";
  if (S.sel) $("clear").onclick = () => select(null);
  const kw = V.kindW, tot = kw.area + kw.feature + kw.settlement;
  $("readouts").innerHTML = [
    ["Papers", V.n.toLocaleString()], ["With a located origin", pct(V.located, V.n)], ["With a place of study", pct(V.placed, V.n)],
    ["Study weight to areas", pct(kw.area, tot)], ["To natural features", pct(kw.feature, tot)], ["To settlements", pct(kw.settlement, tot)],
  ].map(([t, v]) => `<div><dt>${t}</dt><dd>${v}</dd></div>`).join("");
  // setting bar, in the same colours as the map
  const setTot = Object.fromEntries(SETTINGS.map((s) => [s, 0]));
  for (const i of V.ids) setTot[M.papers[i].setting]++;
  const col = (s) => `var(${s === "unclear" ? "--unclear-mark" : SET_VAR[s]})`;
  $("setbar").innerHTML = SETTINGS.filter((s) => setTot[s]).map((s) => `<div style="flex:${setTot[s]};background:${col(s)}" title="${SET_LABEL[s]}: ${setTot[s]}"></div>`).join("");
  $("setbar").setAttribute("aria-label", SETTINGS.map((s) => `${SET_LABEL[s]} ${setTot[s]}`).join(", "));
  $("setkey").innerHTML = SETTINGS.map((s) => `<span><i style="background:${col(s)}"></i>${SET_LABEL[s]} ${pct(setTot[s], V.n)}</span>`).join("");
  // matrix: origin region by setting, each column tinted in its own setting colour
  const rows = [...V.matrix.entries()].map(([reg, r]) => [reg, r, SETTINGS.reduce((a, s) => a + r[s], 0)]).sort((a, b) => (a[0] === NO_ORIGIN) - (b[0] === NO_ORIGIN) || b[2] - a[2]);
  const top = rows.filter((r) => r[0] !== NO_ORIGIN).slice(0, 9), rest = rows.filter((r) => r[0] !== NO_ORIGIN).slice(9), none = rows.find((r) => r[0] === NO_ORIGIN);
  if (rest.length) { const o = Object.fromEntries(SETTINGS.map((s) => [s, rest.reduce((a, r) => a + r[1][s], 0)])); top.push(["Other regions", o, rest.reduce((a, r) => a + r[2], 0)]); }
  if (none) top.push(none);
  const max = Math.max(1, ...top.flatMap(([, r]) => SETTINGS.map((s) => r[s])));
  const selReg = S.sel && S.sel.kind === "origin" && S.sel.region ? S.sel.region : null;
  $("matrix").innerHTML = `<thead><tr><th></th>${SETTINGS.map((s) => `<th scope="col" title="${SET_LABEL[s]}">${({ unclear: "Uncl.", not_applicable: "n/a" })[s] || SET_LABEL[s]}</th>`).join("")}<th scope="col">All</th></tr></thead><tbody>` +
    top.map(([reg, r, t]) => `<tr data-reg="${esc(reg)}" ${reg === NO_ORIGIN || reg === "Other regions" ? "" : 'tabindex="0"'} aria-selected="${reg === selReg}"><th class="row" scope="row" title="${esc(reg)}">${esc(reg)}</th>${SETTINGS.map((s) => `<td style="background:color-mix(in srgb, ${col(s)} ${Math.round(65 * Math.sqrt(r[s] / max))}%, transparent)">${r[s] >= 0.5 ? Math.round(r[s]) : ""}</td>`).join("")}<td>${Math.round(t)}</td></tr>`).join("") + "</tbody>";
  topicTable();
  legend(); LEGEND_LOCAL = -1;
  draw();
}
$("matrix").addEventListener("click", (e) => selectRow(e.target.closest("tr[data-reg]")));
$("matrix").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectRow(e.target.closest("tr[data-reg]")); } });
function selectRow(tr) {
  if (!tr) return;
  const reg = tr.dataset.reg;
  if (reg === NO_ORIGIN || reg === "Other regions") return;
  if (tr.getAttribute("aria-selected") === "true") { select(null); return; }
  const ids = M.places.map((p, i) => (p.kind === "institution" && p.regions[S.regions] === reg ? i : -1)).filter((i) => i >= 0);
  S.sel = { kind: "origin", ids: new Set(ids), region: reg }; S.selLabel = `Papers written in ${reg}`;
  update(); frameSelection();
}

new ResizeObserver(resize).observe(cv);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
// a selection carried in the link
if (S.selHash) {
  const [lv, ...rest] = S.selHash.split(":"), name = rest.join(":");
  if (lv === "region") {
    const ids = M.places.map((p, i) => (p.kind === "institution" && p.regions[S.regions] === name ? i : -1)).filter((i) => i >= 0);
    if (ids.length) { S.sel = { kind: "origin", ids: new Set(ids), region: name }; S.selLabel = `Papers written in ${name}`; }
  } else if (["field", "subfield", "topic"].includes(lv) && M.vocab.includes(name)) {
    S.level = lv; S.sel = { kind: "topic", level: lv, ids: new Set([M.vocab.indexOf(name)]) }; S.selLabel = `Papers on ${name}`;
  }
}
update();
resize();
if (S.sel && !location.hash.includes("at=")) requestAnimationFrame(() => frameSelection());      // the observer's first call can come late; size the canvas now as well
