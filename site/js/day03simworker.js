/* Day 3 worker: replicates, scale curves and offset sweeps off the main thread. */
importScripts("day03simcore.js");
const S = self.D3S;
let cacheKey = "", cacheWorld = null;
function worldFor(b) {
  const k = JSON.stringify([b.world, b.worldSeed, b.worldParams]);
  if (k !== cacheKey) { cacheWorld = S.makeWorld(b.world, b.worldSeed, b.worldParams); cacheKey = k; }
  return cacheWorld;
}
function strip(o) { return { truth: o.truth, census: o.census, est: o.est, nz: o.nz, zonesSampled: o.zonesSampled }; }
self.onmessage = (e) => {
  const m = e.data;
  try {
    if (m.type === "curves") {
      const w = worldFor(m.base), out = { id: m.id, type: "curves", sizes: m.sizes, points: [], sweep: null, theory: null };
      for (const s of m.sizes) {
        const st = JSON.parse(JSON.stringify(m.base));
        if (st.frame.kind === "basin") st.frame.basinKm2 = s; else st.frame.size = s;
        out.points.push(strip(S.evaluate(w, st)));
      }
      if (m.sweep) {
        const sw = [], K = 6;
        for (let i = 0; i < K; i++) for (let j = 0; j < K; j++) {
          const st = JSON.parse(JSON.stringify(m.base));
          st.frame.ox = (i + 0.5) / K * st.frame.size; st.frame.oy = (j + 0.5) / K * st.frame.size;
          sw.push(strip(S.evaluate(w, st)));
        }
        out.sweep = sw;
      }
      if (m.theory) out.theory = S.krigeShare(m.base.worldParams, m.sizes.map((s) => Math.round(s / S.CELL)));
      self.postMessage(out);
    } else if (m.type === "rep") {
      const res = S.replicate(m.base, m.source, m.R, (i, R) => self.postMessage({ id: m.id, type: "progress", source: m.source, i, R }));
      self.postMessage({ id: m.id, type: "rep", source: m.source, res });
    }
  } catch (err) {
    self.postMessage({ id: m.id, type: "error", message: String(err && err.message || err) });
  }
};
