// W1 and W2 checks: the simulator's known totals appear exactly in the app's
// aggregation, and the weight invariants hold for every scope filter.
// Run: node --test day-09/app/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { load, view, scopeCounts, cluster, bundle, termCounts, termOf, SCOPES, SETTINGS } from "../core.js";

const here = new URL("../data/", import.meta.url);
const world = JSON.parse(readFileSync(new URL("world50.json", here)));
const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6, `${msg}: ${a} vs ${b}`);

const corpora = ["sim", "sim_b"].concat(existsSync(new URL("day09.json", here)) ? ["day09"] : []);
for (const name of corpora) {
  const C = JSON.parse(readFileSync(new URL(`${name}.json`, here)));
  const E = JSON.parse(readFileSync(new URL(`${name}_expected.json`, here)));
  const M = load(C, world);
  const all = { scopes: new Set(SCOPES), origin: "all", dir: "studies", sel: null };

  test(`${name}: totals match the simulator`, () => {
    const v = view(M, all);
    assert.equal(v.n, E.papers);
    assert.equal(v.located, E.located);
    assert.equal(v.placed, E.placed);
    assert.deepEqual(scopeCounts(M), Object.fromEntries(SCOPES.map((s) => [s, E.scopes[s] || 0])));
    for (const k of ["area", "feature", "settlement"]) close(v.kindW[k], E.study_weight_by_kind[k], k);
  });

  test(`${name}: both region schemes count the same papers, and every institution has a region in each`, () => {
    const tot = (st) => [...view(M, st).matrix.values()].reduce((a, r) => a + SETTINGS.reduce((t, s) => t + r[s], 0), 0);
    close(tot({ ...all, regions: "m49" }), tot({ ...all, regions: "wb" }), "matrix total");
    for (const p of M.places) if (p.kind === "institution") assert.ok(p.regions.m49 && p.regions.wb, p.name);
  });

  test(`${name}: weight invariants hold for every single-scope filter`, () => {
    for (const s of SCOPES) {
      const v = view(M, { ...all, scopes: new Set([s]) });
      let m = 0;
      for (const row of v.matrix.values()) for (const x of Object.values(row)) m += x;
      close(m, v.n, `${s} matrix sums to papers`);
      close([...v.origin.values()].reduce((a, b) => a + b, 0), v.located, `${s} origin weight = located`);
      close([...v.study.values()].reduce((a, b) => a + b, 0), v.placed, `${s} study weight = placed`);
      let both = 0;
      for (const i of v.ids) if (M.byPaper[i].o.length && M.byPaper[i].s.length) both++;
      close([...v.arcs.values()].reduce((a, b) => a + b, 0), both, `${s} arc weight = located and placed`);
    }
  });

  test(`${name}: invariants hold with body-text places left out`, () => {
    const v = view(M, { ...all, body: false });
    close([...v.study.values()].reduce((a, b) => a + b, 0), v.placed, "study weight = placed");
    let m = 0;
    for (const row of v.matrix.values()) for (const x of Object.values(row)) m += x;
    close(m, v.n, "matrix sums to papers");
  });

  test(`${name}: settings split the arc and study weights exactly`, () => {
    const v = view(M, all);
    const sum = (m) => [...m.values()].reduce((a, r) => a + SETTINGS.reduce((t, s) => t + r[s], 0), 0);
    close(sum(v.arcSet), [...v.arcs.values()].reduce((a, b) => a + b, 0), "arc settings");
    close(sum(v.studySet), v.placed, "study settings");
  });

  test(`${name}: bundling keeps the total arc weight at every zoom level`, () => {
    const v = view(M, all), tot = [...v.arcs.values()].reduce((a, b) => a + b, 0);
    let prev = 0;
    for (const lv of [3, 5, 8, 12]) {
      const b = bundle(M, v.arcSet, lv);
      close(b.reduce((a, g) => a + g.w, 0), tot, `level ${lv}`);
      assert.ok(b.length >= prev, `level ${lv}: bundles only split as you zoom in`);
      prev = b.length;
    }
    assert.ok(bundle(M, v.arcSet, 3).length < v.arcs.size, "the widest zoom merges something");
  });

  test(`${name}: a topic selection keeps exactly the papers with that term`, () => {
    for (const level of ["field", "subfield", "topic"]) {
      const tc = termCounts(M, view(M, all).keep, level);
      if (!tc.size) continue;
      const [t, r] = [...tc.entries()].sort((a, b) => b[1].n - a[1].n)[0];
      const v = view(M, { ...all, sel: { kind: "topic", level, ids: new Set([t]) } });
      assert.equal(v.n, r.n);
      assert.equal(v.n, M.papers.filter((p) => termOf(p, level) === t).length);
    }
  });

  test(`${name}: a place selection counts distinct papers`, () => {
    const v0 = view(M, all);
    const [pl] = [...v0.study.entries()].sort((a, b) => b[1] - a[1])[0];
    const v = view(M, { ...all, sel: { kind: "place", ids: new Set([pl]) } });
    const direct = M.byPaper.filter((b) => b.s.some((s) => s.pl === pl)).length;
    assert.equal(v.n, direct);
  });
}

test("clusters nest: every level-k+1 cluster lies inside one level-k cluster", () => {
  const pts = Array.from({ length: 500 }, (_, i) => ({ id: i, x: Math.sin(i) * 2.5, y: Math.cos(i * 1.7) * 1.2, w: 1 }));
  for (let k = 1; k < 6; k++) {
    const parent = new Map();
    cluster(pts, k).forEach((c, j) => c.ids.forEach((id) => parent.set(id, j)));
    for (const c of cluster(pts, k + 1)) assert.equal(new Set(c.ids.map((id) => parent.get(id))).size, 1);
  }
});

// the public data file publishes no place that no paper links to, and no point place studied by one paper only
// (D128 coarsening; preflight finding Bp2)
if (existsSync(new URL("day09.json", here))) {
  test("day09: public places are all linked, and no point place rests on one paper", () => {
    const C = JSON.parse(readFileSync(new URL("day09.json", here)));
    const used = new Set([...C.studies.rows.map((r) => r[1]), ...C.origins.rows.map((r) => r[1])]);
    assert.equal(used.size, C.places.rows.length);
    const n = new Map();
    for (const r of C.studies.rows) n.set(r[1], (n.get(r[1]) || 0) + 1);
    // finer than a province and inside one country: needs two papers (multi-country regions such as the Andes are coarser than a country)
    const fc = C.places.cols.indexOf("fcode"), code = C.places.cols.indexOf("code");
    const WHOLE = new Set(["PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "ADM1", "CONT", "OCN", "SEA"]);
    for (const [pl, c] of n) {
      const p = C.places.rows[pl];
      if (!WHOLE.has(p[fc]) && p[code]) assert.ok(c > 1, p[0]);
    }
    // topic labels: one per paper, each shared by 3 or more papers; no keywords
    const t = new Map();
    for (const r of C.papers.rows) { assert.ok(r[4].length <= 1); for (const x of r[4]) t.set(x, (t.get(x) || 0) + 1); }
    for (const [x, c] of t) assert.ok(c >= 3, C.vocab[x]);
    for (const col of ["subfield", "field"]) {
      const j = C.papers.cols.indexOf(col), m = new Map();
      for (const r of C.papers.rows) if (r[j] != null) m.set(r[j], (m.get(r[j]) || 0) + 1);
      for (const [x, c] of m) assert.ok(c >= 3, `${col} ${C.vocab[x]}`);
    }
  });
}
