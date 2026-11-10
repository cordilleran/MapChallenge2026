"""Reading the inks of the scan: paper colour, optical density, and the four ink plates.

Shared by 03_ice1913.py (blue versus brown contour ink) and 07b_scan_colour.py (colour matching).
"""
import numpy as np
from scipy import ndimage as ndi


def paper_and_od(rgb):
    """Paper colour per channel (smooth 80th percentile) and optical density OD = -log10(I / paper)."""
    small = rgb[:, ::8, ::8]
    paper = np.stack([ndi.percentile_filter(c, 80, size=9) for c in small])
    paper = np.stack([ndi.zoom(ndi.gaussian_filter(c, 2), 8, order=1)[: rgb.shape[1], : rgb.shape[2]]
                      for c in paper])
    od = np.maximum(0, -np.log10(np.clip(rgb, 1, 255) / np.clip(paper, 1, 255)))
    return paper, od


def plates(od):
    """Masks of the blue, brown, black and red inks."""
    r, g, b = od
    ink = od.sum(0) > 0.12
    black = od.min(0) > 0.22               # lettering, boundary, railway, frame
    # Roads and trails. The red ink absorbs more green than blue; dense brown absorbs more blue than
    # green and passed the first two tests on the master TIFF (2.6 % of the sheet), not on the JPEG.
    red = (g - r > 0.08) & (b - r > 0.05) & (g > b)
    keep = ink & ~black & ~red
    return {"blue": keep & (r - b > 0.015), "brown": keep & (b - r > 0.015), "black": ink & black,
            "red": ink & red & ~black}
