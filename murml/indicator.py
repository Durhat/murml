"""Floating Status-Indicator nahe der Maus.

Zeigt zwei Zustände:

- ``recording``    : ein pulsierender roter Punkt
- ``transcribing`` : drei Punkte, die nacheinander pulsieren

Die Anzeige liegt in einem randlosen, klick-durchlässigen Fenster, das
ständig oben bleibt (``NSStatusWindowLevel``) und mit einem dezenten
Vibrancy-Hintergrund versehen ist.

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
from typing import Optional

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


# ── Custom NSView ────────────────────────────────────────────────────

class _DotsView(NSView):
    """View, die drei Punkte oder einen Punkt zeichnet."""

    def initWithFrame_(self, frame):  # noqa: N802 (Cocoa API)
        self = objc.super(_DotsView, self).initWithFrame_(frame)
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

        # Hintergrund-Pille mit subtiler Transparenz und Schatten kommt vom
        # Window selbst (siehe LoadingIndicator); hier malen wir nur das
        # eigentliche Innenleben.
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSRect(NSPoint(0, 0), NSSize(w, h)),
            h / 2.0,
            h / 2.0,
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.72).setFill()
        bg_path.fill()

        if self._mode == "recording":
            self._draw_recording(w, h)
        else:
            self._draw_transcribing(w, h)

    @objc.python_method
    def _draw_recording(self, w: float, h: float) -> None:
        # Ein pulsierender roter Punkt, mittig.
        pulse = 0.5 + 0.5 * math.sin(self._t * 2 * math.pi * 1.4)  # 1.4 Hz
        radius = h * (0.18 + 0.06 * pulse)
        cx = w / 2.0
        cy = h / 2.0
        circle = NSBezierPath.bezierPathWithOvalInRect_(
            NSRect(NSPoint(cx - radius, cy - radius), NSSize(radius * 2, radius * 2))
        )
        # Sattes Apple-Rot, Helligkeit pulsiert.
        red = 0.95
        green = 0.25 + 0.10 * pulse
        blue = 0.30 + 0.10 * pulse
        alpha = 0.85 + 0.15 * pulse
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            red, green, blue, alpha
        ).setFill()
        circle.fill()

    @objc.python_method
    def _draw_transcribing(self, w: float, h: float) -> None:
        # Drei Punkte, die nacheinander pulsieren.
        n = 3
        radius = h * 0.18
        gap = h * 0.55
        total = (n - 1) * gap
        cy = h / 2.0
        cx0 = (w - total) / 2.0

        for i in range(n):
            phase = self._t * 2 * math.pi * 1.6 - i * (math.pi * 0.55)
            pulse = 0.5 + 0.5 * math.sin(phase)
            r = radius * (0.7 + 0.45 * pulse)
            cx = cx0 + i * gap
            circle = NSBezierPath.bezierPathWithOvalInRect_(
                NSRect(NSPoint(cx - r, cy - r), NSSize(r * 2, r * 2))
            )
            alpha = 0.55 + 0.40 * pulse
            NSColor.colorWithCalibratedWhite_alpha_(0.95, alpha).setFill()
            circle.fill()


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

    WIDTH = 44
    HEIGHT = 18
    OFFSET = (16, -28)   # rechts/unten von der Maus, in Cocoa-Koordinaten
    TICK_HZ = 30.0       # Frames pro Sekunde

    def __init__(self) -> None:
        self._window: Optional[NSWindow] = None
        self._view: Optional[_DotsView] = None
        self._timer: Optional[NSTimer] = None
        self._timer_target: Optional[_TimerTarget] = None
        self._visible = False

    # --- Aufbau ---

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

        view = _DotsView.alloc().initWithFrame_(rect)
        win.setContentView_(view)

        self._window = win
        self._view = view

    def _start_timer(self) -> None:
        if self._timer is not None:
            return
        last = [None]  # mutable container für Closure

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

    # --- Public ---

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
        # Ein Redraw, damit der Mode-Wechsel sofort sichtbar ist.
        self._view.setNeedsDisplay_(True)

    def hide(self) -> None:
        if self._window is None:
            return
        self._stop_timer()
        if self._visible:
            self._window.orderOut_(None)
            self._visible = False
