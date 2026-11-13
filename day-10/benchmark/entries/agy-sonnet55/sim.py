#!/usr/bin/env python3
"""Dryland hillslope erosion / deposition teaching simulation.

Run:  python3 sim.py --seed 42 --out OUTDIR

Processes (all coupled through elevation z):
  1. Linear hillslope creep  dz/dt = div(Kc(V) grad z)
  2. Overland-flow erosion   E = Ke(V) * qw^0.5 * S  per storm, qw = routed runoff
     volume per unit contour width; sediment is routed downslope (multiple-flow
     direction) and re-deposited with a transport-length (settling) law.
  3. Random storms: Poisson arrivals, exponential depths, infiltration-excess runoff.
  4. Patchy vegetation: reduces erodibility, raises infiltration, speeds creep a little.
Boundary: bottom edge open (sediment leaves and is counted); other edges closed.
"""
import argparse, base64, json, os, time
import numpy as np
from scipy import ndimage, sparse
from scipy.sparse.linalg import spsolve

# ----------------------------------------------------------------- parameters
NY, NX = 128, 128
DX = 5.0                    # m
N_STORMS = 1500             # one model step per storm
STORMS_PER_YEAR = 10.0      # erosive storms / yr
MEAN_STORM_MM = 14.0        # mean storm depth (exponential), mm
KC = 0.003                  # m2/yr creep diffusivity (typical 1e-3..1e-2)
KE = 0.010                  # erosion coefficient, m per (m * unit slope) ^ per storm
M_EXP = 0.5                 # discharge exponent
MFD_P = 1.1                 # multiple-flow-direction slope exponent
ELL_C, Q_REF, S_REF = 60.0, 1.0, 0.1   # transport (settling) length law
IC_BARE, IC_VEG = 6.0, 20.0  # infiltration capacity per storm, mm
VEG_COVER = 0.35
N_FRAMES = 9

NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
DIST = np.array([np.hypot(a, b) for a, b in NB]) * DX


def make_terrain(rng):
    y = (np.arange(NY) + 0.5) * DX
    x = (np.arange(NX) + 0.5) * DX
    L = NY * DX
    Lc, S0 = 200.0, 0.30
    prof = S0 * Lc * (np.exp(-y / Lc) - np.exp(-L / Lc))   # concave, high at row 0
    swale = 1.5 * np.exp(-((x - 0.35 * NX * DX) / 60.0) ** 2)[None, :] * (y / L)[:, None]
    z = prof[:, None] - swale
    noise = ndimage.gaussian_filter(rng.standard_normal((NY, NX)), 1.5)
    z += 0.2 * noise / noise.std()
    z += 0.3          # keep base positive-ish
    ghost = z[-1, :] - 0.012 * DX
    return z.astype(np.float64), ghost


def make_vegetation(rng, z):
    n = ndimage.gaussian_filter(rng.standard_normal((NY, NX)), 3.0)
    n = (n - n.mean()) / n.std()
    yy = np.linspace(0, 1, NY)[:, None]
    n = n + 0.6 * yy                       # a bit more cover on the lower, flatter ground
    thr = np.quantile(n, 1 - VEG_COVER)
    v = 1 / (1 + np.exp(-(n - thr) * 3.0))  # soft patches, 0..1
    return v


def route(z, ghost):
    """MFD routing. Returns W (recv<-donor fractions), S_max, sink mask."""
    zp = np.full((NY + 2, NX + 2), np.inf)
    zp[1:-1, 1:-1] = z
    sl = np.zeros((8, NY, NX))
    for k, (di, dj) in enumerate(NB):
        zn = zp[1 + di:NY + 1 + di, 1 + dj:NX + 1 + dj]
        with np.errstate(invalid="ignore"):
            s = (z - zn) / DIST[k]
        s[~np.isfinite(s)] = 0
        sl[k] = np.maximum(s, 0)
    smax = sl.max(0)
    w = sl ** MFD_P
    w[:, -1, :] = 0                         # bottom row drains off-grid
    tot = w.sum(0)
    smax[-1, :] = np.maximum((z[-1, :] - ghost) / DX, 1e-3)
    sink = (tot == 0)
    sink[-1, :] = False
    f = np.divide(w, tot, out=np.zeros_like(w), where=tot > 0)
    idx = np.arange(NY * NX).reshape(NY, NX)
    rows, cols, data = [], [], []
    for k, (di, dj) in enumerate(NB):
        msk = f[k] > 0
        d = idx[msk]
        rows.append(d + di * NX + dj)
        cols.append(d)
        data.append(f[k][msk])
    W = sparse.csc_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))),
                          shape=(NY * NX, NY * NX))
    return W, smax, sink


