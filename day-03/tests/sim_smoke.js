// smoke and invariant checks for site/js/day03simcore.js (node day-03/tests/sim_smoke.js)
const S = require("../../site/js/day03simcore.js");
const assert = require("assert");
const t0 = Date.now();
const tw = S.textbookWorld(11, {});
console.log("textbook ms", Date.now() - t0, "X mean/sd", S.meanOf(tw.layers.X).toFixed(3), S.sdOf(tw.layers.X).toFixed(3));
const t1 = Date.now();
const ww = S.watershedWorld(11, {});
console.log("watershed ms", Date.now() - t1);
for (const v of [...S.VARIABLES.watershed, {id:"power"}]) {
  const a = Array.from(ww.layers[v.id]).filter(Number.isFinite);
  a.sort((x, y) => x - y);
  console.log(v.id.padEnd(7), "n", a.length, "p5", a[Math.floor(a.length * .05)].toFixed(2), "p50", a[a.length >> 1].toFixed(2), "p95", a[Math.floor(a.length * .95)].toFixed(2));
}
const becN = [0,0,0,0,0]; for (const b of ww.bec) becN[b]++; console.log("BEC counts", becN);
const maxA = Math.max(...ww.area); console.log("max drainage km2", maxA.toFixed(1), "stream cells", ww.stream.reduce((a,b)=>a+b,0));
// invariant: census mean through any frame equals the truth
const base = (frame, est, extra) => Object.assign({ world: "watershed", worldSeed: 11, estimand: est, var: "precip", var2: "elev", thr: 1000, method: "cell",
  frame, sample: { design: "census", n: 200, seed: 5, beta: 0 } }, extra || {});
for (const f of [{ kind: "grid", size: 4, ox: 1, oy: 2 }, { kind: "hex", size: 4, ox: .3, oy: .1 }, { kind: "vor", size: 4, vseed: 3 }, { kind: "basin", basinKm2: 20 }, { kind: "bec" }]) {
  const o = S.evaluate(ww, base(f, "mean"));
  console.log("census mean", f.kind.padEnd(5), "nz", o.nz, "truth", o.truth.toFixed(4), "census", o.census.toFixed(4), "est", o.est.toFixed(4));
  assert(Math.abs(o.census - o.truth) <= 1e-9 * Math.abs(o.truth), "census mean != truth under " + f.kind);
}
// the same invariant on the textbook world (the world the page uses), shifted lognormal so the mean is away from zero
const twl = S.textbookWorld(21, { marginal: "lognormal" });
for (const f of [{ kind: "grid", size: 4, ox: 1, oy: 2 }, { kind: "hex", size: 4, ox: .3, oy: .1 }, { kind: "vor", size: 4, vseed: 3 }]) {
  const o = S.evaluate(twl, { world: "textbook", worldSeed: 21, estimand: "mean", var: "X", method: "cell", frame: f, sample: { design: "census", n: 0, seed: 1, beta: 0 } });
  console.log("textbook census mean", f.kind.padEnd(5), "truth", o.truth.toFixed(4), "census", o.census.toFixed(4));
  assert(Math.abs(o.census - o.truth) <= 1e-9 * Math.abs(o.truth), "textbook census mean != truth under " + f.kind);
}
for (const est of ["varshare", "corr", "exceed", "rule", "rank"]) {
  for (const d of ["random", "systematic", "stratified"]) {
    const st = base({ kind: "grid", size: 6, ox: 0, oy: 0 }, est, { sample: { design: d, n: 150, seed: 9, beta: 0 } });
    const o = S.evaluate(ww, st);
    console.log(est.padEnd(8), d.padEnd(10), "n", o.n, "truth", (+o.truth).toFixed(3), "census", (+o.census).toFixed(3), "est", (+o.est).toFixed(3), "zones", o.zonesSampled + "/" + o.nz);
  }
}
const pref = S.evaluate(ww, base({ kind: "grid", size: 6, ox: 0, oy: 0 }, "mean", { var: "snow", sample: { design: "random", n: 150, seed: 9, beta: 1.5 } }));
console.log("preferential snow mean: truth", pref.truth.toFixed(3), "est", pref.est.toFixed(3));
const sv = S.evaluate(ww, base({ kind: "svor" }, "mean", { sample: { design: "random", n: 80, seed: 9, beta: 0 } }));
console.log("sample voronoi nz", sv.nz, "n", sv.n);
const t2 = Date.now();
const rep = S.replicate(base({ kind: "grid", size: 6, ox: 0, oy: 0 }, "mean", { sample: { design: "random", n: 100, seed: 9, beta: 0 } }), "sample", 50);
console.log("50 sample reps ms", Date.now() - t2, S.summarize(rep, "est"));
const t3 = Date.now();
const repw = S.replicate(base({ kind: "grid", size: 6, ox: 0, oy: 0 }, "mean", { sample: { design: "random", n: 100, seed: 9, beta: 0 } }), "world", 10);
console.log("10 world reps ms", Date.now() - t3);
console.log("krige share k=5,10,20,40", S.krigeShare({}, [5, 10, 20, 40]).map((x) => x.toFixed(3)));
