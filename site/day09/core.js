// Corpus geography app: the pure part (no DOM), so Node can test it.
// Reads the data contract (corpus-geography/0.1) and answers one question per
// filter state: which papers are in, and how they spread over origins, places
// and the origin-region by setting matrix. Weights follow the spec's rule:
// a paper counts 1; its origin weights sum to 1 if located; its study weights
// sum to 1 if placed; an arc's weight is the product.

export const SCOPES = ["site", "multi-site", "regional", "global", "local-implicit", "non-spatial"];
export const SETTINGS = ["rural", "mixed", "urban", "unclear", "not_applicable"];
export const NO_ORIGIN = "No located origin";

const rows = (t) => t.rows.map((r) => Object.fromEntries(t.cols.map((c, i) => [c, r[i]])));

export function load(contract, world) {
  const papers = rows(contract.papers);
  const places = rows(contract.places);
  const W = world ? rows(world) : [];
  // two accepted region schemes: UN M49 subregions (Natural Earth SUBREGION) and the World Bank's seven regions
  const region = Object.fromEntries(W.map((w) => [w.iso, w.subregion || w.region]));
  const regionWB = Object.fromEntries(W.map((w) => [w.iso, w.region_wb || w.subregion || w.region]));
  const label = Object.fromEntries(W.map((w) => [w.iso, [w.lx, w.ly]]));
  const areas = contract.areas && contract.areas.cols.includes("iso") ? rows(contract.areas) : [];
  const AREA = Object.fromEntries(areas.map((a) => [a.code, a]));
  const byPaper = papers.map(() => ({ o: [], s: [] }));
  for (const [p, pl, w, corr] of contract.origins.rows) byPaper[p].o.push({ pl, w, corr });
  for (const [p, pl, w, src] of contract.studies.rows) byPaper[p].s.push({ pl, w, src });
  for (const pl of places) {
    const a = AREA[pl.code];
    pl.iso = a ? a.iso : pl.code;                       // provinces carry "a1:<GeoNames id>" as code
    pl.regions = { m49: region[pl.iso] || "Other", wb: regionWB[pl.iso] || "Other" };
    pl.region = pl.regions.m49;
    // countries and provinces sit at their label point; other areas (ranges, regions) keep their own point
    const whole = !pl.fcode || /^(PCL|TERR)/.test(pl.fcode) || pl.fcode === "ADM1";
    if (pl.kind === "area" && whole) [pl.lon, pl.lat] = (a && a.label) || label[pl.iso] || [pl.lon, pl.lat];
    [pl.x, pl.y] = ee(pl.lon, pl.lat);
  }
  return { papers, places, byPaper, areas: AREA, admin1: contract.admin1 || [], vocab: contract.vocab || [], note: contract.note || "" };
}

// state: { scopes: Set, origin: "all" | "corr", dir: "studies" | "written", body: bool, regions: "m49" | "wb",
//          sel: null | {kind: "origin" | "place", ids:Set} | {kind: "topic", level: "field" | "subfield" | "topic", ids:Set} }
// body = false drops places found only in the body text and re-weights the rest to sum to 1.
// a paper's term at one level of the OpenAlex hierarchy (vocab index), or null
export function termOf(p, level) {
  if (level === "topic") return p.subfield == null ? null : (p.topics || [])[0] ?? null;
  return p[level] ?? null;
}
export function studiesOf(M, i, body = true) {
  const s = M.byPaper[i].s;
  if (body !== false) return s;
  const keep = s.filter((x) => x.src !== "body"), t = keep.reduce((a, x) => a + x.w, 0);
  return keep.map((x) => ({ ...x, w: x.w / t }));
}
export function view(M, state) {
  const inScope = (p) => state.scopes.has(p.scope);
  const keep = [];
  for (let i = 0; i < M.papers.length; i++) if (inScope(M.papers[i])) keep.push(i);
  const originsOf = (i) => {
    const o = M.byPaper[i].o;
    if (state.origin !== "corr") return o;
    const c = o.find((x) => x.corr);
    return c ? [{ ...c, w: 1 }] : [];
  };
  // a selection narrows the papers: an origin selection keeps papers written there,
  // a place selection keeps papers that study it
  let sel = keep;
  if (state.sel) {
    const ids = state.sel.ids;
    sel = keep.filter((i) => state.sel.kind === "origin" ? originsOf(i).some((o) => ids.has(o.pl))
      : state.sel.kind === "topic" ? ids.has(termOf(M.papers[i], state.sel.level))
      : studiesOf(M, i, state.body).some((s) => ids.has(s.pl)));
  }
  const origin = new Map(), study = new Map(), arcs = new Map(), matrix = new Map();
  const studySet = new Map(), arcSet = new Map();   // the same weights split by the paper's setting
  const add = (m, key, set, w) => { const r = m.get(key) || Object.fromEntries(SETTINGS.map((s) => [s, 0])); r[set] += w; m.set(key, r); };
  let located = 0, placed = 0;
  const kindW = { area: 0, feature: 0, settlement: 0 };
  for (const i of sel) {
    const p = M.papers[i], os = originsOf(i), ss = studiesOf(M, i, state.body);
    if (os.length) located++;
    if (ss.length) placed++;
    // matrix: origin region rows by setting columns; unlocated papers get their own row
    const parts = os.length ? os.map((o) => [M.places[o.pl].regions[state.regions || "m49"], o.w]) : [[NO_ORIGIN, 1]];
    for (const [reg, w] of parts) {
      const row = matrix.get(reg) || Object.fromEntries(SETTINGS.map((s) => [s, 0]));
      row[p.setting] += w;
      matrix.set(reg, row);
    }
    for (const o of os) origin.set(o.pl, (origin.get(o.pl) || 0) + o.w);
    for (const s of ss) {
      study.set(s.pl, (study.get(s.pl) || 0) + s.w);
      add(studySet, s.pl, p.setting, s.w);
      kindW[M.places[s.pl].kind] += s.w;
      for (const o of os) {
        const k = o.pl + ">" + s.pl;
        arcs.set(k, (arcs.get(k) || 0) + o.w * s.w);
        add(arcSet, k, p.setting, o.w * s.w);
      }
    }
  }
  return { n: sel.length, nScope: keep.length, located, placed, origin, study, arcs, matrix, kindW, ids: sel, keep, studySet, arcSet };
}