def runoff_depth_m(P_mm, veg):
    return np.maximum(P_mm - (IC_BARE + (IC_VEG - IC_BARE) * veg), 0.0) / 1000.0


def water(W, rdepth):
    N = NY * NX
    A = sparse.identity(N, format="csc") - W
    return spsolve(A, (rdepth * DX * DX).ravel()).reshape(NY, NX)   # m3 per storm


def creep(z, ghost, kc, dt):
    """Explicit flux-form diffusion; closed sides/top, open bottom. Returns new z, volume exported."""
    nsub = int(np.ceil(dt / (DX * DX / (4.0 * kc.max()) * 0.9)))
    h = dt / nsub
    out = 0.0
    for _ in range(nsub):
        kx = 0.5 * (kc[:, 1:] + kc[:, :-1])
        ky = 0.5 * (kc[1:, :] + kc[:-1, :])
        fx = -kx * (z[:, 1:] - z[:, :-1]) / DX      # flux along +x (m2/yr)
        fy = -ky * (z[1:, :] - z[:-1, :]) / DX      # flux along +y (down the slope)
        fb = -kc[-1, :] * (ghost - z[-1, :]) / DX   # flux out of bottom row
        div = np.zeros_like(z)
        div[:, :-1] += fx; div[:, 1:] -= fx
        div[:-1, :] += fy; div[1:, :] -= fy
        div[-1, :] += fb
        z = z - h * div / DX
        out += h * fb.sum() * DX
    return z, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    z, ghost = make_terrain(rng)
    veg = make_vegetation(rng, z)
    storm_P = rng.exponential(MEAN_STORM_MM, N_STORMS)
    storm_dt = rng.exponential(1.0 / STORMS_PER_YEAR, N_STORMS)

    z0 = z.copy()
    ke = KE * (1 - 0.85 * veg)
    kc = KC * (1 + 0.5 * veg)
    snap_at = set(np.linspace(0, N_STORMS, N_FRAMES).astype(int)[1:])
    frames_z, frames_flow, years_at = [z0.astype(np.float32)], [], [0.0]

    def flow_frame(zz):
        W, _, _ = route(zz, ghost)
        return np.log10(water(W, runoff_depth_m(20.0, veg)) + 1e-3)
    frames_flow.append(flow_frame(z))

    exported = 0.0
    gross_eroded = 0.0
    years = 0.0
    for s in range(N_STORMS):
        dt = storm_dt[s]
        r = runoff_depth_m(storm_P[s], veg)
        if r.max() > 0:
            W, smax, sink = route(z, ghost)
            Aw = water(W, r)
            qw = Aw / DX
            E = ke * np.sqrt(qw) * smax                       # depth this storm (m)
            E = np.minimum(E, 0.5 * smax * DX)                # stability cap
            ell = np.maximum(ELL_C * np.sqrt(np.maximum(qw, 1e-9) / Q_REF)
                             * np.maximum(smax, 0.003) / S_REF, 0.05 * DX)
            lam = DX / ell
            lam[sink] = 1e9
            N = NY * NX
            M = sparse.diags((1 + lam).ravel()) - W
            Qs = spsolve(M.tocsc(), (E * DX * DX).ravel()).reshape(NY, NX)
            Qs[sink] = 0.0                                    # pits trap everything
            Qin = (W @ Qs.ravel()).reshape(NY, NX)
            dz = (Qin - Qs) / (DX * DX)                       # exact cell volume balance
            z = z + dz
            exported += Qs[-1, :].sum()
            gross_eroded += (E * DX * DX).sum()
        z, out_c = creep(z, ghost, kc, dt)
        exported += out_c
        years += dt
        if (s + 1) in snap_at:
            frames_z.append(z.astype(np.float32))
            frames_flow.append(flow_frame(z))
            years_at.append(years)

    dV = (z - z0).sum() * DX * DX
    gross_total = max(gross_eroded + 1e-12, 1e-12)
    mb_err = abs(dV + exported) / max((np.abs(z - z0).sum() * DX * DX), 1e-12) * 100
    d = z - z0
    tele = dict(seed=int(a.seed), grid_shape=[NY, NX], cell_size_m=DX,
                years_simulated=float(years), timesteps=int(N_STORMS),
                open_boundaries=["bottom"], sediment_exported_m3=float(exported),
                uplift_or_baselevel_m3=0.0, max_erosion_m=float(max(0.0, -d.min())),
                max_deposition_m=float(max(0.0, d.max())), mass_balance_error_pct=float(mb_err))
    np.save(os.path.join(a.out, "z_initial.npy"), z0.astype(np.float64))
    np.save(os.path.join(a.out, "z_final.npy"), z.astype(np.float64))
    with open(os.path.join(a.out, "telemetry.json"), "w") as fh:
        json.dump(tele, fh, indent=2)

    vmax = float(np.quantile(np.abs(d), 0.99)) or 0.01
    write_png(os.path.join(a.out, "map.png"), z0, z, veg, vmax)
    write_html(os.path.join(a.out, "map.html"), frames_z, frames_flow, years_at, veg, vmax)
    print(json.dumps(tele, indent=2))
    print("runtime %.1f s" % (time.time() - t0))


