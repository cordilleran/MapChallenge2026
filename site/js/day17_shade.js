// Day 17 Light and dark: Mountain's Shadow (data: day-17/scripts/s4_export.py).
// World axes: X = east (m) from the LiDAR centre, Y = height above Z0 (m, times exaggeration), Z = -north (m).
// The surface is unlit on purpose (D338): its tone is the measured shade share and nothing else.
import * as THREE from "three";
import { OrbitControls } from "../vendor/three-0.186.1/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const status = (t) => ($("status").textContent = t);
window.addEventListener("error", (e) => status("Error: " + e.message));
window.addEventListener("unhandledrejection", (e) => status("Could not load the map data: " + (e.reason?.message || e.reason)));
const ok = (r) => { if (!r.ok) throw new Error(`${r.url} (${r.status})`); return r; };
const getJSON = (p) => fetch(p).then(ok).then((r) => r.json());
const getBuf = (p) => fetch(p).then(ok).then((r) => r.arrayBuffer());
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const DATA = "data/day17/";

const [meta, labels, nearU16, regionU16, nearRO, regionRO] = await Promise.all([
  getJSON(DATA + "meta.json"), getJSON(DATA + "labels.json"),
  getBuf(DATA + "near_dem_10m.u16"), getBuf(DATA + "region_dtm_90m.u16"),
  getBuf(DATA + "near_readout_10m.u8"), getBuf(DATA + "region_readout_90m.u8"),
]);
const N = meta.near, R = meta.region, W = meta.weekly;
const CX = (N.x0 + N.x1) / 2, CY = (N.y0 + N.y1) / 2;
const nearH = new Uint16Array(nearU16), regionH = new Uint16Array(regionU16);
const nearRo = new Uint8Array(nearRO), regionRo = new Uint8Array(regionRO);

// ---------- renderer and camera
const PAPER = new THREE.Color("#efe9dc"), INK = new THREE.Color("#1b1a19");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(PAPER);
renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // shader writes display values directly
$("view").appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 20, 200000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = !reduceMotion;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 300; controls.maxDistance = 70000;
const maxTex = renderer.capabilities.maxTextureSize;

// ---------- geometry from a Uint16 height grid (row 0 = north)
const BLEND = 400; // m: the LiDAR mesh eases to the regional surface over its outer 400 m, so the window has no cut edge
function grid(u16, w, h, x0, y1, cell, edge = null) {
  const pos = new Float32Array(w * h * 3);
  for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
    const i = r * w + c, e = x0 + (c + 0.5) * cell, n = y1 - (r + 0.5) * cell;
    let z = u16[i] * meta.zscale;
    if (edge) {
      const d = Math.min(e - edge[0], edge[2] - e, n - edge[1], edge[3] - n);
      if (d < BLEND) {
        const zr = regionHeight(e, n), t = Math.max(0, d / BLEND), wgt = t * t * (3 - 2 * t);
        if (!Number.isNaN(zr)) z = zr + (z - zr) * wgt;
      }
    }
    pos[i * 3] = e - CX;
    pos[i * 3 + 1] = z;
    pos[i * 3 + 2] = -(n - CY);
  }
  const idx = new Uint32Array((w - 1) * (h - 1) * 6);
  let k = 0;
  for (let r = 0; r < h - 1; r++) for (let c = 0; c < w - 1; c++) {
    const a = r * w + c, b = a + 1, d = a + w, e = d + 1;
    idx[k++] = a; idx[k++] = d; idx[k++] = b; idx[k++] = b; idx[k++] = d; idx[k++] = e;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeBoundingSphere();
  return g;
}

// ---------- the charcoal shader
const vert = /* glsl */`
uniform float uEx; uniform float uZ0;
varying vec2 vEN; varying float vH;
void main() {
  vec3 p = position;
  vH = p.y + uZ0;
  vEN = vec2(p.x, -p.z);   // metres from the scene centre: small numbers keep float32 precise on the GPU
  p.y *= uEx;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`;