export function scopeCounts(M) {
  const c = Object.fromEntries(SCOPES.map((s) => [s, 0]));
  for (const p of M.papers) c[p.scope]++;
  return c;
}

// papers in `ids` per term at one level, with their settings, for the topic table
export function termCounts(M, ids, level) {
  const out = new Map();
  for (const i of ids) {
    const p = M.papers[i], t = termOf(p, level);
    if (t == null) continue;
    const r = out.get(t) || { n: 0, ...Object.fromEntries(SETTINGS.map((s) => [s, 0])) };
    r.n++; r[p.setting]++; out.set(t, r);
  }
  return out;
}

// Bundling by aggregation: arcs whose two ends fall in the same pair of nested cells at this
// zoom level merge into one, at the weighted mean of their ends. Weight and settings add up.
export function bundle(M, arcSet, level, span = 2 * ee(180, 0)[0]) {
  const size = span / 2 ** level, cell = (p) => Math.floor(p.x / size) + ":" + Math.floor(p.y / size), out = new Map();
  for (const [key, r] of arcSet) {
    const [o, d] = key.split(">").map(Number), a = M.places[o], b = M.places[d];
    const ca = cell(a), cb = cell(b), k = ca + ">" + cb, w = SETTINGS.reduce((t, s) => t + r[s], 0);
    const g = out.get(k) || { self: ca === cb, w: 0, ox: 0, oy: 0, dx: 0, dy: 0, set: Object.fromEntries(SETTINGS.map((s) => [s, 0])), kind: {}, o: new Set(), d: new Set() };
    g.w += w; g.ox += a.lon * w; g.oy += a.lat * w; g.dx += b.lon * w; g.dy += b.lat * w;
    for (const s of SETTINGS) g.set[s] += r[s];
    g.kind[b.kind] = (g.kind[b.kind] || 0) + w; g.o.add(o); g.d.add(d);
    out.set(k, g);
  }
  return [...out.values()].map((g) => ({ ...g, o: [...g.o], d: [...g.d], from: [g.ox / g.w, g.oy / g.w], to: [g.dx / g.w, g.dy / g.w] }));
}

export function topics(M, ids, k = 3) {
  const c = new Map();
  for (const i of ids) for (const t of M.papers[i].topics || []) c.set(t, (c.get(t) || 0) + 1);
  return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, k).map(([t, n]) => [M.vocab[t], n]);
}

// Equal Earth (Šavrič, Patterson and Jenny 2019)
const A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796, MM = Math.sqrt(3) / 2, RAD = Math.PI / 180;
export function ee(lon, lat) {
  const l = lon * RAD, t = Math.asin(MM * Math.sin(lat * RAD)), t2 = t * t, t6 = t2 * t2 * t2;
  return [l * Math.cos(t) / (MM * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2))), t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))];
}

// Great circle as projected pieces, split where it crosses the antimeridian; also returns its angle.
export function greatCircle(a, b) {
  const v = (p) => [Math.cos(p[1] * RAD) * Math.cos(p[0] * RAD), Math.cos(p[1] * RAD) * Math.sin(p[0] * RAD), Math.sin(p[1] * RAD)];
  const u = v(a), w = v(b), dot = Math.max(-1, Math.min(1, u[0] * w[0] + u[1] * w[1] + u[2] * w[2])), om = Math.acos(dot);
  const n = Math.max(2, Math.ceil(om / (2 * RAD))), segs = [[]];
  let prev = null;
  for (let i = 0; i <= n; i++) {
    const f = i / n, s = Math.sin(om) < 1e-9 ? [1 - f, f] : [Math.sin((1 - f) * om) / Math.sin(om), Math.sin(f * om) / Math.sin(om)];
    const x = s[0] * u[0] + s[1] * w[0], y = s[0] * u[1] + s[1] * w[1], z = s[0] * u[2] + s[1] * w[2];
    const lon = Math.atan2(y, x) / RAD, lat = Math.asin(Math.max(-1, Math.min(1, z))) / RAD;
    if (prev !== null && Math.abs(lon - prev) > 180) {
      const e0 = prev > 0 ? 180 : -180;
      segs[segs.length - 1].push(ee(e0, lat));
      segs.push([ee(-e0, lat)]);
    }
    segs[segs.length - 1].push(ee(lon, lat));
    prev = lon;
  }
  return { segs, om };
}

// Clustering by zoom with nested cells: the cell at level k+1 splits its parent in four,
// so a cluster only ever splits into its own members as you zoom in.
export function cluster(points, level, span = 2 * ee(180, 0)[0]) {
  const size = span / 2 ** level, cells = new Map();
  for (const p of points) {
    const key = Math.floor(p.x / size) + ":" + Math.floor(p.y / size);
    const c = cells.get(key) || { x: 0, y: 0, w: 0, ids: [] };
    c.x += p.x * p.w; c.y += p.y * p.w; c.w += p.w; c.ids.push(p.id);
    cells.set(key, c);
  }
  return [...cells.values()].map((c) => ({ x: c.x / c.w, y: c.y / c.w, w: c.w, ids: c.ids }));
}
