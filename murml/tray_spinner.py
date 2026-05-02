"""Tray-Spinner während TRANSCRIBING: Wandernder Punkt mit ~1/3-Umfangs-Schweif.

@2×-Raster (PNG), Maxwellsche Scheiben entlang eines Kreisbogens — ohne die
später hinzugefügte Partikel-/Shimmer-Schicht oder Display-abhängiges Timing.
"""

from __future__ import annotations

import math
from io import BytesIO

import numpy as np
from AppKit import NSData, NSImage, NSSize
from PIL import Image

TRAY_SPINNER_SIZE = 20.0
_BITMAP_SCALE = 2

_ORBIT_RADIUS = 7.15
_DOT_RADIUS = 1.92
_SAMPLES = 56
_TRAIL_ANGLE_RAD = math.tau / 3.0
_TAIL_R_FACTOR = 0.32
_WIDTH_SCALE = 0.91
_TAIL_ALPHA_POWER = 1.06
_SPIN_PERIOD_S = 1.35
_AA_PT = 0.52


def transcribing_theta_at(monotonic_elapsed_s: float) -> float:
    omega = math.tau / _SPIN_PERIOD_S
    return monotonic_elapsed_s * omega


def _smooth_outside_disc(dist: np.ndarray, radius: float, aa: float) -> np.ndarray:
    t = np.clip((radius + aa * 0.5 - dist) / max(aa, 1e-4), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def transcribing_spinner_nsimage(theta_head_rad: float) -> NSImage:
    sc = float(_BITMAP_SCALE)
    pts = TRAY_SPINNER_SIZE
    p = max(4, int(round(pts * sc)))
    aa = max(1.0, _AA_PT * sc)

    gx, gy = np.meshgrid(np.arange(p, dtype=np.float64), np.arange(p, dtype=np.float64))

    cx = (pts / 2.0) * sc
    cy = (pts / 2.0) * sc
    r_o = _ORBIT_RADIUS * sc
    dot_r_px = _DOT_RADIUS * sc
    tail_radius_min = dot_r_px * _TAIL_R_FACTOR

    accum = np.zeros((p, p), dtype=np.float64)
    n = max(3, _SAMPLES)

    for i in range(n):
        s = i / float(n - 1)
        ang = theta_head_rad - _TRAIL_ANGLE_RAD * (1.0 - s)
        px = cx + r_o * math.cos(ang)
        py = cy + r_o * math.sin(ang)
        rad = (tail_radius_min + (dot_r_px - tail_radius_min) * s) * _WIDTH_SCALE
        alpha = math.pow(s, _TAIL_ALPHA_POWER)
        d = np.hypot(gx - px, gy - py)
        splat = alpha * _smooth_outside_disc(d, rad, aa)
        accum = np.maximum(accum, splat)

    rgba = np.zeros((p, p, 4), dtype=np.uint8)
    ch = np.clip(np.round(accum * 255.0), 0, 255).astype(np.uint8)
    rgba[:, :, 3] = ch

    buf = BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", compress_level=3)
    data = buf.getvalue()
    img = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(data, len(data)))
    img.setSize_(NSSize(pts, pts))
    return img
