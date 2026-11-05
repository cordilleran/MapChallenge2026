/* Day 4 engine tests (node): node day-04/tests/core_test.js */
"use strict";
const fs = require("fs"), path = require("path");
const C = require("../../site/js/day04core.js");
let fails = 0;
function check(name, ok, info) { console.log((ok ? "PASS " : "FAIL ") + name + (info ? "  " + info : "")); if (!ok) fails++; }

// excess within the first dBin edges / lags: sum(obs - permMean) over lag <= lagMax and d < dMax
function excess(r, dCut, lagMax) {
  let inD = 0, all = 0;
  for (let tb = 0; tb < r.tBins; tb++) {
    if (r.tEdges[tb + 1] > lagMax) break;
    for (let db = 0; db < r.dBins; db++) {
      const e = r.obs[tb * r.dBins + db] - r.permMean[tb * r.dBins + db];
      all += e; if (r.dEdges[db + 1] <= dCut) inD += e;
    }
  }
  return { inD, all, share: all > 0 ? inD / all : 0 };
}
function ridge(r, tb) {
  let best = -Infinity, bd = -1;
  for (let db = 0; db < r.dBins; db++) { const e = r.obs[tb * r.dBins + db] - r.permMean[tb * r.dBins + db]; if (e > best) { best = e; bd = db; } }
  return 0.5 * (r.dEdges[bd] + r.dEdges[bd + 1]);
}

// (a) simulated storm, drift (0, 50) km/h
const sim = C.simStorm(7, { u: 0, v: 50 });
const g = C.knox(sim.x, sim.y, sim.t, { u: 0, v: 0, nPerm: 39, seed: 3 });
const s = C.knox(sim.x, sim.y, sim.t, { u: 0, v: 50, nPerm: 39, seed: 3 });
const r0 = ridge(g, 0), r3 = ridge(g, 3), r0s = ridge(s, 0), r3s = ridge(s, 3);
check("ground frame: ridge moves out with lag", r3 >= 20 && r3 > r0 + 10, `ridge d at lag 0-10 min = ${r0} km, at 30-40 min = ${r3} km (need >= 20 and > +10)`);
check("storm frame: ridge stays near zero", r3s <= 10, `ridge d at lag 30-40 min = ${r3s} km (need <= 10)`);
const eg = excess(g, 10, 60), es = excess(s, 10, 60);
console.log(`  metric: share of excess pairs (obs - permMean, lag <= 60 min, d < 100 km) that lie within 10 km; ground ${eg.share.toFixed(3)}, storm ${es.share.toFixed(3)}`);
check("storm-frame short-distance excess share clearly higher", es.share > 0.5 && es.share > 2 * eg.share, "need storm > 0.5 and > 2 x ground");

// knox pair counts against a brute-force count (observed, storm frame) on a small sim
{
  const sm = C.simStorm(11, { nCells: 8, flashesPerCell: 30 }), n = sm.x.length, nb = 20 * 18, bf = new Float64Array(nb);
  for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
    const lag = Math.abs(sm.t[i] - sm.t[j]); if (lag >= 180) continue;
    const dx = (sm.x[i] - 0) - (sm.x[j] - 0), dy = (sm.y[i] - 50 * sm.t[i] / 60) - (sm.y[j] - 50 * sm.t[j] / 60);
    const d = Math.hypot(dx, dy); if (d >= 100) continue;
    bf[Math.floor(lag / 10) * 20 + Math.floor(d / 5)]++;
  }
  const kk = C.knox(sm.x, sm.y, sm.t, { u: 0, v: 50, nPerm: 2 });
  check("knox observed counts equal brute force", kk.obs.every((v, i) => v === bf[i]), "pairs " + bf.reduce((a, b) => a + b, 0));
}

