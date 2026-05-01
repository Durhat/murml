"""Floating Lade-Spinner während der Transkription.

Erzeugt ein kleines, randloses Fenster mit Apples Standard-Spinner
(`NSProgressIndicator` im Spinning-Style), positioniert es nahe der Maus
und blendet es wieder aus, wenn die Transkription fertig ist.

Hinweise:
- Cocoa-Operationen MÜSSEN am Main-Thread laufen. Dieses Modul wird
  ausschließlich aus der Tray-Pump (Main-Thread) heraus aufgerufen.
- Wir hätten den Spinner via Accessibility-API (`AXUIElement`) am echten
  Text-Cursor ankleben können. Das ist aber unzuverlässig: nicht jede App
  liefert die nötigen Bounds, und Webviews/Electron-Apps weigern sich
  meist komplett. Die Maus-Position ist deutlich robuster und ist
  ohnehin fast immer dort, wo du gerade hingeklickt hast.
"""

from __future__ import annotations

from typing import Optional

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSPoint,
    NSProgressIndicator,
    NSRect,
    NSSize,
    NSWindow,
)

# PyObjC stellt manche Konstanten nicht in jeder Version unter dem
# AppKit-Namen bereit; deshalb hier die Werte direkt aus den Apple-Headern.
_NSWindowStyleMaskBorderless = 0
_NSProgressIndicatorStyleSpinning = 1
_NSWindowCollectionBehaviorCanJoinAllSpaces = 1 << 0
_NSWindowCollectionBehaviorTransient = 1 << 4
# Über allen normalen Fenstern, unter Screen-Saver.
_NSStatusWindowLevel = 25


class LoadingIndicator:
    SIZE = 28          # Pixel Kantenlänge des Spinners
    OFFSET = (16, -32) # nach rechts/unten von der Maus, in Cocoa-Koordinaten

    def __init__(self) -> None:
        self._window: Optional[NSWindow] = None
        self._spinner: Optional[NSProgressIndicator] = None

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        size = self.SIZE
        rect = NSRect(NSPoint(0, 0), NSSize(size, size))

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            _NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        win.setBackgroundColor_(NSColor.clearColor())
        win.setOpaque_(False)
        win.setHasShadow_(False)
        win.setIgnoresMouseEvents_(True)
        win.setLevel_(_NSStatusWindowLevel)
        win.setCollectionBehavior_(
            _NSWindowCollectionBehaviorCanJoinAllSpaces
            | _NSWindowCollectionBehaviorTransient
        )

        spinner = NSProgressIndicator.alloc().initWithFrame_(rect)
        spinner.setStyle_(_NSProgressIndicatorStyleSpinning)
        spinner.setIndeterminate_(True)
        spinner.setDisplayedWhenStopped_(False)

        win.setContentView_(spinner)

        self._window = win
        self._spinner = spinner

    def show(self) -> None:
        self._ensure_window()
        if self._window is None or self._spinner is None:
            return
        # Maus-Position in globalen Bildschirmkoordinaten.
        mouse = NSEvent.mouseLocation()
        ox, oy = self.OFFSET
        origin = NSPoint(mouse.x + ox, mouse.y + oy)
        self._window.setFrameOrigin_(origin)
        self._spinner.startAnimation_(None)
        self._window.orderFrontRegardless()

    def hide(self) -> None:
        if self._window is None or self._spinner is None:
            return
        self._spinner.stopAnimation_(None)
        self._window.orderOut_(None)
