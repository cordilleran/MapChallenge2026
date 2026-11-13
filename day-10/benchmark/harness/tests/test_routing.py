"""Routing checks on surfaces with known answers: a tilted plane and a cone."""
import numpy as np
import routing

def test_plane_area_grows_downslope():
    ny, nx, dx = 40, 30, 2.0
    z = np.add.outer(np.linspace(10, 0, ny), np.zeros(nx))
    r = routing.route(z, ["bottom"], dx)
    rows = r["area"].mean(axis=1) / (dx * dx)          # cells draining through each row cell
    assert np.allclose(rows[:-1], np.arange(1, ny)), rows[:5]
    assert np.allclose(r["slope"][:-1], 10 / (ny - 1) / dx)

def test_pit_is_filled_and_drains():
    z = np.add.outer(np.linspace(10, 0, 20), np.zeros(20)); z[8, 10] -= 3
    r = routing.route(z, ["south"], 1.0)
    spill = z[9, 9:12].min()                              # lowest neighbour downslope
    assert r["filled"][8, 10] >= spill
    assert (r["rec"].reshape(z.shape)[:-1] >= 0).all()   # everything above the outlet row drains

def test_cone_total_area():
    n = 41; y, x = np.mgrid[:n, :n]; z = 30 - np.hypot(y - 20, x - 20)
    out = np.zeros((n, n), bool); out[[0, -1], :] = True; out[:, [0, -1]] = True
    f, _ = routing.fill(z, out); rec, _ = routing.d8(f, out, 1.0)
    a = routing.accumulate_d8(rec, f, np.ones_like(z))
    assert np.isclose(a[out].sum(), n * n)                 # every cell reaches an outlet once
    m = routing.accumulate_mfd(f, out, 1.0, np.ones_like(z))
    assert np.isclose(m[out].sum(), n * n)
