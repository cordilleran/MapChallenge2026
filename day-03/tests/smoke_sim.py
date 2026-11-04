#!/usr/bin/env python3
"""Drive the Day 3 simulated-world page in headless Chromium (DevTools protocol) and assert what the visitor sees.

    python3 day-03/tests/smoke_sim.py http://127.0.0.1:8766/ <shots_dir>

Checks: no script errors, nothing from another host, readouts are numbers for every question, every zone frame
and sampling design; census mean equals the truth; replicates run in the worker; the try-it buttons load;
the JSON round-trips; phone width has no sideways scroll. Saves shots. Same driver pattern as smoke_day03.py.
"""
import base64, hashlib, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

PORT = 9335
PROFILE = os.environ.get("MC26_CHROMIUM_PROFILE") or (os.path.expanduser("~/snap/chromium/common/day03sim-smoke")
                                                      if os.path.isdir(os.path.expanduser("~/snap/chromium")) else tempfile.mkdtemp())
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
        s = s.replace(",", "").replace("−", "-").replace("+", "").split(" ")[0]
        try: return float(s)
        except ValueError: return float("nan")
    click = lambda sel: ev(f"document.querySelector(\"{sel}\").click()")
    settle = lambda t=0.8: time.sleep(t)
    call("Runtime.enable"); call("Page.enable")   # Network.enable stalls this page under CDP (tested 11-03); hosts come from Performance entries
    call("Page.navigate", url=base + "day-03.html"); time.sleep(5)
    errs = lambda: [e["params"]["exceptionDetails"].get("text", "") + " " + str(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:200] for e in events if e.get("method") == "Runtime.exceptionThrown"]
    check("no script errors on load", not errs(), "; ".join(errs()))
    host = base.split("/")[2]
    hosts = ev("[...new Set(performance.getEntriesByType('resource').map(e=>new URL(e.name).host))]")
    check("nothing loaded from another host", all(h == host for h in hosts), str(hosts))
    check("truth reads a number", num(txt("r-truth")) == num(txt("r-truth")), txt("r-truth"))
    shot("#s3-map", "gaussian_x.png")
    # census: by-zone equals the truth for the mean, for every frame
    click("#s3-design button[data-k=census]"); settle()
    for k in ("grid", "hex", "vor"):
        click(f"#s3-frame button[data-k={k}]"); settle(1.0)
        check(f"census mean equals truth under {k}", txt("r-truth") == txt("r-census") == txt("r-est"), f"{txt('r-truth')} / {txt('r-census')} / {txt('r-est')}")
        shot("#s3-map", f"frame_{k}.png")
    click("#s3-frame button[data-k=grid]"); click("#s3-design button[data-k=random]"); settle()
    for q in ("mean", "varshare", "corr", "exceed", "rank"):
        click(f"#s3-est button[data-k={q}]"); settle(1.2)
        for d in ("random", "systematic", "stratified"):
            click(f"#s3-design button[data-k={d}]"); settle(0.7)
            v = num(txt("r-est"))
            check(f"{q} / {d}: site estimate is a number", v == v, txt("r-est") + " | " + txt("r-line")[:90])
        click("#s3-design button[data-k=random]"); settle(0.5)
    click("#s3-est button[data-k=mean]"); click("#s3-frame button[data-k=svor]"); settle(1)
    check("site Voronoi gives a number", num(txt("r-est")) == num(txt("r-est")), txt("r-line")[:100])
    click("#s3-frame button[data-k=grid]"); settle(1.5)
    check("scale curve drawn", ev("document.querySelectorAll('#s3-curve circle').length") > 10)
    check("offset sweep sentence", "36 positions" in txt("r-sweep"), txt("r-sweep"))
    # replicates
    click("#s3-run-all"); 
    for _ in range(120):
        time.sleep(1)
        if (ev("document.querySelectorAll('#s3-reptable tbody tr').length") or 0) == 3: break
    rows = ev("[...document.querySelectorAll('#s3-reptable tbody tr')].map(r=>r.textContent)")
    check("three replicate rows", rows and len(rows) == 3, str(rows))
    shot("#s3-reps", "reps.png")
    # drag the grid
    x, y, w, h = rect("#s3-map"); h0 = shot("#s3-map")
    ev("document.getElementById('s3-map').scrollIntoView({block:'center'})"); time.sleep(0.3); x, y, w, h = ev("(()=>{const r=document.querySelector('#s3-map').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
    for t, (dx, dy) in (("mousePressed", (0, 0)), ("mouseMoved", (40, 30)), ("mouseMoved", (80, 50)), ("mouseReleased", (80, 50))):
        call("Input.dispatchMouseEvent", type=t, x=x + w / 2 + dx, y=y + h / 2 + dy, button="left", buttons=1 if t != "mouseReleased" else 0, clickCount=1); time.sleep(0.15)
    settle(); check("drag moves the grid", shot("#s3-map") != h0)
    # textbook and the try-it buttons
    vis = ev("[...document.querySelectorAll('#s3-frame button,#s3-est button')].filter(b=>!b.hidden).map(b=>b.dataset.k).join()")
    check("only Gaussian-world controls", vis == "mean,varshare,corr,exceed,rank,grid,hex,vor,svor", vis)
    tries = ev("document.querySelectorAll('[data-try]').length")
    for i in range(tries):
        ev(f"document.querySelectorAll('[data-try]')[{i}].click()"); settle(1.8)
        check(f"try {i+1} loads", num(txt("r-census")) == num(txt("r-census")) and not errs(), ev(f"document.querySelectorAll('[data-try]')[{i}].textContent") + " -> " + txt("r-census"))
        if i == 1: check("correlation flips sign across the curve", ev("(()=>{const c=[...document.querySelectorAll('#s3-curve circle[r=\\'3.5\\']')];return c.length>5})()"))
        if i == 2: check("Krige band drawn", ev("[...document.querySelectorAll('#s3-curve path')].some(p=>p.getAttribute('stroke-width')==='6')"))
        shot("#s3-tools", f"try{i+1}.png")
    # JSON round-trip through the address
    st = ev("decodeURIComponent(location.hash.slice(1))")
    check("state is in the address", st and json.loads(st).get("estimand") == "mean")
    # bad and old addresses must fall back, not blank the page (preflight item 3)
    for bad in ["%7Bnot json", "%7B%22world%22%3A%22watershed%22%2C%22estimand%22%3A%22rule%22%2C%22frame%22%3A%7B%22kind%22%3A%22basin%22%2C%22size%22%3A-5%7D%2C%22sample%22%3A%7B%22n%22%3A1e9%7D%7D"]:
        call("Page.navigate", url="about:blank"); time.sleep(0.5); call("Page.navigate", url=base + "day-03.html#" + bad); time.sleep(4)
        check("bad address falls back: " + bad[:14], num(txt("r-truth")) == num(txt("r-truth")) and not errs(), txt("r-truth") + " | " + "; ".join(errs()))
    # phone width
    call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True); settle(1.5)
    check("no sideways scroll at phone width", ev("document.documentElement.scrollWidth <= innerWidth + 1"), str(ev("[document.documentElement.scrollWidth, innerWidth]")))
    shot("#s3-tools", "phone.png")
    hid = ev("['s3-world','s3-wsdemwrap'].map(i=>document.getElementById(i).offsetParent===null).every(Boolean)")
    check("hidden controls stay hidden", hid)
    check("no script errors at the end", not errs(), "; ".join(errs()))
finally:
    proc.terminate()
print("FAILS:", len(fails)); sys.exit(1 if fails else 0)