# ------------------------------------------------------------------ outputs
def write_png(path, z0, z, veg, vmax):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, LightSource, TwoSlopeNorm
    terr = LinearSegmentedColormap.from_list("dry", ["#8c6a48", "#c49a5f", "#dcc08a", "#ecdcb8", "#f6eede"])
    div = LinearSegmentedColormap.from_list("ero", ["#a8431f", "#e0955a", "#f4efe6", "#6fb3b8", "#1f7a8c"])
    vegc = LinearSegmentedColormap.from_list("veg", ["#e3c88f", "#a8a45a", "#55702f"])
    ext = [0, NX * DX, NY * DX, 0]
    ls = LightSource(azdeg=315, altdeg=40)
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.6), constrained_layout=True)
    rgb = ls.shade(z, terr, blend_mode="soft", vert_exag=2, dx=DX, dy=DX)
    ax[0].imshow(rgb, extent=ext)
    ax[0].set_title("Final terrain (hillshade; top = ridge, bottom = open outlet)")
    im = ax[1].imshow(z - z0, cmap=div, norm=TwoSlopeNorm(0, -vmax, vmax), extent=ext)
    ax[1].set_title("Net change (m): brown = eroded, teal = deposited")
    fig.colorbar(im, ax=ax[1], shrink=0.8)
    im2 = ax[2].imshow(veg, cmap=vegc, vmin=0, vmax=1, extent=ext)
    ax[2].set_title("Vegetation patches (0 bare - 1 dense)")
    fig.colorbar(im2, ax=ax[2], shrink=0.8)
    for x in ax:
        x.set_xlabel("m")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def b64(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode()


HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Dryland hillslope: erosion and deposition</title>
<style>
body{font-family:Georgia,serif;background:#f6eede;color:#3b2f22;margin:0;padding:16px;max-width:1000px;margin:auto}
h1{margin:.2em 0}.row{display:flex;gap:20px;flex-wrap:wrap}
canvas{border:2px solid #8c6a48;image-rendering:auto;background:#fff}
.panel{background:#ecdcb8;padding:10px 14px;border-radius:6px;margin:8px 0}
label{margin-right:12px;white-space:nowrap}input[type=range]{width:300px}
#info{font-family:monospace;min-height:3em}
</style></head><body>
<h1>Where does a dryland hillslope lose and gain soil?</h1>
<p>A simulated hillslope __SIZE__ m across. Ridge at the top, flat plain and open outlet at the bottom. Move the slider to watch time pass (the first frame is the starting surface), and switch layers.</p>
<div class="row"><div>
<canvas id="c" width="640" height="640"></canvas><div id="info">Hover over the map.</div></div>
<div style="flex:1;min-width:280px">
<div class="panel"><b>Time</b><br><input id="t" type="range" min="0" max="__NF__" value="__NF__" step="1"><br><span id="tl"></span></div>
<div class="panel"><b>Layer</b><br>
<label><input type="radio" name="l" value="terrain" checked> Terrain</label>
<label><input type="radio" name="l" value="change"> Change since start</label>
<label><input type="radio" name="l" value="veg"> Vegetation</label>
<label><input type="radio" name="l" value="flow"> Flow (runoff paths)</label><br>
<label><input type="checkbox" id="hs" checked> relief shading</label></div>
<div class="panel"><b>Legend</b><br><canvas id="lg" width="280" height="22" style="border:1px solid #8c6a48"></canvas><div id="lgt"></div></div>
</div></div>
<div class="panel"><h3>What the model assumes</h3><ul>
<li>Soil moves by <b>creep</b>: slow downhill diffusion, faster on steep ground.</li>
<li>Rain comes as <b>random storms</b> (about 10 a year, sizes vary, many small, a few big). Water runs off only when a storm exceeds what the soil can soak up; bare crusted soil soaks up little (about 6 mm), vegetated soil much more (up to 20 mm).</li>
<li>Runoff is routed downhill over the surface, so water gathers in hollows. <b>Erosion</b> grows with steepness and with the amount of water that has collected upslope.</li>
<li>Eroded soil is carried downslope and <b>dropped</b> where flow is weak and the ground flat. No soil is deleted: the sediment leaving the bottom edge is counted (other edges are closed).</li>
<li><b>Vegetation patches</b> protect the surface (about 85% less erodible when dense), so bare gaps are cut and vegetated patches stand as islands.</li>
<li>Elevation changes feed back into flow paths, so channels and fans grow by themselves. The 2D flow model is simplified: no gullies narrower than a cell, no pits filled, no wind.</li></ul>
<h3>Landforms to look for</h3><ul>
<li><b>Rills and small gullies</b> (brown streaks in the Change layer) cut where flow concentrates on the steep upper slope.</li>
<li><b>Vegetation islands</b>: slightly raised patches left between eroded bare ground.</li>
<li><b>Footslope deposition / fans</b> (teal) where the slope flattens and sediment drops.</li>
<li><b>Pits that fill</b>: small hollows trap sediment and show as small teal spots.</li></ul></div>
<script>
const D=__DATA__;
function dec(s,T){const b=atob(s),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return new T(u.buffer);}
const n=D.ny,m=D.nx,Z=D.z.map(s=>dec(s,Float32Array)),F=D.flow.map(s=>dec(s,Uint8Array)),V=dec(D.veg,Uint8Array);
const c=document.getElementById('c'),ctx=c.getContext('2d'),off=document.createElement('canvas');off.width=m;off.height=n;
const octx=off.getContext('2d');
function lerp(st,t){t=Math.max(0,Math.min(1,t));const k=t*(st.length-1),i=Math.min(Math.floor(k),st.length-2),f=k-i;
 return [0,1,2].map(j=>st[i][j]+(st[i+1][j]-st[i][j])*f);}
const H=h=>[1,3,5].map(i=>parseInt(h.substr(i,2),16));
const TERR=["#8c6a48","#c49a5f","#dcc08a","#ecdcb8","#f6eede"].map(H),
 DIV=["#a8431f","#e0955a","#f4efe6","#6fb3b8","#1f7a8c"].map(H),
 VEG=["#e3c88f","#a8a45a","#55702f"].map(H),FLOW=["#f6eede","#9ec5d0","#2a6f97","#123c69"].map(H);
let zmin=1e9,zmax=-1e9;for(const z of Z)for(const v of z){if(v<zmin)zmin=v;if(v>zmax)zmax=v;}
function shade(z){const s=new Float32Array(n*m),az=315*Math.PI/180,al=40*Math.PI/180,ve=2;
 for(let i=0;i<n;i++)for(let j=0;j<m;j++){const i0=Math.max(i-1,0),i1=Math.min(i+1,n-1),j0=Math.max(j-1,0),j1=Math.min(j+1,m-1);
 const dzdx=ve*(z[i*m+j1]-z[i*m+j0])/((j1-j0)*D.dx),dzdy=ve*(z[i1*m+j]-z[i0*m+j])/((i1-i0)*D.dx);
 const sl=Math.atan(Math.hypot(dzdx,dzdy)),asp=Math.atan2(dzdy,-dzdx);
 s[i*m+j]=Math.cos(Math.PI/2-al)*Math.cos(sl)+Math.sin(Math.PI/2-al)*Math.sin(sl)*Math.cos(Math.PI*1.5-az-asp+Math.PI);}
 return s;}
const flowMax=255;
function layer(){return document.querySelector('input[name=l]:checked').value;}
function draw(){const t=+document.getElementById('t').value,L=layer(),hs=document.getElementById('hs').checked;
 const z=Z[t],z0=Z[0],sh=shade(z),img=octx.createImageData(m,n);
 for(let k=0;k<n*m;k++){let col;
  if(L=='terrain')col=lerp(TERR,(z[k]-zmin)/(zmax-zmin));
  else if(L=='change')col=lerp(DIV,0.5+0.5*(z[k]-z0[k])/D.vmax);
  else if(L=='veg')col=lerp(VEG,V[k]/255);
  else col=lerp(FLOW,F[t][k]/flowMax);
  const f=hs?0.55+0.7*Math.max(0,Math.min(1,sh[k])):1;
  for(let j=0;j<3;j++)img.data[4*k+j]=Math.max(0,Math.min(255,col[j]*f));
  img.data[4*k+3]=255;}
 octx.putImageData(img,0,0);ctx.imageSmoothingEnabled=true;ctx.drawImage(off,0,0,640,640);
 document.getElementById('tl').textContent='Year '+D.years[t].toFixed(0)+' (frame '+t+' of '+(Z.length-1)+')';
 legend(L);}
function legend(L){const g=document.getElementById('lg').getContext('2d'),T=document.getElementById('lgt');
 const st={terrain:TERR,change:DIV,veg:VEG,flow:FLOW}[L];
 for(let x=0;x<280;x++){const c=lerp(st,x/279);g.fillStyle='rgb('+c.map(Math.round)+')';g.fillRect(x,0,1,22);}
 T.textContent={terrain:'Low '+zmin.toFixed(1)+' m  ...  high '+zmax.toFixed(1)+' m',
  change:'Brown: lost '+D.vmax.toFixed(2)+' m or more | white: no change | teal: gained '+D.vmax.toFixed(2)+' m or more',
  veg:'Bare ... dense vegetation',flow:'Little runoff ... runoff concentrated (log scale, 20 mm storm)'}[L];}
c.addEventListener('mousemove',e=>{const r=c.getBoundingClientRect(),j=Math.floor((e.clientX-r.left)/r.width*m),i=Math.floor((e.clientY-r.top)/r.height*n);
 if(i<0||j<0||i>=n||j>=m)return;const t=+document.getElementById('t').value,k=i*m+j;
 document.getElementById('info').textContent='x '+(j*D.dx)+' m, y '+(i*D.dx)+' m | elevation '+Z[t][k].toFixed(2)+' m | change '+(Z[t][k]-Z[0][k]).toFixed(3)+' m | vegetation '+Math.round(V[k]/2.55)+'%';});
document.querySelectorAll('input').forEach(e=>e.addEventListener('input',draw));
draw();
</script></body></html>
"""


def write_html(path, fz, ff, years, veg, vmax):
    allf = np.concatenate([f.ravel() for f in ff])
    lo, hi = -3.0, max(allf.max(), -2.0)
    q = [np.clip((f - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8) for f in ff]
    data = dict(ny=NY, nx=NX, dx=DX, vmax=vmax, years=[float(y) for y in years],
                z=[b64(f) for f in fz], flow=[b64(f) for f in q],
                veg=b64((veg * 255).astype(np.uint8)))
    html = (HTML.replace("__DATA__", json.dumps(data)).replace("__NF__", str(len(fz) - 1))
            .replace("__SIZE__", str(int(NX * DX))))
    with open(path, "w") as fh:
        fh.write(html)


if __name__ == "__main__":
    main()
