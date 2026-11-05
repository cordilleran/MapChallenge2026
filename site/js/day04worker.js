/* Day 4 worker: clustering, Knox surface and velocity fit off the main thread.
   Points come either as m.glm (raw D4GLM, cached) or m.pts = {x, y, t, area} in km and minutes. */
importScripts("day04core.js");
const C = self.D4C;
let cacheGlm = null, cacheData = null;
function pointsFor(m) {
  if (m.pts) return m.pts;
  if (m.glm) { cacheGlm = m.glm; cacheData = C.load(m.glm); }
  if (!cacheData) throw new Error("no points: send glm or pts");
  return cacheData;
}
self.onmessage = (e) => {
  const m = e.data;
  try {
    const d = pointsFor(m);
    if (m.type === "cluster") {
      const r = C.dbscan(d.x, d.y, d.t, m.params);
      const stats = C.cellStats(r.labels, r.k, d.x, d.y, d.t, d.area_km2 || d.area);
      const kd = C.kdist(d.x, d.y, d.t, m.params.tScale, m.kdistK || Math.max(1, m.params.minPts - 1));
      self.postMessage({ id: m.id, type: "cluster", labels: r.labels, k: r.k, core: r.core, stats, kdist: kd });
    } else if (m.type === "knox") {
      const res = C.knox(d.x, d.y, d.t, m.opts, (i, R) => self.postMessage({ id: m.id, type: "progress", i, R }));
      self.postMessage({ id: m.id, type: "knox", res });
    } else if (m.type === "fit") {
      self.postMessage({ id: m.id, type: "fit", res: C.fitVelocity(m.labels, m.k, d.x, d.y, d.t, m.opts) });
    }
  } catch (err) {
    self.postMessage({ id: m.id, type: "error", message: String(err && err.message || err) });
  }
};