const frag = /* glsl */`
uniform sampler2D tA; uniform sampler2D tB; uniform vec4 uBA;
uniform float uDiff, uStyle, uContour, uHoleOn, uFade;
uniform vec4 uHole; uniform vec4 uExt; uniform vec3 uPaper; uniform vec3 uInk;
varying vec2 vEN; varying float vH;

float hash(vec2 p) { p = mod(p, 1024.0); p = fract(p * vec2(0.1234, 0.4562)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
// one family of hand-drawn strokes: wobbling, tapered, broken
float strokes(vec2 p, float ang, float sp, float w) {
  vec2 d = vec2(cos(ang), sin(ang)), n = vec2(-d.y, d.x);
  float along = dot(p, d) / sp, across = dot(p, n) / sp;
  float row = floor(across);
  float wob = (vnoise(vec2(along * 0.3, row * 7.1)) - 0.5) * 0.45;
  float f = abs(fract(across + wob) - 0.5);
  float aa = fwidth(across) * 0.9;
  float ww = w * (0.6 + 0.6 * vnoise(vec2(along * 0.5, row * 3.7)));
  float line = 1.0 - smoothstep(ww * 0.5 - aa, ww * 0.5 + aa, f);
  float gap = smoothstep(0.18, 0.4, vnoise(vec2(along * 0.45 + row * 1.3, row * 3.3)));
  return line * gap;
}
float charcoal(vec2 p, float sp, float v) {
  float g = vnoise(p / sp * 2.3) * 0.55 + vnoise(p / sp * 6.1) * 0.45;          // paper tooth
  float h1 = strokes(p, 0.79, sp, mix(0.3, 0.8, smoothstep(0.1, 0.5, v))) * smoothstep(0.06, 0.28, v);
  float h2 = strokes(p, -0.62, sp * 0.93, mix(0.25, 0.75, smoothstep(0.35, 0.8, v))) * smoothstep(0.33, 0.55, v);
  float h3 = strokes(p, 0.12, sp * 0.81, 0.7) * smoothstep(0.62, 0.82, v);
  float hatch = max(max(h1, h2), h3) * (0.75 + 0.25 * g);
  float rub = smoothstep(g - 0.18, g + 0.18, v * 1.1 - 0.12);                  // charcoal rubbed into the tooth
  float dark = max(hatch * 0.9, rub * (0.55 + 0.4 * v));
  return mix(v, dark, 0.7);                                                     // the mean tone stays the data
}
void main() {
  if (uHoleOn > 0.5 && vEN.x > uHole.x && vEN.x < uHole.z && vEN.y > uHole.y && vEN.y < uHole.w) discard;
  vec2 uv = vec2((vEN.x - uBA.x) / (uBA.z - uBA.x), (vEN.y - uBA.y) / (uBA.w - uBA.y));
  float a = texture2D(tA, uv).r;
  float v = a;
  if (uDiff > 0.5) v = clamp(a - texture2D(tB, uv).r, 0.0, 1.0);
  float px = max(max(length(dFdx(vEN)), length(dFdy(vEN))), 0.05);  // the coarser screen axis, so grazing slopes don't alias
  float dark;
  if (uStyle < 0.5) dark = v;
  else {
    float lv = log2(px * 7.0), l0 = floor(lv);
    float sk = mix(charcoal(vEN, exp2(l0), v), charcoal(vEN, exp2(l0 + 1.0), v), lv - l0);
    dark = mix(sk, v, smoothstep(24.0, 64.0, px * 7.0));   // far away, strokes would be hundreds of metres: draw a wash
  }
  vec3 col = mix(uPaper, uInk, dark);
  if (uContour > 0.5) {
    float cc = vH / 50.0, fw = fwidth(cc);
    float line = 1.0 - smoothstep(0.0, fw * 1.3, abs(fract(cc + 0.5) - 0.5));
    bool major = abs(mod(vH + 125.0, 250.0) - 125.0) < 25.0;
    float brk = smoothstep(0.2, 0.35, vnoise(vEN / 140.0));
    float alpha = line * brk * (major ? 0.5 : 0.28) * (1.0 - smoothstep(0.25, 0.5, fw));
    col = mix(col, vec3(0.42, 0.29, 0.17), alpha);                              // sepia contour, apart from the charcoal
  }
  if (uFade > 0.5) {
    float e = min(min(vEN.x - uExt.x, uExt.z - vEN.x), min(vEN.y - uExt.y, uExt.w - vEN.y));
    col = mix(uPaper, col, smoothstep(0.0, 3500.0, e));
  }
  gl_FragColor = vec4(col, 1.0);
}`;
const blank = new THREE.DataTexture(new Uint8Array([0]), 1, 1, THREE.RedFormat); blank.needsUpdate = true;
const rel = (b) => b && [b[0] - CX, b[1] - CY, b[2] - CX, b[3] - CY];
function material(bounds, hole, ext) {
  bounds = rel(bounds); hole = rel(hole); ext = rel(ext);
  return new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag,
    uniforms: {
      tA: { value: blank }, tB: { value: blank }, uBA: { value: new THREE.Vector4(...bounds) },
      uDiff: { value: 0 }, uStyle: { value: 1 }, uContour: { value: 1 },
      uHoleOn: { value: hole ? 1 : 0 }, uHole: { value: new THREE.Vector4(...(hole || [0, 0, 0, 0])) },
      uFade: { value: ext ? 1 : 0 }, uExt: { value: new THREE.Vector4(...(ext || [0, 0, 0, 0])) },
      uEx: { value: 1.5 }, uZ0: { value: meta.z0 },
      uPaper: { value: PAPER }, uInk: { value: INK },
    },
  });
}
const nearMat = material([N.x0, N.y0, N.x1, N.y1]);
const regionMat = material([R.x0, R.y0, R.x1, R.y1], [N.x0 + 12, N.y0 + 12, N.x1 - 12, N.y1 - 12], [R.x0, R.y0, R.x1, R.y1]);
regionMat.polygonOffset = true; regionMat.polygonOffsetFactor = 2; regionMat.polygonOffsetUnits = 2; // the near mesh wins where they overlap
function regionHeight(e, n) {
  return bilin(regionH, R.geom_w, R.geom_h, (e - R.x0) / R.geom_cell - 0.5, (R.y1 - n) / R.geom_cell - 0.5) * meta.zscale;
}
scene.add(new THREE.Mesh(grid(regionH, R.geom_w, R.geom_h, R.x0, R.y1, R.geom_cell), regionMat));
scene.add(new THREE.Mesh(grid(nearH, N.geom_w, N.geom_h, N.x0, N.y1, N.geom_cell, [N.x0, N.y0, N.x1, N.y1]), nearMat));

