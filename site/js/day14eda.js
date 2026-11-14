/* Day 14 exploratory charts, drawn as SVG from data/day14/eda.json. Two series throughout: photo (blue) and model (amber). */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function svg(host, w, h) { return el("svg", { viewBox: "0 0 " + w + " " + h, role: "img" }, host); }
  function tip(host) { var t = document.createElement("div"); t.className = "d14-tip"; host.appendChild(t); return t; }
  function legend(host, items) {
    var d = document.createElement("p"); d.className = "d14-legend";
    items.forEach(function (it) { var s = document.createElement("span"); s.innerHTML = '<i style="background:' + it[1] + '"></i>' + it[0]; d.appendChild(s); });
    host.appendChild(d);
  }
  var C = {};
  function isDark() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  // validated with the dataviz palette checker against each theme's ground (CVD and contrast pass)
  function colours() {
    var dk = isDark();
    C = { photo: dk ? "#3f95d0" : "#1f6fb2", model: dk ? "#c47e1c" : "#b76a00", band: css("--line"), grid: css("--line"), muted: css("--muted") };
  }
  function pct(v) { return Math.round(v * 100) + " %"; }

  fetch("data/day14/eda.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    colours(); draw(d);
    function redraw() { colours(); clear(); draw(d); }
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
    new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }).catch(function () {
    var h = document.getElementById("d14eda"); if (h) h.insertAdjacentHTML("afterbegin", '<p class="small">The charts did not load. Reload the page to try again.</p>');
  });
  function clear() { ["cAlong", "cRose", "cHeat", "thumbs", "tGrid", "cDrain"].forEach(function (id) { var e = document.getElementById(id); if (e) e.innerHTML = ""; }); }

  function draw(d) { along(d); roses(d); heat(d); thumbs(d); gridTable(d); drain(d); }

  function axes(s, W, H, m, xs, ys, xl, yl, xt, yt) {
    yt.forEach(function (v) {
      el("line", { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v), stroke: C.grid, "stroke-width": 1 }, s);
      el("text", { x: m.l - 6, y: ys(v) + 4, "text-anchor": "end" }, s).textContent = yl(v);
    });
    xt.forEach(function (v) { el("text", { x: xs(v), y: H - m.b + 16, "text-anchor": "middle" }, s).textContent = xl(v); });
  }
  function path(pts) { return pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(""); }

  function along(d) {
    var host = document.getElementById("cAlong"); if (!host) return;
    var W = 720, H = 240, m = { l: 44, r: 70, t: 10, b: 28 };
    var xe = d.along_x_mm, mids = xe.slice(0, -1).map(function (x, i) { return (x + xe[i + 1]) / 2; });
    var s = svg(host, W, H); s.setAttribute("aria-label", "Line chart of the share of bare enamel along the tub, photo against model");
    var xs = function (x) { return m.l + (x / 1280) * (W - m.l - m.r); }, ys = function (v) { return H - m.b - v * (H - m.t - m.b); };
    axes(s, W, H, m, xs, ys, function (x) { return x / 10 + " cm"; }, pct, [0, 320, 640, 960, 1280], [0, 0.25, 0.5, 0.75, 1]);
    var lo = mids.map(function (_, i) { return Math.min.apply(null, d.sweep.map(function (r) { return r.along[i]; })); });
    var hi = mids.map(function (_, i) { return Math.max.apply(null, d.sweep.map(function (r) { return r.along[i]; })); });
    var band = mids.map(function (x, i) { return [xs(x), ys(hi[i])]; }).concat(mids.slice().reverse().map(function (x, j) { var i = mids.length - 1 - j; return [xs(x), ys(lo[i])]; }));
    el("path", { d: path(band) + "Z", fill: C.band, opacity: 0.55 }, s);
    var series = [["photo", d.photo.along, C.photo], ["model", d.base.along, C.model]];
    series.forEach(function (sr) {
      el("path", { d: path(mids.map(function (x, i) { return [xs(x), ys(sr[1][i])]; })), fill: "none", stroke: sr[2], "stroke-width": 2, "stroke-linejoin": "round" }, s);
      var last = sr[1][sr[1].length - 1];
      el("text", { x: W - m.r + 6, y: ys(last) + 4, class: "lab" }, s).textContent = sr[0];
    });
    el("text", { x: xs(40), y: m.t + 10 }, s).textContent = "drain end";
    var cross = el("line", { y1: m.t, y2: H - m.b, stroke: C.muted, "stroke-width": 1, opacity: 0 }, s);
    var t = tip(host);
    s.addEventListener("pointermove", function (e) {
      var r = s.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
      var i = Math.max(0, Math.min(mids.length - 1, Math.round(((x - m.l) / (W - m.l - m.r)) * 1280 / 40 - 0.5)));
      cross.setAttribute("x1", xs(mids[i])); cross.setAttribute("x2", xs(mids[i])); cross.setAttribute("opacity", 1);
      t.style.display = "block"; t.style.left = Math.min(r.width - 170, (xs(mids[i]) / W) * r.width + 8) + "px"; t.style.top = "8px";
      t.innerHTML = (xe[i] / 10) + "–" + (xe[i + 1] / 10) + " cm<br>photo " + pct(d.photo.along[i]) + "<br>model " + pct(d.base.along[i]) + "<br>sweep " + pct(lo[i]) + "–" + pct(hi[i]);
    });
    s.addEventListener("pointerleave", function () { t.style.display = "none"; cross.setAttribute("opacity", 0); });
    legend(host, [["photo", C.photo], ["model (chosen run)", C.model], ["range of 16 sweep runs", C.band]]);
  }

  function roses(d) {
    var host = document.getElementById("cRose"); if (!host) return;
    Object.keys(d.photo.rose).forEach(function (zone) {
      var box = document.createElement("div"); box.className = "d14-chart"; host.appendChild(box);
      var W = 240, H = 170, m = { l: 34, r: 8, t: 22, b: 26 }, n = 9;
      var s = svg(box, W, H); s.setAttribute("aria-label", "Bar chart of channel angle to the drain, " + zone);
      el("text", { x: m.l, y: 13, class: "lab" }, s).textContent = zone;
      var mx = Math.max.apply(null, d.photo.rose[zone].concat(d.base.rose[zone])) || 1;
      var bw = (W - m.l - m.r) / n, ys = function (v) { return H - m.b - (v / mx) * (H - m.t - m.b); };
      [0, mx / 2].forEach(function (v) { el("line", { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v), stroke: C.grid }, s); });
      var t = tip(box);
      for (var i = 0; i < n; i++) {
        [["photo", C.photo, 0], ["model", C.model, 1]].forEach(function (sr) {
          var v = (sr[0] === "photo" ? d.photo : d.base).rose[zone][i], x = m.l + i * bw + 2 + sr[2] * (bw - 4) / 2, w = (bw - 6) / 2;
          var r = el("rect", { x: x, y: ys(v), width: Math.max(w, 1), height: Math.max(H - m.b - ys(v), 0.5), fill: sr[1], rx: 1.5 }, s);
          var deg = i * 10;
          r.addEventListener("pointerenter", function () { t.style.display = "block"; t.style.left = (x / W * 100) + "%"; t.style.top = "18px"; t.textContent = sr[0] + ", " + deg + "–" + (deg + 10) + "°: " + pct(v); });
          r.addEventListener("pointerleave", function () { t.style.display = "none"; });
        });
      }
      ["0°", "45°", "90°"].forEach(function (lb, k) { el("text", { x: m.l + k * (W - m.l - m.r) / 2, y: H - 8, "text-anchor": k === 0 ? "start" : k === 2 ? "end" : "middle" }, s).textContent = lb; });
    });
    var lg = document.getElementById("cRoseLegend");
    if (!lg) { lg = document.createElement("div"); lg.id = "cRoseLegend"; host.parentNode.insertBefore(lg, host.nextSibling); }
    lg.innerHTML = ""; legend(lg, [["photo", C.photo], ["model", C.model]]);
  }

  function heat(d) {
    var host = document.getElementById("cHeat"); if (!host || !d.sweep.length) return;
    var Ks = Array.from(new Set(d.sweep.map(function (r) { return r.K; }))).sort(function (a, b) { return a - b; });
    var Krs = Array.from(new Set(d.sweep.map(function (r) { return r.Kr; }))).sort(function (a, b) { return a - b; });
    var W = 460, H = 250, m = { l: 96, r: 10, t: 10, b: 44 };
    var s = svg(host, W, H); s.setAttribute("aria-label", "Heat map of misfit to the photo over the two rates");
    var cw = (W - m.l - m.r) / Krs.length, ch = (H - m.t - m.b) / Ks.length;
    var sc = d.sweep.map(function (r) { return r.score.total; }), lo = Math.min.apply(null, sc), hi = Math.max.apply(null, sc);
    var t = tip(host);
    d.sweep.forEach(function (r) {
      var i = Krs.indexOf(r.Kr), j = Ks.indexOf(r.K), f = (r.score.total - lo) / ((hi - lo) || 1);
      var x = m.l + i * cw, y = m.t + (Ks.length - 1 - j) * ch;
      var cell = el("rect", { x: x + 1, y: y + 1, width: cw - 2, height: ch - 2, rx: 3, fill: C.model, "fill-opacity": (0.95 - 0.8 * f).toFixed(2) }, s);
      el("text", { x: x + cw / 2, y: y + ch / 2 + 4, "text-anchor": "middle", class: "lab" }, s).textContent = r.score.total.toFixed(2);
      cell.addEventListener("pointerenter", function () {
        t.style.display = "block"; t.style.left = ((x + cw) / W * 100) + "%"; t.style.top = (y / H * 100) + "%";
        t.innerHTML = "stripping K " + r.K + "<br>channel Kr " + r.Kr + "<br>misfit " + r.score.total + "<br>bare " + pct(r.pale_frac) + " (photo " + pct(d.photo.pale_frac) + ")";
      });
      cell.addEventListener("pointerleave", function () { t.style.display = "none"; });
    });
    Krs.forEach(function (k, i) { el("text", { x: m.l + (i + 0.5) * cw, y: H - m.b + 16, "text-anchor": "middle" }, s).textContent = k; });
    Ks.forEach(function (k, j) { el("text", { x: m.l - 8, y: m.t + (Ks.length - 1 - j + 0.5) * ch + 4, "text-anchor": "end" }, s).textContent = k; });
    el("text", { x: m.l + (W - m.l - m.r) / 2, y: H - 6, "text-anchor": "middle" }, s).textContent = "channel-cutting rate Kr →";
    el("text", { x: 8, y: m.t + 10 }, s).textContent = "stripping K ↑";
  }

  function thumbs(d) {
    var host = document.getElementById("thumbs"); if (!host) return;
    d.equifinal.forEach(function (name) {
      var r = d.sweep.filter(function (x) { return x.name === name; })[0];
      var f = document.createElement("figure");
      f.innerHTML = '<img src="data/day14/thumbs/' + name + '.jpg" alt="Model run with K ' + r.K + " and Kr " + r.Kr + ', mud thickness, dark is thick" loading="lazy" width="320" height="130"><figcaption>K ' + r.K + " · Kr " + r.Kr + " · misfit " + r.score.total + "</figcaption>";
      host.appendChild(f);
    });
  }

  function gridTable(d) {
    var host = document.getElementById("tGrid"); if (!host) return;
    var rows = d.grid.map(function (g) { return "<tr><td>" + g.dx_mm + " mm</td><td class=num>" + pct(g.pale_frac) + "</td><td class=num>" + (g.spacing_mm == null ? "–" : g.spacing_mm + " mm") + "</td><td class=num>" + g.score + "</td></tr>"; }).join("");
    host.innerHTML = "<table><thead><tr><th>Grid</th><th class=num>Bare enamel</th><th class=num>Channel spacing</th><th class=num>Misfit</th></tr></thead><tbody>" + rows +
      "<tr><td>photo</td><td class=num>" + pct(d.photo.pale_frac) + "</td><td class=num>" + d.photo.spacing_mm + " mm</td><td class=num>–</td></tr></tbody></table>";
  }

  function drain(d) {
    var host = document.getElementById("cDrain"); if (!host) return;
    var pts = [[0, 1]].concat(d.base.drawdown.map(function (p) { return [p[0], p[1]]; }));
    var W = 720, H = 200, m = { l: 44, r: 20, t: 10, b: 28 }, T = d.base.t_end_s;
    var s = svg(host, W, H); s.setAttribute("aria-label", "Line chart of the water left in the pool against seconds after the plug was pulled");
    var xs = function (x) { return m.l + (x / T) * (W - m.l - m.r); }, ys = function (v) { return H - m.b - v * (H - m.t - m.b); };
    var xt = []; for (var x = 0; x <= T; x += 10) xt.push(x);
    axes(s, W, H, m, xs, ys, function (x) { return x + " s"; }, pct, xt, [0, 0.5, 1]);
    el("path", { d: path(pts.map(function (p) { return [xs(p[0]), ys(p[1])]; })), fill: "none", stroke: C.model, "stroke-width": 2 }, s);
    var dot = el("circle", { r: 4, fill: C.model, stroke: css("--ground"), "stroke-width": 2, opacity: 0 }, s), t = tip(host);
    s.addEventListener("pointermove", function (e) {
      var r = s.getBoundingClientRect(), x = ((e.clientX - r.left) / r.width * W - m.l) / (W - m.l - m.r) * T;
      var best = pts.reduce(function (a, p) { return Math.abs(p[0] - x) < Math.abs(a[0] - x) ? p : a; }, pts[0]);
      dot.setAttribute("cx", xs(best[0])); dot.setAttribute("cy", ys(best[1])); dot.setAttribute("opacity", 1);
      t.style.display = "block"; t.style.left = Math.min(r.width - 150, xs(best[0]) / W * r.width + 8) + "px"; t.style.top = "8px";
      t.textContent = best[0].toFixed(1) + " s: " + pct(best[1]) + " of the pool left";
    });
    s.addEventListener("pointerleave", function () { t.style.display = "none"; dot.setAttribute("opacity", 0); });
  }
})();
