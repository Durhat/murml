"""Floating Status-Indicator nahe der Maus.

Zeigt zwei Zustände als kleine, dezente Pille:

- ``recording``    : ein sanft pulsierender roter Punkt
- ``transcribing`` : drei wandernde weiße Punkte

Stilistisch zurückhaltend: dunkles Glas, dezente Top-Highlight, ein
weicher Schatten unten — keine kräftigen Farben am Rand.

Hinweise:
- Wir hätten den Indicator via Accessibility-API direkt am echten Text-
  Cursor ankleben können. Das ist aber unzuverlässig: viele Apps liefern
  keine sinnvollen Bounds. Die Maus-Position ist robust und ist ohnehin
  fast immer dort, wo der Eingabe-Fokus liegt.
- Cocoa-Aufrufe MÜSSEN am Main-Thread laufen. Alle Methoden hier werden
  ausschließlich von der Tray-Pump (Main-Thread) aufgerufen.
"""

from __future__ import annotations

import math
from typing import Optional

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSGradient,
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


class _PillView(NSView):
    """Dezente Pille mit Mode-spezifischem Innenleben."""

    def initWithFrame_(self, frame):  # noqa: N802 (Cocoa API)
        self = objc.super(_PillView, self).initWithFrame_(frame)
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

    def drawRect_(self, dirty_rect):  # noqa: N802 (Cocoa API)
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height

        # Etwas Inset, damit der Schatten am Window-Rand Platz hat.
        inset = 1.0
        x = inset
        y = inset
        pw = w - 2 * inset
        ph = h - 2 * inset
        radius = ph / 2.0

        # 1) Hintergrund: dunkles Glas mit sehr dezentem Vertical-Gradient.
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSRect(NSPoint(x, y), NSSize(pw, ph)), radius, radius
        )
        # Oben minimal heller (wie Glas-Reflex), unten etwas dunkler.
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.78),
            NSColor.colorWithCalibratedWhite_alpha_(0.02, 0.88),
        )
        gradient.drawInBezierPath_angle_(bg_path, 90.0)

        # 2) Sehr dezenter Highlight oben (1 px Linie, sehr leise).
        highlight = NSBezierPath.bezierPath()
        margin = radius * 0.6
        highlight.moveToPoint_(NSPoint(x + margin, y + ph - 1.0))
        highlight.lineToPoint_(NSPoint(x + pw - margin, y + ph - 1.0))
        highlight.setLineWidth_(0.6)
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.18).setStroke()
        highlight.stroke()

        # 3) Hauchdünner Border, damit die Pille auf hellen Hintergründen
        #    nicht in der Luft hängt.
        bg_path.setLineWidth_(0.5)
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.10).setStroke()
        bg_path.stroke()

        # 4) Mode-spezifischer Inhalt.
        cx = x + pw / 2.0
        cy = y + ph / 2.0
        if self._mode == "recording":
            self._draw_recording(cx, cy, ph)
        else:
            self._draw_transcribing(cx, cy, pw, ph)

    @objc.python_method
    def _draw_recording(self, cx: float, cy: float, h: float) -> None:
        pulse = 0.5 + 0.5 * math.sin(self._t * 2 * math.pi * 1.2)
        # Ruhige, kleine Größe; nur subtil pulsierend.
        radius = h * (0.20 + 0.04 * pulse)
        path = NSBezierPath.bezierPathWithOvalInRect_(
            NSRect(NSPoint(cx - radius, cy - radius),
                   NSSize(radius * 2, radius * 2))
        )
        # Weiches, eher matt-rotes Apple-Style.
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.94, 0.32 + 0.08 * pulse, 0.34 + 0.08 * pulse, 0.92
        ).setFill()
        path.fill()

    @objc.python_method
    def _draw_transcribing(self, cx: float, cy: float, w: float, h: float) -> None:
        n = 3
        radius = h * 0.13
        gap = h * 0.46
        total = (n - 1) * gap
        x0 = cx - total / 2.0
        for i in range(n):
            phase = self._t * 2 * math.pi * 1.4 - i * (math.pi * 0.55)
            pulse = 0.5 + 0.5 * math.sin(phase)
            r = radius * (0.75 + 0.45 * pulse)
            x = x0 + i * gap
            path = NSBezierPath.bezierPathWithOvalInRect_(
                NSRect(NSPoint(x - r, cy - r), NSSize(r * 2, r * 2))
            )
            NSColor.colorWithCalibratedWhite_alpha_(
                0.96, 0.55 + 0.40 * pulse
            ).setFill()
            path.fill()


# ── Timer-Target ────────────────────────────────────────────────────

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
    WIDTH = 44
    HEIGHT = 18
    OFFSET = (16, -28)
    TICK_HZ = 24.0   # ruhiger als vorher

    def __init__(self) -> None:
        self._window: Optional[NSWindow] = None
        self._view: Optional[_PillView] = None
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
        win.setHasShadow_(True)
        win.setIgnoresMouseEvents_(True)
        win.setLevel_(_NSStatusWindowLevel)
        win.setCollectionBehavior_(
            _NSWindowCollectionBehaviorCanJoinAllSpaces
            | _NSWindowCollectionBehaviorTransient
        )

        view = _PillView.alloc().initWithFrame_(rect)
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
            dt = (1.0 / self.TICK_HZ) if last[0] is None else (now - last[0])
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