// ---------- textures (greyscale WebP into one red channel), cached, fitted to the GPU's limit
const texCache = new Map();
function loadTex(name) {
  if (texCache.has(name)) return texCache.get(name);
  const p = new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      let src = img;
      if (img.width > maxTex || img.height > maxTex) {
        const s = maxTex / Math.max(img.width, img.height), cv = document.createElement("canvas");
        cv.width = Math.floor(img.width * s); cv.height = Math.floor(img.height * s);
        cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height); src = cv;
      }
      const t = new THREE.Texture(src);
      t.format = THREE.RedFormat; t.colorSpace = THREE.NoColorSpace;
      t.anisotropy = renderer.capabilities.getMaxAnisotropy(); t.needsUpdate = true;
      resolve(t);
    };
    img.onerror = () => reject(new Error("missing " + name));
    img.src = DATA + name;
  });
  texCache.set(name, p);
  return p;
}

// ---------- one date: rebuilt on the GPU from a temporal PCA basis (D353)
// Each weekly stack is stored as its mean over the 27 weeks plus K component images. A date's shade is
// mean + sum_j w_j * component_j, with the weights interpolated between the two nearest weeks by solar declination.
const PCA = W.pca, PREFIX = { near_dsm: "near_wk_dsm", near_dem: "near_wk_dem", region_dsm: "region_wk_dsm", region_dtm: "region_wk_dtm" };
const KMAX = 8;
const pcaQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
  uniforms: { tC: { value: [] }, uLo: { value: new Array(KMAX + 1).fill(0) }, uHi: { value: new Array(KMAX + 1).fill(0) },
    uW: { value: new Array(KMAX).fill(0) }, uK: { value: 0 } },
  vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
  fragmentShader: `precision highp float;
uniform sampler2D tC[${KMAX + 1}]; uniform float uLo[${KMAX + 1}]; uniform float uHi[${KMAX + 1}]; uniform float uW[${KMAX}]; uniform int uK;
varying vec2 vUv;
void main() {
  float v = uLo[0] + texture2D(tC[0], vUv).r * (uHi[0] - uLo[0]);
${[...Array(KMAX).keys()].map((i) => { const j = i + 1;
    return `  if (${j} <= uK) v += uW[${i}] * (uLo[${j}] + texture2D(tC[${j}], vUv).r * (uHi[${j}] - uLo[${j}]));`; }).join("\n")}
  gl_FragColor = vec4(clamp(v / 255.0, 0.0, 1.0), 0.0, 0.0, 1.0);
}`,
  depthTest: false, depthWrite: false,
}));
const pcaScene = new THREE.Scene(), pcaCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
pcaQuad.frustumCulled = false; pcaScene.add(pcaQuad);
const basisCache = new Map(), rtCache = new Map();
function loadBasis(key) {
  if (!basisCache.has(key)) {
    const k = PCA[key].k;
    basisCache.set(key, Promise.all([...Array(k + 1).keys()].map((j) => loadTex(`${PREFIX[key]}_pc${j}.webp`))).then((ts) => {
      for (const c of ts) { c.minFilter = c.magFilter = THREE.NearestFilter; c.generateMipmaps = false; c.anisotropy = 1; c.needsUpdate = true; }
      return ts;
    }));
  }
  return basisCache.get(key);
}
function weightsAt(key, doy) {
  const f = W.week_of_doy[doy - 1], i = Math.min(Math.floor(f), 25), a = f - i, wt = PCA[key].weights;
  return wt[i].map((w, j) => w * (1 - a) + wt[i + 1][j] * a);
}
async function weekTex(key, doy) {
  const ts = await loadBasis(key), P = PCA[key], w = weightsAt(key, doy);
  let rt = rtCache.get(key);
  if (!rt) {
    rt = new THREE.WebGLRenderTarget(ts[0].image.width, ts[0].image.height, { format: THREE.RedFormat, type: THREE.UnsignedByteType,
      minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter, generateMipmaps: true, depthBuffer: false });
    rt.texture.anisotropy = renderer.capabilities.getMaxAnisotropy(); rt.texture.colorSpace = THREE.NoColorSpace;
    rtCache.set(key, rt);
  }
  const u = pcaQuad.material.uniforms;
  u.tC.value = [...ts, ...Array(KMAX + 1 - ts.length).fill(ts[0])];
  u.uLo.value = [...P.ranges.map((r) => r[0]), ...Array(KMAX + 1 - ts.length).fill(0)];
  u.uHi.value = [...P.ranges.map((r) => r[1]), ...Array(KMAX + 1 - ts.length).fill(0)];
  u.uW.value = [...w, ...Array(KMAX - w.length).fill(0)]; u.uK.value = P.k;
  const prev = renderer.getRenderTarget();
  renderer.setRenderTarget(rt); renderer.render(pcaScene, pcaCam); renderer.setRenderTarget(prev);
  return rt.texture;
}
const getTex = (name) => name.startsWith("wk:") ? weekTex(name.slice(3), state.doy) : loadTex(name);

