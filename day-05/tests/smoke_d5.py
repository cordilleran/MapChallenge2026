#!/usr/bin/env python3
"""Drive the Day 5 sight page in headless Chromium (DevTools protocol) and assert what the visitor sees.

    python3 day-05/tests/smoke_d5.py http://127.0.0.1:8778/ <shots_dir>

Checks: no script errors, nothing from another host, the cumulative viewshed draws and the station toggles and
scenarios change the area as expected, the uncertainty layers (and the area line hides with them), the profile
stays hidden (D95), the station panel (panorama at native height, peak markers, plate 597 with its repeat and
skyline match, peak tooltips inside the panorama and naming the height source), the base layers, the observer
position switch, the text fold-downs (D97), and phone width (no sideways scroll, pager ordinal).
Saves shots (light and dark). Same driver pattern as day-04/tests/smoke_d4.py.
"""
import base64, hashlib, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

PORT = 9337
TMP = None
PROFILE = os.environ.get("MC26_CHROMIUM_PROFILE")
if not PROFILE:
    if os.path.isdir(os.path.expanduser("~/snap/chromium")):
        PROFILE = os.path.expanduser("~/snap/chromium/common/day05-smoke")
    else:
        PROFILE = TMP = tempfile.mkdtemp()
base, shots = sys.argv[1].rstrip("/") + "/", sys.argv[2]
os.makedirs(shots, exist_ok=True)
proc = subprocess.Popen(["chromium", "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                         "--window-size=1200,1000", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
fails = []
def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else "")); (None if ok else fails.append(name))
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json")); break
        except OSError: time.sleep(0.2)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], timeout=120)
    n, events = [0], []
    def call(method, **p):
        n[0] += 1; ws.send(json.dumps({"id": n[0], "method": method, "params": p}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == n[0]: return m
            events.append(m)
    def ev(expr):
        r = call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r["result"]["result"].get("value")
    def rect(sel):
        return ev(f"(()=>{{const r=document.querySelector('{sel}').getBoundingClientRect();return [r.left+scrollX,r.top+scrollY,r.width,r.height]}})()")
    def shot(sel, name=None):
        x, y, w, h = rect(sel)
        d = base64.b64decode(call("Page.captureScreenshot", clip={"x": x, "y": y, "width": w, "height": h, "scale": 1}, captureBeyondViewport=True)["result"]["data"])
        if name:
            with open(os.path.join(shots, name), "wb") as fh: fh.write(d)
        return hashlib.sha1(d, usedforsecurity=False).hexdigest()
    txt = lambda i: ev(f"document.getElementById('{i}').textContent") or ""
    def num(s):
        s = s.replace(",", "").replace("−", "-").replace("%", "").replace("+", "").split(" ")[0]
        try: return float(s)
        except ValueError: return float("nan")
    click = lambda sel: ev(f"document.querySelector(\"{sel}\").click()")
    def setrange(i, v): ev(f"(()=>{{const e=document.getElementById('{i}');e.value='{v}';e.dispatchEvent(new Event('input',{{bubbles:true}}))}})()")
    settle = lambda t=0.8: time.sleep(t)
    def wait(cond, secs=20):
        t0 = time.time()
        while time.time() - t0 < secs:
            if ev(cond): return True
            time.sleep(0.15)
        return False
    errs = lambda: [e["params"]["exceptionDetails"].get("text", "") + " " + str(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:200] for e in events if e.get("method") == "Runtime.exceptionThrown"]
    area = lambda: num(txt("d5-area-val"))
    call("Runtime.enable"); call("Page.enable")
    call("Page.navigate", url=base + "day-05.html")
    ok = wait("document.querySelector('#map .leaflet-image-layer') && !/^[–-]?$/.test(document.getElementById('d5-area-val').textContent.trim())", 40)
    check("page ready (map overlay and area drawn)", ok, txt("d5-area-val"))
    check("no script errors on load", not errs(), "; ".join(errs()))
    hosts = ev("[...new Set(performance.getEntriesByType('resource').map(r=>new URL(r.name).host))]")
    check("nothing loaded from another host", hosts == [ev("location.host")] or set(hosts) <= {ev("location.host")}, str(hosts))
    a6 = area(); check("six stations: area near 594.9 km2", abs(a6 - 594.9) < 25, str(a6))
    shot("#d5-app", "desktop_all.png")
    # one station only
    click("#d5-btn-none"); settle(); click("#d5-stn-btns [data-stn='85']"); settle(1.2)
    a85 = area(); check("Anderson alone: area near 52.7 km2", abs(a85 - 52.7) < 5, str(a85))
    click("#d5-btn-all"); settle(1.2); check("all on again restores the area", abs(area() - a6) < 0.5, str(area()))
    click("#d5-stn-btns [data-stn='84']"); settle(1.2); check("switching Mt Blakiston off lowers the area", area() < a6 - 50, str(area()))
    click("#d5-btn-all"); settle(1.0)
    for sc, lo, hi in (("forest30", 500, 560), ("drone", 600, 5000)):
        click(f"#d5-scenarios [data-scen='{sc}']"); settle(1.5)
        check(f"scenario {sc} area in range", lo < area() < hi, str(area()))
    click("#d5-scenarios [data-scen='main']"); settle(1.0)
    # uncertainty
    for m in ("rmse26", "rmse80", "pos"):
        click(f"[data-mode='{m}']"); settle(1.2)
        check(f"area line hidden with the {m} layer", ev("document.getElementById('d5-area-line').hidden") is True and ev("document.getElementById('d5-area-line').offsetHeight") == 0)
    check("station-position table shows variants", (ev("document.querySelectorAll('#d5-variant-table tr').length") or 0) > 2)
    shot("#d5-uncertainty-section", "uncertainty.png")
    click("[data-mode='cumul']"); settle()
    check("area line back with the cumulative layer", ev("document.getElementById('d5-area-line').offsetHeight") > 0)
    folds = ev("[...document.querySelectorAll('details.d5-fold > summary')].map(s=>s.textContent.trim())") or []
    check("four text fold-downs, closed", len(folds) == 4 and not ev("[...document.querySelectorAll('details.d5-fold')].some(d=>d.open)"), str(folds))
    check("no stray h3 in the text", ev("document.querySelectorAll('.day > h3, .cols h3').length") == 0)
    # profile Lost Mt to Lone Mt
    ev("(()=>{const f=document.getElementById('d5-prof-from'),t=document.getElementById('d5-prof-to');f.value=[...f.options].find(o=>/88|Lost/.test(o.text+o.value)).value;f.dispatchEvent(new Event('change',{bubbles:true}));t.value=[...t.options].find(o=>/89|Lone/.test(o.text+o.value)).value;t.dispatchEvent(new Event('change',{bubbles:true}))})()")
    settle(1.0)
    check("profile drawn", (ev("document.querySelectorAll('#d5-prof-svg path, #d5-prof-svg polyline, #d5-prof-svg polygon').length") or 0) > 1)
    print("     profile summary:", txt("d5-prof-summary")[:200])
    check("profile section hidden for now (D95)", ev("document.getElementById('d5-profile-section').hidden") is True)
    # profile hidden (D95): no screenshot
    # Station panel (D88, D89): repeats shown beside plates; panorama peaks and plates on it.
    click("#d5-stn-select [data-stn='89']"); settle(1.5)
    check("panorama shows at native height", abs((ev("(document.querySelector('#d5-station-panel img[src*=pano_]')||{}).height") or 0) - 370) <= 1, str(ev("(document.querySelector('#d5-station-panel img[src*=pano_]')||{}).height")))
    np_ = ev("document.querySelectorAll('#d5-station-panel .d5-peak-marker, #d5-station-panel [class*=peak]').length") or 0
    check("Lone Mt panorama has peak markers", np_ > 20, str(np_))
    btns = ev("[...document.querySelectorAll('#d5-station-panel button')].filter(b=>/597/.test(b.textContent)).length") or 0
    check("plate 597 is clickable", btns >= 1, str(btns))
    ev("[...document.querySelectorAll('#d5-station-panel button')].find(b=>/597/.test(b.textContent)).click()"); settle(1.5)
    check("plate pair loads (1914 and repeat)", ev("[...document.querySelectorAll('#d5-station-panel img')].filter(i=>/plate597_(1914|repeat)/.test(i.src)&&i.complete&&i.naturalWidth>0).length") == 2)
    check("skyline match notes filled", "TODO" not in (ev("(document.getElementById('d5-match-notes')||{}).textContent") or "TODO"))
    check("thesis not linked in the panel", not ev("[...document.querySelectorAll('#d5-station-panel a')].some(a=>/dspace|1828\\/2481/.test(a.href))"))
    for b in ("satellite", "landcover"):
        ev(f"[...document.querySelectorAll('button')].find(x=>x.dataset && (x.dataset.base==='{b}' || x.dataset.layer==='{b}'))?.click()"); settle(1.0)
        check(f"base layer {b} drawn", ev(f"[...document.querySelectorAll('.leaflet-pane img')].some(i=>/{'s2_viewshed' if b=='satellite' else 'landcover_viewshed'}/.test(i.src)&&i.naturalWidth>0)"))
    # every peak tooltip stays inside the panorama box (GW 11-05: high peaks lost their names)
    bad = ev("""(()=>{const box=document.getElementById('d5-pano-scroll').getBoundingClientRect();let bad=[];
      document.querySelectorAll('#d5-station-panel .pano-peak-btn').forEach(b=>{b.dispatchEvent(new Event('mouseenter'));
      const t=document.getElementById('active-pano-tip'); if(t){const r=t.getBoundingClientRect(); const pr=t.offsetParent.getBoundingClientRect();
      if(t.offsetTop<0||t.offsetTop+t.offsetHeight>document.getElementById('d5-pano-img').height+1) bad.push(b.getAttribute('aria-label'));}
      b.dispatchEvent(new Event('mouseleave'));});return bad.slice(0,5);})()""")
    check("peak tooltips stay inside the panorama", not bad, str(bad))
    tiptxt = ev("""(()=>{const b=document.querySelector('#d5-station-panel .pano-peak-btn');b.dispatchEvent(new Event('mouseenter'));
      const t=document.getElementById('active-pano-tip');const s=t?t.textContent:'';b.dispatchEvent(new Event('mouseleave'));return s;})()""") or ""
    check("peak tooltip names the height source", "height" in tiptxt and ("terrain model" in tiptxt or "published" in tiptxt), tiptxt[:120])
    shot("#d5-station-panel", "panel.png")
    # Observer position (D93): high point changes the area, the panorama and the markers.
    a_st = area()
    click("#d5-pos-btns [data-pos='highpoint']"); settle(2.0)
    a_hp = area()
    check("high point changes the visible area", abs(a_hp - a_st) > 1, f"{a_st} -> {a_hp}")
    check("high point panorama shown", "_hp" in (ev("(document.querySelector('#d5-station-panel img[src*=pano_]')||{}).src") or ""))
    shot("#d5-station-panel", "panel_hp.png")
    click("#d5-pos-btns [data-pos='station']"); settle(2.0)
    check("back to the station point restores the area", abs(area() - a_st) < 0.5, str(area()))
    call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}]); settle(1.0); shot("#d5-app", "desktop_dark.png")
    call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
    call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True); settle(2.0)
    check("phone pager shows the ordinal", " of 6: Station " in (txt("d5-stn-pager-label") or ""), txt("d5-stn-pager-label"))
    check("no sideways scroll at phone width", ev("document.documentElement.scrollWidth <= innerWidth + 1"), str(ev("[document.documentElement.scrollWidth, innerWidth]")))
    wide = ev("[...document.querySelectorAll('#d5-app *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1&&!e.closest('.leaflet-container')&&!e.closest('.d5-pano-scroll, [id*=pano]')}).slice(0,6).map(e=>e.tagName+'#'+e.id+'.'+e.className)")
    check("nothing runs off the phone screen", not wide, str(wide))
    shot("#d5-station-panel", "phone_panel.png"); shot("#map", "phone_map.png")
    check("no script errors at the end", not errs(), "; ".join(errs()))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if TMP:
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
print("FAILS:", len(fails)); sys.exit(1 if fails else 0)
