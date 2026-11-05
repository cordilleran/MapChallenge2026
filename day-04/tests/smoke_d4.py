#!/usr/bin/env python3
"""Drive the Day 4 clusters page in headless Chromium (DevTools protocol) and assert what the visitor sees.

    python3 day-04/tests/smoke_d4.py http://127.0.0.1:8767/ <shots_dir>

Checks: no script errors, nothing from another host, the map draws, the DBSCAN sliders change the cell count,
the Knox heat map draws and the frame toggle changes it, the zoom band switch, the parallax toggle, the time window
and play, pan and zoom, the try-it buttons, bad addresses fall back, phone width has no sideways scroll.
Saves shots (light and dark) and prints timings. Same driver pattern as day-03/tests/smoke_sim.py.
"""
import base64, hashlib, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

PORT = 9337
TMP = None
PROFILE = os.environ.get("MC26_CHROMIUM_PROFILE")
if not PROFILE:
    if os.path.isdir(os.path.expanduser("~/snap/chromium")):
        PROFILE = os.path.expanduser("~/snap/chromium/common/day04-smoke")
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
    sig = lambda: ev("document.getElementById('d4-heat').dataset.sig")
    nrect = lambda: ev("document.querySelectorAll('#d4-heat rect').length")
    cells = lambda: num(txt("r4-cells"))
    errs = lambda: [e["params"]["exceptionDetails"].get("text", "") + " " + str(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:200] for e in events if e.get("method") == "Runtime.exceptionThrown"]
    ready = "document.getElementById('d4-heat').dataset.sig && !/^[–]?$/.test(document.getElementById('r4-cells').textContent) && document.getElementById('r4-cells').textContent!=='–'"
    call("Runtime.enable"); call("Page.enable")   # Network.enable stalls headless pages under CDP (tested 11-03); hosts come from Performance entries
    call("Page.navigate", url=base + "day-04.html")
    ok = wait(ready, 40)
    check("page ready (clusters and Knox surface drawn)", ok)
    check("no script errors on load", not errs(), "; ".join(errs()))
    host = base.split("/")[2]
    hosts = ev("[...new Set(performance.getEntriesByType('resource').map(e=>new URL(e.name).host))]")
    check("nothing loaded from another host", all(h == host for h in hosts), str(hosts))
    tm = ev("({first: document.getElementById('d4-tools').dataset.firstMapMs, knox: document.getElementById('d4-tools').dataset.knoxMs})")
    print("TIMING first map (ms since navigation):", tm["first"], " knox recompute 39 perms (ms):", tm["knox"])
    # the map draws
    stats = ev("(()=>{const c=document.getElementById('d4-map'),g=c.getContext('2d'),d=g.getImageData(0,0,c.width,c.height).data;const s=new Set();let non=0;for(let i=0;i<d.length;i+=4*7){const k=d[i]+','+d[i+1]+','+d[i+2];s.add(k);if(!(d[i]===12&&d[i+1]===24&&d[i+2]===34))non++}return [s.size,non,c.width,c.height]})()")
    check("map draws (many colours, not blank)", stats[0] > 30 and stats[1] > 2000, str(stats))
    check("cell count is a number above zero", cells() > 0, txt("r4-cells"))
    check("flashes in view is a number", num(txt("r4-view")) > 0, txt("r4-view"))
    check("auto band is cells when zoomed out", ev("document.getElementById('d4-map').dataset.band") == "cells")
    ev("document.getElementById('d4-map').scrollIntoView({block:'center'})"); time.sleep(0.3)
    h_cells = shot("#d4-map", "map_cells.png")
    # DBSCAN sliders change the cell count
    c0 = cells()
    setrange("d4-eps", 25); check("eps slider changes the cell count", wait(f"document.getElementById('r4-cells').textContent!=='{txt('r4-cells')}'"), f"{c0:.0f} -> {txt('r4-cells')}")
    c1 = cells(); check("a generous radius gives fewer cells", c1 < c0, f"{c0:.0f} -> {c1:.0f}")
    check("k-distance plot has the eps line", "eps 25" in (ev("document.getElementById('d4-kd').textContent") or ""))
    setrange("d4-eps", 3); setrange("d4-mp", 20)
    check("strict settings give mostly noise", wait("parseFloat(document.getElementById('r4-noise').textContent)>80"), txt("r4-noise"))
    setrange("d4-eps", 8); setrange("d4-mp", 6); setrange("d4-ts", 2)
    check("time scale slider changes the cell count", wait(f"document.getElementById('r4-cells').textContent!=='{txt('r4-cells')}'"), txt("r4-cells"))
    setrange("d4-ts", 1); wait(f"Math.abs(parseFloat(document.getElementById('r4-cells').textContent)-{c0})<0.5"); settle(0.3)
    check("back to the first settings gives the first count", cells() == c0, f"{cells():.0f} vs {c0:.0f}")
    # Knox heat map
    check("heat map drawn", nrect() > 100, str(nrect()))
    s_era = sig()
    ev("document.getElementById('d4-heat').scrollIntoView({block:'center'})"); time.sleep(0.3)
    hx, hy, hw, hh = ev("(()=>{const r=document.querySelector('#d4-heat').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
    call("Input.dispatchMouseEvent", type="mouseMoved", x=hx + hw * 0.3, y=hy + hh * 0.5); settle(0.3)
    check("heat map tooltip on hover", ev("!document.getElementById('d4-tip').hidden") and "observed" in txt("d4-tip"), txt("d4-tip")[:60])
    click("#d4-frame button[data-k=ground]")
    check("frame toggle changes the heat map", wait(f"document.getElementById('d4-heat').dataset.frame==='ground' && document.getElementById('d4-heat').dataset.sig!=='{s_era}'"), f"{s_era} -> {sig()}")
    s_ground = sig()
    shot("#d4-heat", "heat_ground.png")
    click("#d4-frame button[data-k=era5]"); wait("document.getElementById('d4-heat').dataset.frame==='era5'")
    check("ERA5 frame restores the first surface", sig() == s_era)
    shot("#d4-heat", "heat_era5.png")
    check("heat map dots are off by default", ev("document.querySelectorAll('#d4-heat circle').length") == 0)
    click("#d4-dots"); settle(0.3)
    check("dots checkbox marks cells and counts them", ev("document.querySelectorAll('#d4-heat circle').length") > 0 and "marked" in txt("d4-dots-n"), txt("d4-dots-n"))
    click("#d4-dots"); settle(0.2)
    rows = ev("[...document.querySelectorAll('#d4-conc tbody tr')].map(r=>r.textContent)")
    print("CONC rows:", rows)
    check("table lists ground and ERA5", rows and len(rows) >= 2, str(rows))
    click("#d4-frame button[data-k=fit]")
    check("self-fitted frame computes", wait("document.getElementById('d4-heat').dataset.frame==='fit'"), txt("d4-v-fit"))
    shot("#d4-heat", "heat_fit.png")
    click("#d4-frame button[data-k=custom]"); settle(0.4)
    check("custom frame shows its sliders", ev("!document.getElementById('d4-custom').hidden"))
    setrange("d4-cu", 30); check("custom frame computes", wait("document.getElementById('d4-heat').dataset.frame==='custom'"))
    click("#d4-frame button[data-k=era5]"); wait("document.getElementById('d4-heat').dataset.frame==='era5'")
    click("#d4-nperm button[data-k='99']")
    check("99 permutations run", wait("document.getElementById('d4-heat').dataset.nperm==='99'", 60), txt("d4-prog"))
    print("TIMING knox 99 perms (ms):", ev("document.getElementById('d4-tools').dataset.knoxMs"))
    click("#d4-nperm button[data-k='39']"); wait("document.getElementById('d4-heat').dataset.nperm==='39'")
    # zoom band switch
    click("#d4-band button[data-k=flashes]"); settle(0.5)
    check("band switch to flashes", ev("document.getElementById('d4-map').dataset.band") == "flashes")
    check("flashes band draws differently from cells", shot("#d4-map", "map_flashes_wide.png") != h_cells)
    click("#d4-band button[data-k=auto]"); settle(0.3)
    # time window and play
    click("#d4-win button[data-k='30']"); settle(0.6)
    v30 = num(txt("r4-view")); check("30 minute window shows fewer flashes", 0 < v30 < 6000, txt("r4-view"))
    check("clock names UTC and Pacific", "UTC" in txt("d4-clock") and "Pacific" in txt("d4-clock"), txt("d4-clock"))
    t0 = ev("document.getElementById('d4-t').value"); click("#d4-play"); settle(1.5)
    t1 = ev("document.getElementById('d4-t').value"); click("#d4-play")
    check("play advances the window", float(t1) > float(t0), f"{t0} -> {t1}")
    check("play button back to Play", txt("d4-play") == "Play")
    # parallax
    h_np = shot("#d4-map"); click("#d4-par"); settle(0.5)
    check("parallax toggle changes the map", shot("#d4-map", "map_parallax.png") != h_np)
    check("parallax note shown", ev("!document.getElementById('d4-par-note').hidden"))
    click("#d4-par")
    # pan and zoom by wheel and drag
    ev("document.querySelector('#d4-map').scrollIntoView({block:'center'})"); settle(0.4)   # events at an off-screen point hit nothing
    x, y, w, h = ev("(()=>{const r=document.querySelector('#d4-map').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
    hz, hh = shot("#d4-map"), ev("location.hash")
    call("Input.dispatchMouseEvent", type="mouseWheel", x=x + w / 2, y=y + h / 2, deltaX=0, deltaY=-400); settle(0.6)
    settle(0.6); check("wheel zooms", ev("location.hash") != hh or shot("#d4-map") != hz)   # state first: screenshots lag
    hz2, hh2 = shot("#d4-map"), ev("location.hash")
    for t, (dx, dy) in (("mousePressed", (0, 0)), ("mouseMoved", (40, 30)), ("mouseMoved", (90, 60)), ("mouseReleased", (90, 60))):
        call("Input.dispatchMouseEvent", type=t, x=x + w / 2 + dx, y=y + h / 2 + dy, button="left", buttons=1 if t != "mouseReleased" else 0, clickCount=1); time.sleep(0.12)
    settle(0.5); check("drag pans the map", ev("location.hash") != hh2 or shot("#d4-map") != hz2)
    click("#d4-zreset"); settle(0.4)
    # try-it buttons
    tries = ev("document.querySelectorAll('[data-try]').length")
    for i in range(tries):
        ev(f"document.querySelectorAll('[data-try]')[{i}].click()"); settle(0.6)
        wait("!document.getElementById('d4-prog').textContent.startsWith('Permutation')", 30); wait("document.getElementById('d4-cl-note').textContent===''", 15); settle(0.8)
        label = ev(f"document.querySelectorAll('[data-try]')[{i}].textContent")[:60]
        check(f"try {i+1} loads", cells() >= 0 and nrect() > 100 and not errs(), label + " -> cells " + txt("r4-cells") + ", noise " + txt("r4-noise") + ", frame " + str(ev("document.getElementById('d4-heat').dataset.frame")))
        if i == 1: check("generous radius leaves little noise", num(txt("r4-noise")) < 5, txt("r4-noise"))
        if i == 2: check("strict settings leave mostly noise", num(txt("r4-noise")) > 80, txt("r4-noise"))
        if i == 6: check("flashes band for the last try", ev("document.getElementById('d4-map').dataset.band") == "flashes" and ev("document.getElementById('d4-par').checked"))
        if i == 3: check("ground frame for the ridge try", ev("document.getElementById('d4-heat').dataset.frame") == "ground")
        if i == 5: check("fit frame for the circular try", ev("document.getElementById('d4-heat').dataset.frame") == "fit")
        if i == 6: shot("#d4-map", "try7_map.png")
        shot("#d4-tools", f"try{i+1}.png")
    # state in the address
    time.sleep(0.5)
    st = ev("decodeURIComponent(location.hash.slice(1))")
    check("state is in the address", st and json.loads(st).get("band") == "flashes", (st or "")[:80])
    # JSON round-trip
    click("#d4-copy"); settle(0.3); js = ev("document.getElementById('d4-json').value")
    check("JSON box filled", js and json.loads(js).get("parallax") is True)
    ev("document.getElementById('d4-json').value=JSON.stringify({eps:10,minPts:8,frame:'ground'})"); click("#d4-load"); settle(0.8)
    check("load from the box", ev("document.getElementById('d4-eps').value") == "10" and txt("d4-json-note") == "Loaded.", txt("d4-json-note"))
    ev("document.getElementById('d4-json').value='{nope'"); click("#d4-load")
    check("bad JSON in the box is refused", "not valid" in txt("d4-json-note"))
    # bad and odd addresses fall back, not blank the page
    bads = ["%7Bnot json", "%5B1%2C2%5D", "%7B%22eps%22%3A1e9%2C%22minPts%22%3A%22x%22%2C%22frame%22%3A%22warp%22%2C%22win%22%3A7%2C%22view%22%3A%7B%22w%22%3A-5%2C%22cx%22%3A%22q%22%7D%2C%22t%22%3Anull%7D"]
    for bad in bads:
        call("Page.navigate", url="about:blank"); time.sleep(0.5); events.clear(); call("Page.navigate", url=base + "day-04.html#" + bad)
        okb = wait(ready, 40)
        check("bad address falls back: " + bad[:14], okb and not errs() and cells() > 0, txt("r4-cells") + " | " + "; ".join(errs()))
    # theme shots (the page chrome follows the system theme; the panels stay dark)
    call("Emulation.setDeviceMetricsOverride", width=1100, height=1000, deviceScaleFactor=1, mobile=False)
    call("Page.navigate", url="about:blank"); time.sleep(0.4); call("Page.navigate", url=base + "day-04.html"); wait(ready, 40); settle(1.0)
    for scheme in ("light", "dark"):
        call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}]); settle(0.6)
        shot("#d4-tools", f"page_{scheme}.png")
        shot("#d4-cov", f"cov_{scheme}.png")
        body = ev("document.body.getBoundingClientRect().height")
        x0, y0, w0, h0 = rect("body"); d = base64.b64decode(call("Page.captureScreenshot", clip={"x": 0, "y": 0, "width": 1100, "height": h0, "scale": 1}, captureBeyondViewport=True)["result"]["data"])
        with open(os.path.join(shots, f"full_{scheme}.png"), "wb") as fh:
            fh.write(d)
    call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
    # phone width
    call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True); settle(1.5)
    wait("document.getElementById('d4-heat').dataset.sig", 20); settle(1.0)
    check("no sideways scroll at phone width", ev("document.documentElement.scrollWidth <= innerWidth + 1"), str(ev("[document.documentElement.scrollWidth, innerWidth]")))
    wide = ev("[...document.querySelectorAll('#d4-tools *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,5).map(e=>e.tagName+'#'+e.id+'.'+e.className)")
    check("nothing in the tools runs off the phone screen", not wide, str(wide))
    shot("#d4-tools", "phone.png"); shot("#d4-map", "phone_map.png"); shot("#d4-heat", "phone_heat.png")
    ev("document.querySelector('.tries').scrollIntoView()")
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