// ---------- state
const state = { when: "year", src: "all", style: "grey", doy: 355, ex: 1.5 };
function names() {
  const nearSurf = state.src === "hills" ? "dem" : "dsm", regSurf = state.src === "hills" ? "dtm" : "dsm";
  if (state.when === "date") {
    const out = { nearA: `wk:near_${nearSurf}`, regA: `wk:region_${regSurf}`, weekly: true };
    if (state.src === "objects") { out.nearB = "wk:near_dem"; out.regB = "wk:region_dtm"; }
    return out;
  }
  const tag = state.when;
  const out = { nearA: `near_${tag}_${nearSurf}.webp`, regA: `region_${tag}_${regSurf}.webp` };
  if (state.src === "objects") { out.nearB = `near_${tag}_dem.webp`; out.regB = `region_${tag}_dtm.webp`; }
  out.weekly = state.when === "date";
  return out;
}
let applySeq = 0;
async function apply() {
  const seq = ++applySeq, n = names();
  const busy = setTimeout(() => status("Drawing…"), 250);
  const [nA, rA, nB, rB] = await Promise.all([getTex(n.nearA), getTex(n.regA), n.nearB ? getTex(n.nearB) : blank, n.regB ? getTex(n.regB) : blank]);
  clearTimeout(busy); status("");
  if (seq !== applySeq) return;
  const nb = n.weekly ? W.near_bounds : [N.x0, N.y0, N.x1, N.y1], rb = n.weekly ? W.region_bounds : [R.x0, R.y0, R.x1, R.y1];
  for (const [m, A, B, b] of [[nearMat, nA, nB, nb], [regionMat, rA, rB, rb]]) {
    m.uniforms.tA.value = A; m.uniforms.tB.value = B; m.uniforms.uBA.value.set(...rel(b));
    m.uniforms.uDiff.value = state.src === "objects" ? 1 : 0;
    m.uniforms.uStyle.value = state.style === "charcoal" ? 1 : 0;
    m.uniforms.uContour.value = $("contours").checked ? 1 : 0;
    m.uniforms.uEx.value = state.ex;
  }
  $("key-h").textContent = state.src === "objects" ? "Shadow added by trees and buildings" : "Share of daylight in shadow";
  $("key-note").textContent = state.src === "objects"
    ? "Percentage points of daylight, beyond what the hills alone cast."
    : "Paper: sun whenever the sun is up. Black: shadow nearly all day.";
  render();
  lastPick && pick(lastPick);
}

