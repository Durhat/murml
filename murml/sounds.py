"""Akustische Statusrückmeldungen über macOS' afplay.

Spielt Sounds asynchron, ohne den Hauptprozess zu blockieren.
Reihenfolge der Suche für einen Sound-Namen:

  1. Absoluter Pfad, falls der Name einer ist.
  2. ./sounds/<name>(.wav|.aiff|.mp3|.m4a) im Projektordner.
  3. /System/Library/Sounds/<name>.aiff (Apple-Defaults als Fallback).

Wenn nichts passt, wird leise nichts getan.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

_SYSTEM_SOUND_DIR = Path("/System/Library/Sounds")
_PROJECT_SOUND_DIR = Path(__file__).resolve().parent.parent / "sounds"
_AUDIO_EXTS = (".wav", ".aiff", ".aif", ".mp3", ".m4a", ".caf")


def _enabled() -> bool:
    return os.getenv("MURML_SOUNDS", "on").lower() not in {"0", "off", "false", "no"}


def _resolve(name: str) -> Optional[Path]:
    if not name:
        return None

    p = Path(name)
    if p.is_absolute() and p.exists():
        return p

    if p.suffix and (_PROJECT_SOUND_DIR / p).exists():
        return _PROJECT_SOUND_DIR / p

    for ext in _AUDIO_EXTS:
        cand = _PROJECT_SOUND_DIR / f"{p.stem or name}{ext}"
        if cand.exists():
            return cand

    for ext in (".aiff", ".caf", ".wav"):
        cand = _SYSTEM_SOUND_DIR / f"{name}{ext}"
        if cand.exists():
            return cand

    return None


def play(name: str, volume: float = 0.4) -> None:
    """Spielt einen Sound asynchron. Fehler werden geschluckt."""
    if not _enabled():
        return
    path = _resolve(name)
    if path is None:
        return
    try:
        subprocess.Popen(
            ["afplay", "-v", f"{volume:.2f}", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _vol(env_name: str, default: float) -> float:
    try:
        return float(os.getenv(env_name, str(default)))
    except ValueError:
        return default


def start() -> None:
    play(os.getenv("MURML_SOUND_START", "start"), _vol("MURML_SOUND_START_VOL", 0.4))


def stop() -> None:
    play(os.getenv("MURML_SOUND_STOP", "stop"), _vol("MURML_SOUND_STOP_VOL", 0.4))


def done() -> None:
    play(os.getenv("MURML_SOUND_DONE", "done"), _vol("MURML_SOUND_DONE_VOL", 0.25))


def error() -> None:
    play(os.getenv("MURML_SOUND_ERROR", "error"), _vol("MURML_SOUND_ERROR_VOL", 0.4))
