"""The harness's own flow routing, independent of every entry's.

Priority-flood pit filling with a small gradient (so every cell drains), D8 receivers,
a multiple-flow (MFD) rule, contributing area, and accumulation of any per-cell field.
Edges named in an entry's telemetry ("bottom"/"south" = last row, "top"/"north" = row 0,
"left"/"west" = column 0, "right"/"east" = last column) are the outlets; with none, the
lowest edge cell is.
"""
import heapq

import numpy as np

EDGE_NAMES = {"bottom": "bottom", "south": "bottom", "top": "top", "north": "top",
              "left": "left", "west": "left", "right": "right", "east": "right"}
NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def outlet_mask(shape, open_edges):
    m = np.zeros(shape, bool)
    for e in open_edges or []:
        k = EDGE_NAMES.get(str(e).lower())
        if k == "bottom": m[-1, :] = True
        elif k == "top": m[0, :] = True
        elif k == "left": m[:, 0] = True
        elif k == "right": m[:, -1] = True
    return m


def fill(z, outlets, eps=1e-6):
    """Priority flood (Barnes et al. style, with epsilon) from the outlet cells."""
    ny, nx = z.shape
    if not outlets.any():
        edge = np.zeros_like(outlets); edge[[0, -1], :] = True; edge[:, [0, -1]] = True
        i = np.argmin(np.where(edge, z, np.inf)); outlets = np.zeros_like(outlets); outlets.flat[i] = True
    f = z.astype(float).copy()
    done = np.zeros(z.shape, bool)
    pq = [(f[i, j], i, j) for i, j in zip(*np.nonzero(outlets))]
    heapq.heapify(pq)
    done[outlets] = True
    while pq:
        h, i, j = heapq.heappop(pq)
        for di, dj in NB:
            a, b = i + di, j + dj
            if 0 <= a < ny and 0 <= b < nx and not done[a, b]:
                done[a, b] = True
                if f[a, b] <= h + eps:
                    f[a, b] = h + eps
                heapq.heappush(pq, (f[a, b], a, b))
    return f, outlets


def d8(f, outlets, dx):
    """Receiver index of each cell (-1 at outlets) and its steepest-descent slope."""
    ny, nx = f.shape
    best = np.zeros(f.shape); rec = -np.ones(f.size, int)
    idx = np.arange(f.size).reshape(f.shape)
    fp = np.pad(f, 1, constant_values=np.inf)
    for di, dj in NB:
        d = dx * np.hypot(di, dj)
        s = (f - fp[1 + di:1 + di + ny, 1 + dj:1 + dj + nx]) / d
        r = np.roll(np.roll(idx, -di, 0), -dj, 1)
        better = s > best
        best = np.where(better, s, best)
        rec = np.where(better.ravel(), r.ravel(), rec)
    rec[outlets.ravel()] = -1
    return rec, best


def accumulate_d8(rec, f, values):
    """Sum of `values` over each cell and everything upstream of it (D8)."""
    out = values.astype(float).ravel().copy()
    for c in np.argsort(-f.ravel(), kind="stable"):
        r = rec[c]
        if r >= 0:
            out[r] += out[c]
    return out.reshape(f.shape)


def accumulate_mfd(f, outlets, dx, values, p=1.1):
    """Multiple-flow accumulation: each cell splits to all lower neighbours by slope**p."""
    ny, nx = f.shape
    out = values.astype(float).copy()
    order = np.argsort(-f.ravel(), kind="stable")
    for c in order:
        i, j = divmod(c, nx)
        if outlets[i, j]:
            continue
        w, tgt = [], []
        for di, dj in NB:
            a, b = i + di, j + dj
            if 0 <= a < ny and 0 <= b < nx and f[a, b] < f[i, j]:
                w.append(((f[i, j] - f[a, b]) / (dx * np.hypot(di, dj))) ** p); tgt.append((a, b))
        if w:
            w = np.array(w) / sum(w)
            for wk, (a, b) in zip(w, tgt):
                out[a, b] += wk * out[i, j]
    return out


def route(z, open_edges, dx):
    """Everything the checks need, on one surface."""
    outlets = outlet_mask(z.shape, open_edges)
    f, outlets = fill(z, outlets)
    rec, slope = d8(f, outlets, dx)
    area = accumulate_d8(rec, f, np.full(z.shape, dx * dx))
    return {"filled": f, "outlets": outlets, "rec": rec, "slope": slope, "area": area}
