// Node tests for site/js/day05core.js: projection against gdaltransform, and line of sight against r.viewshed.
// Run from the repo root: node day-05/tests/core_test.js
const fs = require("fs");
const path = require("path");
const core = require("../../site/js/day05core.js");
const root = path.join(__dirname, "..", "..");

// (a) EPSG:4326 -> EPSG:3979 for 20 points, expected values from gdaltransform (GDAL 3.12)
const proj = JSON.parse(fs.readFileSync(path.join(__dirname, "proj_expected_gdal.json")));
let worst = 0;
for (const p of proj) {
  const r = core.projectTo3979(p.lat, p.lon);
  worst = Math.max(worst, Math.hypot(r.x - p.x, r.y - p.y));
}
console.log(`projection: ${proj.length} points, worst offset ${worst.toFixed(4)} m (tolerance 0.05 m) ${worst < 0.05 ? "PASS" : "FAIL"}`);

// (b) visibility at the far end of a profile against vs_<stn>_main.tif
const meta = JSON.parse(fs.readFileSync(path.join(root, "site/data/day05/profile_dem.json")));
const buf = fs.readFileSync(path.join(root, "site/data/day05/profile_dem.bin"));
const dem = core.createDem(new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2), meta);
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "los_sampled_20.json"))).cases;
let agree = 0;
const misses = [];
for (const c of cases) {
  const r = core.losProfile(dem, c.station_x, c.station_y, c.target_x, c.target_y);
  if (r.targetVisible === c.vs_main_visible) agree++;
  else misses.push(`case ${c.id} stn ${c.station}: js ${r.targetVisible}, r.viewshed ${c.vs_main_visible}`);
}
console.log(`line of sight: ${agree}/${cases.length} agree with r.viewshed`);
misses.forEach((m) => console.log("  " + m));
process.exitCode = worst < 0.05 ? 0 : 1;