// (b) fitVelocity
const db = C.dbscan(sim.x, sim.y, sim.t, { eps: 10, tScale: 0.5, minPts: 5 });
const fit = C.fitVelocity(db.labels, db.k, sim.x, sim.y, sim.t);
const errv = Math.hypot(fit.u - 0, fit.v - 50) / 50;
check("fitVelocity recovers drift within 15%", errv < 0.15, `fit u=${fit.u.toFixed(2)} v=${fit.v.toFixed(2)} km/h from ${fit.nCells} cells (k=${db.k}, truth 40 cells); error ${(100 * errv).toFixed(1)}%`);

// (c) tiny hand case: two blobs of 3 points, one border point between reach of A only, one noise point
{
  const x = Float64Array.from([0, 1, 0, 10, 11, 10, 2.5, 50]);
  const y = Float64Array.from([0, 0, 1, 0, 0, 1, 0, 50]);
  const t = new Float64Array(8);
  const r = C.dbscan(x, y, t, { eps: 1.5, tScale: 1, minPts: 3 });
  const ok = r.k === 2 && [0, 1, 2].every((i) => r.labels[i] === 0) && [3, 4, 5].every((i) => r.labels[i] === 1) &&
    r.labels[6] === 0 && r.labels[7] === -1 && r.core[6] === 0 && r.core[0] === 1 && r.core[7] === 0;
  check("dbscan hand case", ok, "labels " + Array.from(r.labels).join(","));
  const kd = C.kdist(x, y, t, 1, 2);
  check("kdist hand case", Math.abs(kd[0] - 1) < 1e-12 && kd.length === 8 && kd[7] > 40, "kdist " + Array.from(kd).map((v) => v.toFixed(2)).join(","));
  // time scaling separates otherwise-adjacent points
  const t2 = Float64Array.from([0, 0, 0, 0, 0, 0, 0, 0]); t2[2] = 100;
  const r2 = C.dbscan(x, y, t2, { eps: 1.5, tScale: 1, minPts: 3 });
  check("dbscan time scaling", r2.labels[2] === -1 && r2.k === 2, "labels " + Array.from(r2.labels).join(","));
}

// (d) timing on real data
const src = fs.readFileSync(path.join(__dirname, "../../site/data/day04_glm.js"), "utf8");
const win = {}; new Function("window", src)(win);
const d = C.load(win.D4GLM);
check("load counts", d.x.length === 6547 && d.gx.length === 40200, `${d.x.length} flashes, ${d.gx.length} groups`);
let t0 = process.hrtime.bigint();
const kn = C.knox(d.x, d.y, d.t, { nPerm: 39, seed: 1 });
let ms = Number(process.hrtime.bigint() - t0) / 1e6;
console.log(`  knox real data, ground frame, 39 permutations: ${(ms / 1000).toFixed(2)} s`);
check("knox timing under 3 s", ms < 3000, `${(ms / 1000).toFixed(2)} s`);
t0 = process.hrtime.bigint();
const dd = C.dbscan(d.x, d.y, d.t, { eps: 10, tScale: 1, minPts: 5 }); const st = C.cellStats(dd.labels, dd.k, d.x, d.y, d.t, d.area_km2);
const kd = C.kdist(d.x, d.y, d.t, 1, 4);
console.log(`  dbscan+cellStats+kdist real data: ${(Number(process.hrtime.bigint() - t0) / 1e6).toFixed(0)} ms; k=${dd.k}, noise ${(100 * st.noiseShare).toFixed(1)}%, median lifetime ${st.medLifetime.toFixed(1)} min, median radius ${st.medRadius.toFixed(1)} km`);
const fr = C.fitVelocity(dd.labels, dd.k, d.x, d.y, d.t);
console.log(`  real-data fitted velocity u=${fr.u.toFixed(1)} v=${fr.v.toFixed(1)} km/h from ${fr.nCells} cells`);
check("knox sanity: short-lag short-distance ratio > 1", kn.ratio[0] > 1, "ratio " + kn.ratio[0].toFixed(2));

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
