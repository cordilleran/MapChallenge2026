// statistical checks: Krige's expected between-zone share against simulation; estimator bias by replicates
const S = require("../../site/js/day03simcore.js");
const assert = require("assert");
const KRIGE_TOL = 0.03, VARIO_TOL = 0.06;   // absolute; observed worst 0.009 and 0.037
const ks = [2, 5, 10, 20, 40];
const th = S.krigeShare({}, ks);
const emp = ks.map(() => []);
for (let r = 0; r < 40; r++) {
  const w = S.textbookWorld(1000 + r, {});
  ks.forEach((k, i) => {
    const o = S.evaluate(w, { world: "textbook", estimand: "varshare", var: "X", frame: { kind: "grid", size: k * S.CELL, ox: 0, oy: 0 }, sample: { design: "census", n: 0, seed: 1, beta: 0 } });
    emp[i].push(o.census);
  });
}
ks.forEach((k, i) => console.log("k", k, "theory", th[i].toFixed(3), "sim mean", S.meanOf(emp[i]).toFixed(3), "sd", S.sdOf(emp[i]).toFixed(3)));
ks.forEach((k, i) => assert(Math.abs(th[i] - S.meanOf(emp[i])) <= KRIGE_TOL, "Krige theory vs simulation off at k=" + k));
// empirical variogram of X against the input
const w = S.textbookWorld(77, {}), X = w.layers.X, p = S.TEXTBOOK_DEFAULTS;
for (const lag of [1, 3, 10, 30]) {
  let s = 0, n = 0; for (let y = 0; y < S.N; y++) for (let x = 0; x + lag < S.N; x++) { const d = X[y * S.N + x] - X[y * S.N + x + lag]; s += d * d; n++; }
  const h = lag * S.CELL, g = p.nugget + (1 - p.nugget) * (1 - ((1 - p.longShare) * S.matern(h, p.rhoShort, p.nu) + p.longShare * S.matern(h, p.rhoLong, p.nu)));
  console.log("lag km", h.toFixed(1), "gamma sim", (s / n / 2).toFixed(3), "input", g.toFixed(3));
  assert(Math.abs(s / n / 2 - g) <= VARIO_TOL, "empirical variogram off its input at lag " + h.toFixed(1) + " km");
}
// estimator bias: replicates over samples
const ww = S.watershedWorld(11, {});
const base = (est, extra) => Object.assign({ world: "watershed", worldSeed: 11, estimand: est, var: "precip", var2: "elev", thr: 900, method: "cell", frame: { kind: "grid", size: 6, ox: 0, oy: 0, vseed: 1 }, sample: { design: "random", n: 150, seed: 9, beta: 0 } }, extra || {});
for (const [lab, st] of [["mean random", base("mean")], ["mean pref b=1.5", base("mean", { sample: { design: "random", n: 150, seed: 9, beta: 1.5 } })],
  ["rule cell random", base("rule")], ["rule zone census", base("rule", { method: "zone", sample: { design: "census", n: 0, seed: 1, beta: 0 } })],
  ["rule cell strat", base("rule", { sample: { design: "stratified", n: 150, seed: 9, beta: 0 } })],
  ["exceed cell", base("exceed")], ["exceed zone", base("exceed", { method: "zone" })], ["rank", base("rank")]]) {
  const rep = S.replicate(st, "sample", 200);
  const sm = S.summarize(rep, "est");
  console.log(lab.padEnd(18), "truth", (+rep[0].truth).toFixed(3), "mean est", sm.mean.toFixed(3), "bias", sm.bias.toFixed(3), "sd", sm.sd.toFixed(3));
}
