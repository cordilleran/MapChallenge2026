// Far-end visibility of 60 profiles (half seen, half hidden in r.viewshed) and the per-sample flags,
// written out for the sample check to compare with the rasters. Run from the repo root.
const fs = require("fs"), path = require("path");
const core = require("../../site/js/day05core.js");
const root = path.join(__dirname, "..", "..");
const meta = JSON.parse(fs.readFileSync(path.join(root, "site/data/day05/profile_dem.json")));
const buf = fs.readFileSync(path.join(root, "site/data/day05/profile_dem.bin"));
const dem = core.createDem(new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2), meta);
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "los_cases_60.json"))).cases;
let agree = 0; const samples = []; const t0 = Date.now();
for (const c of cases) {
  const r = core.losProfile(dem, c.sx, c.sy, c.tx, c.ty);
  if ((r.targetVisible ? 1 : 0) === c.rv) agree++;
  const n = r.distances.length, L = r.distances[n - 1];
  for (let i = 1; i < n; i++) {
    const f = r.distances[i] / L;
    samples.push([c.station, c.sx + (c.tx - c.sx) * f, c.sy + (c.ty - c.sy) * f, r.visible[i]]);
  }
}
console.log(`far end: ${agree}/${cases.length} agree with r.viewshed; ${((Date.now() - t0) / cases.length).toFixed(1)} ms per profile`);
fs.writeFileSync(path.join(__dirname, "los_samples_out.json"), JSON.stringify(samples));
