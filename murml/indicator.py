"""Floating Status-Indicator nahe der Maus.

Zeigt zwei Zustände im selben "Apple-Intelligence"-Look:
- ``recording``    : pulsierender roter Punkt mit umlaufendem Glow
- ``transcribing`` : drei wandernde Punkte mit umlaufendem Glow

Der Glow ist ein animierter, langsam rotierender Regenbogen-Hue-Shift entlang
des Pillen-Rands, gerendert über kleine, schimmernde Path-Segmente plus
zusätzlichen Stroke-Layern, die dem Rand einen weichen Schein geben.

Hinweise:
- Wir hätten den Indicator via Accessibility-API direkt am echten Text-
  Cursor ankleben können. Das ist aber unzuverlässig: viele Apps liefern
  keine sinnvollen Bounds (Webviews, Electron, viele Cocoa-Editoren).
  Die Maus-Position ist robust und ist ohnehin fast immer dort, wo der
  Eingabe-Fokus liegt.
- Cocoa-Aufrufe MÜSSEN am Main-Thread laufen. Alle Methoden hier werden
  ausschließlich von der Tray-Pump (Main-Thread) aufgerufen.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSPoint,
    NSRect,
    NSSize,
    NSView,
    NSWindow,
)
from Foundation import NSObject, NSTimer

# Werte aus den Apple-Headern; pyobjc bietet sie nicht überall an.
_NSWindowStyleMaskBorderless = 0
_NSWindowCollectionBehaviorCanJoinAllSpaces = 1 << 0
_NSWindowCollectionBehaviorTransient = 1 << 4
_NSStatusWindowLevel = 25


# ── Geometrie-Helfer ────────────────────────────────────────────────

def _pill_perimeter_points(
    rect_origin_x: float,
    rect_origin_y: float,
    width: float,
    height: float,
    n: int,
) -> List[Tuple[float, float]]:
    """Gleichverteilte Punkte entlang einer Pille (Stadium).

    Die Pille besteht aus zwei geraden Stücken (oben/unten) und zwei
    Halbkreisen (links/rechts). Wir laufen den Umfang ab, parametrisiert
    nach der Bogenlänge.
    """
    r = height / 2.0
    straight = max(width - 2.0 * r, 0.0)
    semicircle = math.pi * r
    perim = 2.0 * straight + 2.0 * semicircle
    if perim <= 0:
        return [(rect_origin_x, rect_origin_y)] * n

    cx_left = rect_origin_x + r
    cx_right = rect_origin_x + width - r
    cy = rect_origin_y + r

    pts: List[Tuple[float, float]] = []
    for i in range(n):
        s = (i / n) * perim
        if s < straight:                                # oben (links → rechts)
            x = cx_left + s
            y = rect_origin_y + height
        elif s < straight + semicircle:                 # rechter Halbkreis (oben → unten)
            t = (s - straight) / r        # 0..π
            angle = math.pi / 2.0 - t
            x = cx_right + r * math.cos(angle)
            y = cy + r * math.sin(angle)
        elif s < 2.0 * straight + semicircle:           # unten (rechts → links)
            x = cx_right - (s - straight - semicircle)
            y = rect_origin_y
        else:                                           # linker Halbkreis (unten → oben)
            t = (s - 2.0 * straight - semicircle) / r   # 0..π
            angle = -math.pi / 2.0 - t
            x = cx_left + r * math.cos(angle)
            y = cy + r * math.sin(angle)
        pts.append((x, y))
    return pts


# ── Custom NSView ───────────────────────────────────────────────────

class _GlowView(NSView):
    """Pille mit animiertem Apple-Intelligence-artigem Hue-Shift-Glow."""

    SEGMENTS = 96
    GLOW_LAYERS = (   # (line_width, alpha)
        (8.0, 0.10),
        (5.0, 0.18),
        (3.0, 0.40),
        (1.6, 0.95),
    )

    def initWithFrame_(self, frame):  # noqa: N802 (Cocoa API)
        self = objc.super(_GlowView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._mode = "transcribing"
        self._t = 0.0
        return self

    @objc.python_method
    def set_mode(self, mode: str) -> None:
        self._mode = mode

    @objc.python_method
    def tick(self, dt: float) -> None:
        self._t = (self._t + dt) % 10_000.0
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _hue_at(self, fraction: float) -> float:
        # Phase rotiert mit ~6 s pro Umlauf.
        return ((fraction + self._t * 0.165) % 1.0)

    def drawRect_(self, dirty_rect):  # noqa: N802 (Cocoa API)
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height

        # Wir lassen einen kleinen Rand frei, damit der Glow nicht abgeschnitten
        # wird (er strahlt nach außen). Inset ≈ 4 px.
        inset = 4.0
        pill_x = inset
        pill_y = inset
        pill_w = w - 2 * inset
        pill_h = h - 2 * inset
        radius = pill_h / 2.0

        # 1) Dunkler Hintergrund mit hoher Sättigung – wirkt wie schwarzes Glas.
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSRect(NSPoint(pill_x, pill_y), NSSize(pill_w, pill_h)),
            radius,
            radius,
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.04, 0.85).setFill()
        bg_path.fill()

        # 2) Hue-Shift-Glow: viele kleine Segmente entlang des Umrisses,
        #    mehrfach gestrokt für weichen Glanz nach außen.
        pts = _pill_perimeter_points(pill_x, pill_y, pill_w, pill_h, self.SEGMENTS)
        # Geschlossene Schleife: ein Punkt mehr am Ende.
        pts_loop = pts + [pts[0]]

        for line_width, base_alpha in self.GLOW_LAYERS:
            for i in range(self.SEGMENTS):
                p0 = pts_loop[i]
                p1 = pts_loop[i + 1]
                hue = self._hue_at(i / self.SEGMENTS)
                # Sanfte Modulation der Helligkeit pro Segment, gibt
                # zusätzlichen "Sheen".
                shimmer = 0.5 + 0.5 * math.sin(
                    self._t * 2 * math.pi * 0.7
                    - (i / self.SEGMENTS) * 2 * math.pi * 1.6
                )
                color = NSColor.colorWithCalibratedHue_saturation_brightness_alpha_(
                    hue,
                    0.78,
                    0.88 + 0.10 * shimmer,
                    base_alpha,
                )
                color.setStroke()
                seg = NSBezierPath.bezierPath()
                seg.setLineWidth_(line_width)
                seg.setLineCapStyle_(1)  # Round
                seg.moveToPoint_(NSPoint(p0[0], p0[1]))
                seg.lineToPoint_(NSPoint(p1[0], p1[1]))
                seg.stroke()

        # 3) Mode-spezifischer Inner-Content.
        cx = pill_x + pill_w / 2.0
        cy = pill_y + pill_h / 2.0
        if self._mode == "recording":
            self._draw_recording(cx, cy, pill_h)
        else:
            self._draw_transcribing(cx, cy, pill_w, pill_h)

    @objc.python_method
    def _draw_recording(self, cx: float, cy: float, h: float) -> None:
        pulse = 0.5 + 0.5 * math.sin(self._t * 2 * math.pi * 1.3)
        radius = h * (0.18 + 0.06 * pulse)
        path = NSBezierPath.bezierPathWithOvalInRect_(
            NSRect(NSPoint(cx - radius, cy - radius),
                   NSSize(radius * 2, radius * 2))
        )
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.96,
            0.27 + 0.10 * pulse,
            0.30 + 0.10 * pulse,
            0.92,
        ).setFill()
        path.fill()

    @objc.python_method
    def _draw_transcribing(self, cx: float, cy: float, w: float, h: float) -> None:
        n = 3
        radius = h * 0.12
        gap = h * 0.46
        total = (n - 1) * gap
        x0 = cx - total / 2.0
        for i in range(n):
            phase = self._t * 2 * math.pi * 1.5 - i * (math.pi * 0.55)
            pulse = 0.5 + 0.5 * math.sin(phase)
            r = radius * (0.7 + 0.55 * pulse)
            x = x0 + i * gap
            path = NSBezierPath.bezierPathWithOvalInRect_(
                NSRect(NSPoint(x - r, cy - r), NSSize(r * 2, r * 2))
            )
            NSColor.colorWithCalibratedWhite_alpha_(
                0.96, 0.55 + 0.40 * pulse
            ).setFill()
            path.fill()


# ── Timer-Target (NSObject, weil NSTimer eine Selektor-Methode braucht) ──

class _TimerTarget(NSObject):
    def initWithCallback_(self, cb):  # noqa: N802
        self = objc.super(_TimerTarget, self).init()
        if self is None:
            return None
        self._cb = cb
        return self

    def fire_(self, _timer):  # noqa: N802
        try:
            self._cb()
        except Exception as e:  # pragma: no cover
            print(f"[indicator] tick error: {e}")


# ── Public API ───────────────────────────────────────────────────────

class LoadingIndicator:
    """Bündelt Window + View + Timer für die zwei Anzeigemodi."""

    WIDTH = 64
    HEIGHT = 26
    OFFSET = (16, -34)   # rechts/unten von der Maus, in Cocoa-Koordinaten
    TICK_HZ = 30.0       # Frames pro Sekunde

    def __init__(self) -> None:
        self._window: Optional[NSWindow] = None
        self._view: Optional[_GlowView] = None
        self._timer: Optional[NSTimer] = None
        self._timer_target: Optional[_TimerTarget] = None
        self._visible = False

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        rect = NSRect(NSPoint(0, 0), NSSize(self.WIDTH, self.HEIGHT))

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            _NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        win.setBackgroundColor_(NSColor.clearColor())
        win.setOpaque_(False)
        win.setHasShadow_(False)        # Glow malen wir selbst.
        win.setIgnoresMouseEvents_(True)
        win.setLevel_(_NSStatusWindowLevel)
        win.setCollectionBehavior_(
            _NSWindowCollectionBehaviorCanJoinAllSpaces
            | _NSWindowCollectionBehaviorTransient
        )

        view = _GlowView.alloc().initWithFrame_(rect)
        win.setContentView_(view)

        self._window = win
        self._view = view

    def _start_timer(self) -> None:
        if self._timer is not None:
            return
        last = [None]

        def _tick():
            import time as _time
            now = _time.monotonic()
            if last[0] is None:
                dt = 1.0 / self.TICK_HZ
            else:
                dt = now - last[0]
            last[0] = now
            if self._view is not None:
                self._view.tick(dt)

        self._timer_target = _TimerTarget.alloc().initWithCallback_(_tick)
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / self.TICK_HZ,
            self._timer_target,
            "fire:",
            None,
            True,
        )

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
            self._timer_target = None

    def show(self, mode: str) -> None:
        """``mode`` ∈ {``recording``, ``transcribing``}."""
        self._ensure_window()
        if self._window is None or self._view is None:
            return
        self._view.set_mode(mode)
        mouse = NSEvent.mouseLocation()
        ox, oy = self.OFFSET
        origin = NSPoint(mouse.x + ox, mouse.y + oy)
        self._window.setFrameOrigin_(origin)
        if not self._visible:
            self._window.orderFrontRegardless()
            self._start_timer()
            self._visible = True
        self._view.setNeedsDisplay_(True)

    def hide(self) -> None:
        if self._window is None:
            return
        self._stop_timer()
        if self._visible:
            self._window.orderOut_(None)
            self._visible = False