// ---------- controls
const fmtDate = (doy) => new Date(Date.UTC(2026, 0, doy)).toLocaleDateString("en-CA", { month: "short", day: "numeric", timeZone: "UTC" });
function syncDate() {
  $("date-out").textContent = fmtDate(state.doy);
  $("date").setAttribute("aria-valuetext", fmtDate(state.doy));
}
document.querySelectorAll("input[name=when]").forEach((el) => el.addEventListener("change", () => { state.when = el.value; if (state.when !== "date") stopPlay(); apply(); }));
document.querySelectorAll("input[name=src]").forEach((el) => el.addEventListener("change", () => { state.src = el.value; apply(); }));
document.querySelectorAll("input[name=style]").forEach((el) => el.addEventListener("change", () => { state.style = el.value; apply(); }));
$("contours").addEventListener("change", apply);
$("names").addEventListener("change", render);
$("date").addEventListener("input", () => {
  state.doy = +$("date").value; syncDate();
  if (state.when !== "date") { state.when = "date"; document.querySelector("input[name=when][value=date]").checked = true; }
  apply();
});
$("ex").addEventListener("input", () => { state.ex = +$("ex").value; $("ex-out").textContent = state.ex + "×"; apply(); });
$("ex-out").textContent = state.ex + "×"; syncDate();
$("toggle").addEventListener("click", () => {
  const p = $("panel"); p.classList.toggle("closed"); $("toggle").setAttribute("aria-expanded", !p.classList.contains("closed"));
});
let playing = null;
let wantPlay = false;
function stopPlay() {
  wantPlay = false;
  if (playing) { clearInterval(playing); playing = null; }
  $("play").setAttribute("aria-pressed", "false"); $("play").textContent = "Play the year";
}
$("play").addEventListener("click", async () => {
  if (wantPlay) { stopPlay(); return; }
  wantPlay = true;
  state.when = "date"; document.querySelector("input[name=when][value=date]").checked = true;
  $("play").setAttribute("aria-pressed", "true"); $("play").textContent = "Pause";
  status("Loading the year…");
  const n = names();
  await Promise.all([n.nearA, n.regA, n.nearB, n.regB].filter(Boolean).map((k) => loadBasis(k.slice(3))));   // only the stacks this view draws
  status("");
  if (!wantPlay || playing) return;                                              // paused while loading
  playing = setInterval(() => { state.doy = ((state.doy + 1) % 365) + 1; $("date").value = state.doy; syncDate(); apply(); }, reduceMotion ? 700 : 100);
});

// ---------- views
const VIEWS = { // [camera east, height, north] and target, relative to the LiDAR centre
  town: [[1800, 2600, 5200], [0, 120, -300]],
  valley: [[-2000, 9000, 19000], [0, 200, -1500]],
  south: [[1500, 3400, -11000], [0, 200, 1500]],
  top: [[0, 26000, -10], [0, 0, 0]],
};
function view(k, instant) {
  const [c, t] = VIEWS[k];
  camera.position.set(c[0], c[1], -c[2]); controls.target.set(t[0], t[1], -t[2]); controls.update(); render();
}
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => view(b.dataset.view)));

