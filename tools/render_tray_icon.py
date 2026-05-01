#!/usr/bin/env python3
"""Erzeugt das Menüleisten-Symbol für murml.

Wir malen einen Kreis mit einem kleinen Highlight oben rechts — die "Murmel".
Das Bild wird als Template gespeichert (nur Schwarz auf Transparenz), damit
macOS es automatisch dem aktuellen Menüleisten-Stil (Hell/Dunkel) anpasst.

Aufruf:  python tools/render_tray_icon.py
Schreibt: assets/tray-icon.png       (18×18, 1×)
          assets/tray-icon@2x.png    (36×36, 2×)

Die PNGs werden ins Repo eingecheckt und von ``murml/tray.py`` per Pfad an
rumps übergeben.
"""

from __future__ import annotations

import math
from pathlib import Path

from AppKit import (
    NSBitmapImageRep,
    NSBezierPath,
    NSCalibratedRGBColorSpace,
    NSColor,
    NSGraphicsContext,
    NSPoint,
    NSRect,
    NSSize,
)

PNG_TYPE = 4  # NSBitmapImageFileTypePNG


def render(size: int) -> bytes:
    """Rendert direkt in eine NSBitmapImageRep mit exakt ``size`` Pixeln."""
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 32
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    # Strichstärke skaliert mit der Größe.
    line_width = max(1.0, size * 0.085)
    margin = line_width * 0.9

    # ── Outer circle (Outline)
    NSColor.blackColor().setStroke()
    outer = NSBezierPath.bezierPathWithOvalInRect_(
        NSRect(
            NSPoint(margin, margin),
            NSSize(size - 2 * margin, size - 2 * margin),
        )
    )
    outer.setLineWidth_(line_width)
    outer.stroke()

    # ── Highlight oben rechts: kleiner gefüllter Punkt
    NSColor.blackColor().setFill()

    cx = size / 2.0
    cy = size / 2.0
    r_outer = (size / 2.0) - margin

    angle = math.radians(50)  # 0° = rechts, 90° = oben
    hx = cx + math.cos(angle) * (r_outer * 0.55)
    hy = cy + math.sin(angle) * (r_outer * 0.55)
    hr = max(1.0, size * 0.105)

    highlight = NSBezierPath.bezierPathWithOvalInRect_(
        NSRect(NSPoint(hx - hr, hy - hr), NSSize(hr * 2, hr * 2))
    )
    highlight.fill()

    NSGraphicsContext.restoreGraphicsState()

    png = rep.representationUsingType_properties_(PNG_TYPE, {})
    return bytes(png)


def main() -> None:
    here = Path(__file__).resolve().parent
    out_dir = here.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    for size, name in [(18, "tray-icon.png"), (36, "tray-icon@2x.png")]:
        data = render(size)
        path = out_dir / name
        path.write_bytes(data)
        print(f"  geschrieben: {path}  ({len(data)} bytes)")


if __name__ == "__main__":
    main()
