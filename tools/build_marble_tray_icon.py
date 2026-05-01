#!/usr/bin/env python3
"""Erzeugt Template-PNGs für die Menüleiste aus assets/murml-marble.svg.

1. qlmanage rendert das SVG zu einem großen Raster-PNG.
2. Pillow wandelt zu macOS-Template-Style (schwarze Form, Alpha = Opazität).

Aufruf aus dem Repo-Root:  python tools/build_marble_tray_icon.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow fehlt:  pip install Pillow", file=sys.stderr)
    sys.exit(1)


def _qlmanage_render(svg: Path, tmp_dir: Path, size: int = 512) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "qlmanage",
            "-t",
            "-s",
            str(size),
            "-o",
            str(tmp_dir),
            str(svg),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    produced = tmp_dir / f"{svg.name}.png"
    if not produced.exists():
        raise FileNotFoundError(f"qlmanage erzeugte keine Datei: {produced}")
    return produced


def _to_template_rgba(im: Image.Image) -> Image.Image:
    """Weiße Form auf Transparent → schwarze Form, Alpha = Luminanz."""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            # Luminanz der ursprünglichen (meist weißen) Fläche
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            alpha = int(round(a * lum))
            px[x, y] = (0, 0, 0, alpha)
    return rgba


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    svg = root / "assets" / "murml-marble.svg"
    if not svg.exists():
        print(f"SVG nicht gefunden: {svg}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        big_path = _qlmanage_render(svg, Path(tmp), size=512)
        im = Image.open(big_path)
        im = _to_template_rgba(im)

        out_1x = root / "assets" / "tray-icon.png"
        out_2x = root / "assets" / "tray-icon@2x.png"
        im.resize((18, 18), Image.Resampling.LANCZOS).save(out_1x, "PNG")
        im.resize((36, 36), Image.Resampling.LANCZOS).save(out_2x, "PNG")
        print(f"  geschrieben: {out_1x}")
        print(f"  geschrieben: {out_2x}")


if __name__ == "__main__":
    main()