// ---------- height lookup and picking (CPU ray march against the 10 m and 90 m grids)
function bilin(arr, w, h, fx, fy, off = 0) {
  if (fx < 0 || fy < 0 || fx > w - 1 || fy > h - 1) return NaN;
  const c0 = Math.min(Math.floor(fx), w - 2), r0 = Math.min(Math.floor(fy), h - 2), a = fx - c0, b = fy - r0;
  const v = (r, c) => arr[off + r * w + c];
  return (v(r0, c0) * (1 - a) + v(r0, c0 + 1) * a) * (1 - b) + (v(r0 + 1, c0) * (1 - a) + v(r0 + 1, c0 + 1) * a) * b;
}
const inNear = (e, n) => e > N.x0 && e < N.x1 && n > N.y0 && n < N.y1;
function heightAt(e, n) { // metres above Z0, as the meshes draw it (blend included)
  const zr = regionHeight(e, n);
  if (!inNear(e, n)) return zr;
  const z = bilin(nearH, N.geom_w, N.geom_h, (e - N.x0) / N.geom_cell - 0.5, (N.y1 - n) / N.geom_cell - 0.5) * meta.zscale;
  if (Number.isNaN(z)) return zr;
  const d = Math.min(e - N.x0, N.x1 - e, n - N.y0, N.y1 - n);
  if (d >= BLEND || Number.isNaN(zr)) return z;
  const t = Math.max(0, d / BLEND), wgt = t * t * (3 - 2 * t);
  return zr + (z - zr) * wgt;
}
const ray = new THREE.Raycaster();
function groundHit(ndc) {
  ray.setFromCamera(ndc, camera);
  const o = ray.ray.origin, d = ray.ray.direction;
  let prev = 0, step = 25;
  for (let t = 0; t < 120000; t += step) {
    const p = o.clone().addScaledVector(d, t), e = p.x + CX, n = -p.z + CY, h = heightAt(e, n);
    if (Number.isNaN(h)) { if (t > 2000) return null; prev = t; continue; }
    if (p.y <= h * state.ex) { // refine between prev and t
      let lo = prev, hi = t;
      for (let i = 0; i < 18; i++) {
        const m = (lo + hi) / 2, q = o.clone().addScaledVector(d, m);
        if (q.y <= heightAt(q.x + CX, -q.z + CY) * state.ex) hi = m; else lo = m;
      }
      const q = o.clone().addScaledVector(d, hi);
      return { e: q.x + CX, n: -q.z + CY };
    }
    prev = t; step = Math.min(250, 25 + t * 0.004);
  }
  return null;
}
const HOURS = meta.daylight_hours_year;
function readout(e, n) {
  const pct = (b) => Math.round((b / 255) * 100);
  if (inNear(e, n)) {
    const w = N.geom_w, h = N.geom_h, c = Math.floor((e - N.x0) / N.geom_cell), r = Math.floor((N.y1 - n) / N.geom_cell);
    if (c < 0 || r < 0 || c >= w || r >= h) return null;
    const L = (i) => nearRo[i * w * h + r * w + c];
    return { src: L(6) ? "gap in the LiDAR, filled from GEM-15 at 15 m" : "LiDAR surface, 2 m", elev: L(7) * 4 + meta.z0,
      all: [pct(L(0)), pct(L(1)), pct(L(2))], hills: [pct(L(3)), pct(L(4)), pct(L(5))] };
  }
  const w = R.geom_w, h = R.geom_h, c = Math.floor((e - R.x0) / R.geom_cell), r = Math.floor((R.y1 - n) / R.geom_cell);
  if (c < 0 || r < 0 || c >= w || r >= h) return null;
  const L = (i) => regionRo[i * w * h + r * w + c];
  return { src: "GEM-15 surface, 15 m (forest from its DSM)", elev: L(6) * 8 + meta.z0,
    all: [pct(L(0)), pct(L(1)), pct(L(2))], hills: [pct(L(3)), pct(L(4)), pct(L(5))] };
}
const bar = (p) => `<span class="bar" style="width:${Math.round(p * 0.6)}px"></span>`;
let lastPick = null;
function pick(ndc) {
  lastPick = ndc;
  const hit = groundHit(ndc), ro = hit && readout(hit.e, hit.n);
  if (!ro) { $("info").innerHTML = `<p class="note">Point at the ground to read it.</p>`; return; }
  const sun = Math.round(((100 - ro.all[0]) / 100) * HOURS / 10) * 10;
  $("info").innerHTML = `<table>
    <tr><td colspan="3"><b>${Math.round(ro.elev)} m</b> · ${ro.src}</td></tr>
    <tr><td>In shadow</td><td class="n">all</td><td class="n">hills alone</td></tr>
    <tr><td>Year</td><td class="n">${ro.all[0]}% ${bar(ro.all[0])}</td><td class="n">${ro.hills[0]}%</td></tr>
    <tr><td>December</td><td class="n">${ro.all[1]}% ${bar(ro.all[1])}</td><td class="n">${ro.hills[1]}%</td></tr>
    <tr><td>June</td><td class="n">${ro.all[2]}% ${bar(ro.all[2])}</td><td class="n">${ro.hills[2]}%</td></tr>
  </table><p class="note">About ${sun.toLocaleString("en-CA")} hours of direct sun a year, of ${HOURS.toLocaleString("en-CA")} with the sun up. Values are 10 m (LiDAR) or 90 m means.</p>`;
}
const ndcOf = (ev) => { const b = renderer.domElement.getBoundingClientRect(); return new THREE.Vector2(((ev.clientX - b.left) / b.width) * 2 - 1, -((ev.clientY - b.top) / b.height) * 2 + 1); };
let pickPending = null;
renderer.domElement.addEventListener("pointermove", (ev) => {
  if (ev.buttons) return;
  const v = ndcOf(ev);
  if (!pickPending) pickPending = requestAnimationFrame(() => { pickPending = null; pick(v); });
});
renderer.domElement.addEventListener("click", (ev) => pick(ndcOf(ev)));

