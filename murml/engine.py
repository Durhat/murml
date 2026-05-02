"""Push-to-Talk-Engine: orchestriert Hotkey → Recorder → Transcriber → Paste.

Hier liegt die ganze Domänenlogik UI-agnostisch. Die Tray-App benutzt diese
Klasse über einen schmalen Listener, das CLI ebenso.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from typing import Callable, Optional

from . import sounds
from .history import History
from .paster import paste_text
from .recorder import Recorder

# Status-Werte für die UI:
STATUS_IDLE = "idle"
STATUS_ARMED = "armed"        # Press registriert, noch nicht entschieden
STATUS_RECORDING = "recording"
STATUS_TRANSCRIBING = "transcribing"


# Whisper neigt bei Stille zu Halluzinationen aus seinem Trainingsmaterial:
# Untertitel-Disclaimer, Werbe-Floskeln, „Vielen Dank fürs Zuschauen". Wenn
# die komplette Ausgabe nur aus solchen Schnipseln besteht, werfen wir sie weg.
_HALLUCINATION_PATTERNS = (
    re.compile(r"untertitel.{0,40}(zdf|ard|wdr|funk|ndr|rundfunk|stephanie geiges)", re.I),
    re.compile(r"untertitelung.{0,40}(zdf|ard|wdr|funk|ndr|rundfunk)", re.I),
    re.compile(r"vielen dank f.{1,3}r.{0,4}(zuschauen|zusehen|zuh.ren|hinschauen)", re.I),
    re.compile(r"copyright.{0,5}\d{4}", re.I),
    re.compile(r"^\s*[\.\!\?\,]+\s*$"),
    re.compile(r"^\s*(thanks?|thank you)\s+for\s+watching\.?\s*$", re.I),
    re.compile(r"^\s*(\.|,|untertitel.*)$", re.I),
)


def _is_hallucination(text: str) -> bool:
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 2:
        return True
    return any(p.search(stripped) for p in _HALLUCINATION_PATTERNS)


def _open_emoji_picker() -> None:
    """Öffnet Apples Zeichenviewer / Emoji-Picker via Ctrl+Cmd+Space."""
    try:
        subprocess.Popen(
            [
                "osascript",
                "-e",
                'tell application "System Events" to key code 49 using {control down, command down}',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[emoji] Konnte Picker nicht öffnen: {e}")


class Engine:
    def __init__(
        self,
        transcribe: Callable[[str], str],
        recorder: Recorder,
        history: History,
        on_status: Optional[Callable[[str], None]] = None,
        on_history_change: Optional[Callable[[], None]] = None,
        tap_threshold: float = 0.25,
        emoji_on_tap: bool = True,
        max_record_seconds: float = 0.0,
    ) -> None:
        self._transcribe = transcribe
        self._recorder = recorder
        self._history = history
        self._on_status = on_status or (lambda s: None)
        self._on_history_change = on_history_change or (lambda: None)
        self._tap_threshold = tap_threshold
        self._emoji_on_tap = emoji_on_tap
        self._max_record_seconds = max_record_seconds

        self._lock = threading.Lock()
        self._phase = STATUS_IDLE
        self._press_id = 0
        self._arm_timer: Optional[threading.Timer] = None
        self._max_timer: Optional[threading.Timer] = None
        self._paused = False  # Pausen-Modus: Hotkey-Callbacks werden ignoriert.

    # ── öffentliche API für die UI ────────────────────────────────────

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, value: bool) -> None:
        self._paused = bool(value)
        if self._paused and self._phase != STATUS_IDLE:
            # Laufende Aufnahme abbrechen.
            self._cancel_active()

    def status(self) -> str:
        return self._phase

    # ── Hotkey-Callbacks ──────────────────────────────────────────────

    def on_press(self) -> None:
        if self._paused:
            return
        with self._lock:
            if self._phase != STATUS_IDLE:
                sounds.error()
                return
            self._phase = STATUS_ARMED
            self._press_id += 1
            pid = self._press_id
            t = threading.Timer(self._tap_threshold, self._begin_recording, args=(pid,))
            t.daemon = True
            self._arm_timer = t
        self._on_status(STATUS_ARMED)
        t.start()

    def on_release(self) -> None:
        with self._lock:
            phase = self._phase
            arm_timer = self._arm_timer
            max_timer = self._max_timer
            self._arm_timer = None
            self._max_timer = None
            # ARMED → tap, sofort idle.
            # RECORDING → erst nach recorder.stop() entscheiden, ob TRANSCRIBING
            # (es gibt Audio) oder IDLE (zu kurz/leise).
            if phase == STATUS_ARMED:
                self._phase = STATUS_IDLE

        if arm_timer is not None:
            arm_timer.cancel()
        if max_timer is not None:
            max_timer.cancel()

        if phase == STATUS_ARMED:
            # Tap erkannt: kein Audio, optional Emoji-Picker.
            self._on_status(STATUS_IDLE)
            if self._emoji_on_tap and not self._paused:
                _open_emoji_picker()
            return

        if phase == STATUS_RECORDING:
            sounds.stop()
            try:
                audio_path = self._recorder.stop()
            except Exception as e:
                print(f"[recorder] Stop-Fehler: {e}")
                audio_path = None

            if audio_path is None:
                # Nichts zu transkribieren → keinen Worker starten,
                # Phase direkt zurück nach IDLE.
                with self._lock:
                    self._phase = STATUS_IDLE
                self._on_status(STATUS_IDLE)
                return

            with self._lock:
                self._phase = STATUS_TRANSCRIBING
            self._on_status(STATUS_TRANSCRIBING)
            threading.Thread(
                target=self._process, args=(audio_path,), daemon=True
            ).start()
            return

        # phase ∈ {IDLE, TRANSCRIBING}: verirrtes release, ignorieren.

    # ── interne Hilfsmethoden ─────────────────────────────────────────

    def _begin_recording(self, expected_id: int) -> None:
        with self._lock:
            if self._phase != STATUS_ARMED or self._press_id != expected_id:
                return
            self._phase = STATUS_RECORDING
            self._arm_timer = None

        print("● Aufnahme läuft…")
        sounds.start()
        try:
            self._recorder.start()
        except Exception as e:
            with self._lock:
                self._phase = STATUS_IDLE
            sounds.error()
            self._on_status(STATUS_IDLE)
            print(f"[recorder] Konnte Aufnahme nicht starten: {e}")
            return

        self._on_status(STATUS_RECORDING)

        if self._max_record_seconds > 0:
            t = threading.Timer(
                self._max_record_seconds, self._force_release, args=(expected_id,)
            )
            t.daemon = True
            with self._lock:
                self._max_timer = t
            t.start()

    def _force_release(self, expected_id: int) -> None:
        with self._lock:
            if self._phase != STATUS_RECORDING or self._press_id != expected_id:
                return
        print(
            f"[!] Aufnahme >{self._max_record_seconds:.0f}s — automatischer Stop."
        )
        self.on_release()

    def _cancel_active(self) -> None:
        """Bricht laufende Aufnahme ohne Transkription ab (für Pause-Modus)."""
        with self._lock:
            arm = self._arm_timer
            mx = self._max_timer
            self._arm_timer = None
            self._max_timer = None
            self._phase = STATUS_IDLE
        if arm is not None:
            arm.cancel()
        if mx is not None:
            mx.cancel()
        try:
            self._recorder.stop()
        except Exception:
            pass
        self._on_status(STATUS_IDLE)

    def _process(self, audio_path: str) -> None:
        try:
            try:
                print("… transkribiere")
                text = self._transcribe(audio_path)
                text = (text or "").strip()
                if not text:
                    print("[!] Keine Sprache erkannt.")
                    return
                if _is_hallucination(text):
                    print(f"[!] Halluzination unterdrückt: {text!r}")
                    return
                print(f"✓ {text}")
                paste_text(text)
                self._history.add(text)
                self._on_history_change()
                sounds.done()
            except Exception as e:
                sounds.error()
                print(f"[x] Fehler bei Transkription: {e}")
            finally:
                try:
                    os.unlink(audio_path)
                except Exception:
                    pass
        finally:
            with self._lock:
                self._phase = STATUS_IDLE
            self._on_status(STATUS_IDLE)