// ---------- names
const labelEls = labels.map((l) => {
  const s = document.createElement("span"); s.className = l.kind; s.textContent = l.name; $("labels").appendChild(s);
  return { l, s, h: null };
});
const v3 = new THREE.Vector3();
function placeLabels() {
  const show = $("names").checked, W2 = renderer.domElement.clientWidth / 2, H2 = renderer.domElement.clientHeight / 2;
  for (const o of labelEls) {
    if (o.h === null) o.h = heightAt(o.l.x, o.l.y);
    v3.set(o.l.x - CX, (o.h || 0) * state.ex + 25, -(o.l.y - CY)).project(camera);
    const vis = show && v3.z < 1 && Math.abs(v3.x) < 1.05 && Math.abs(v3.y) < 1.05;
    o.s.style.display = vis ? "" : "none";
    if (vis) { o.s.style.left = `${(v3.x + 1) * W2}px`; o.s.style.top = `${(1 - v3.y) * H2}px`; }
  }
  const dir = new THREE.Vector3(); camera.getWorldDirection(dir);
  $("needle").setAttribute("transform", `rotate(${(Math.atan2(dir.x, -dir.z) * -180) / Math.PI})`);
}

// ---------- render loop (on demand)
let frame = null;
function render() { if (!frame) frame = requestAnimationFrame(() => { frame = null; controls.update(); renderer.render(scene, camera); placeLabels(); }); }
controls.addEventListener("change", render);
function resize() { const w = innerWidth, h = innerHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); render(); }
addEventListener("resize", resize); resize();
const q = new URLSearchParams(location.search);
view(VIEWS[q.get("view")] ? q.get("view") : "town");
const ALLOWED = { when: ["year", "dec", "jun", "date"], src: ["all", "hills", "objects"], style: ["grey", "charcoal"] };
for (const [k, ok] of Object.entries(ALLOWED)) {
  const v = q.get(k);
  if (!ok.includes(v)) continue;
  state[k] = v;
  const el = document.querySelector(`input[name=${k}][value=${v}]`); if (el) el.checked = true;
}
const qd = Math.round(Number(q.get("doy")));
if (qd >= 1 && qd <= 365) { state.doy = qd; $("date").value = state.doy; syncDate(); }
await apply();
status("");
window.__day17ready = true;
