"""Menüleisten-App auf Basis von rumps.

Die App registriert den Hotkey am Main-RunLoop und überlässt rumps das
eigentliche Run-Looping. Kommunikation aus Hintergrund-Threads (z. B. dem
Transkriber-Thread) läuft über eine threadsichere Queue, die ein
rumps-Timer auf dem Main-Thread abarbeitet.
"""

from __future__ import annotations

import math
import queue
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from AppKit import NSImage
import Quartz
import pyperclip
import rumps

from .engine import (
    Engine,
    STATUS_RECORDING,
    STATUS_TRANSCRIBING,
)
from .history import History
from .hotkey import build_hotkey
from .indicator import LoadingIndicator
from .tray_spinner import transcribing_spinner_nsimage, transcribing_theta_at

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRAY_ICON_PATH = _REPO_ROOT / "assets" / "tray-icon.png"
_TRAY_ICON_REC_PATH = _REPO_ROOT / "assets" / "tray-icon-rec.png"

_REC_PULSE_PERIOD_S = 1.24
_REC_PULSE_ALPHA_MIN = 0.52
_REC_PULSE_ALPHA_MAX = 1.0
_REC_PULSE_FPS = 24.0
_TRANSC_SPIN_FPS = 24.0


def _icon_path() -> Optional[str]:
    return str(_TRAY_ICON_PATH) if _TRAY_ICON_PATH.exists() else None

_MAX_HISTORY_LABEL = 60  # Zeichen für die Menü-Anzeige eines Eintrags


def _truncate(text: str, n: int = _MAX_HISTORY_LABEL) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


class WisprTray(rumps.App):
    def __init__(
        self,
        engine: Engine,
        history: History,
        hotkey_mode: str,
        hotkey_starts_enabled: bool = True,
    ) -> None:
        # Template-Image (assets/tray-icon.png): passt sich Hell/Dunkel an.
        # „Figure space“ (U+2007): minimale Breite fürs Klick-Ziel neben dem
        # Icon — reiner Leerstring kann unter macOS das Aufklappen des Menüs
        # verhindern.
        icon = _icon_path()
        if icon is not None:
            super().__init__("\u2007", icon=icon, template=False, quit_button=None)
        else:
            super().__init__("◉", quit_button=None)
        self._engine = engine
        self._history = history
        self._tasks: queue.Queue[Callable[[], None]] = queue.Queue()
        self._indicator = LoadingIndicator()
        self._bootstrap_done = hotkey_starts_enabled

        # Engine-Callbacks ins Tray weiterleiten.
        engine._on_status = self._on_engine_status  # type: ignore[attr-defined]
        engine._on_history_change = self._on_engine_history  # type: ignore[attr-defined]

        # Menü statisch initialisieren; History-Submenü wird dynamisch befüllt.
        self._pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self._history_menu = rumps.MenuItem("Verlauf")

        self.menu = [
            self._pause_item,
            None,
            self._history_menu,
            rumps.MenuItem("Verlauf-Datei öffnen", callback=self._open_history_file),
            rumps.MenuItem("Verlauf leeren", callback=self._clear_history),
            None,
            rumps.MenuItem("Beenden", callback=self._quit),
        ]
        # Erst NACH dem Setzen von self.menu existiert die NSMenu hinter dem
        # History-Submenü; jetzt können wir sie sicher befüllen.
        self._build_history_menu()

        # Hotkey nach App-Init am Main-RunLoop hängen.
        self._hotkey = build_hotkey(
            hotkey_mode, on_press=engine.on_press, on_release=engine.on_release
        )
        self._hotkey.enabled = hotkey_starts_enabled
        self._hotkey.attach(Quartz.CFRunLoopGetMain())

        # Main-Thread-Pump für UI-Updates aus Background-Threads.
        self._pump = rumps.Timer(self._drain_tasks, 0.15)
        self._pump.start()
        self._rec_pulse_t0 = 0.0
        self._recording_pulse = rumps.Timer(
            self._recording_pulse_tick, 1.0 / _REC_PULSE_FPS
        )
        self._trans_spin_t0 = 0.0
        self._transcribing_spin = rumps.Timer(
            self._transcribing_spin_tick, 1.0 / _TRANSC_SPIN_FPS
        )

    def set_hotkey_enabled(self, enabled: bool) -> None:
        """Wird vom Bootstrap-Thread aufgerufen, sobald das Modell bereit ist."""
        self._bootstrap_done = bool(enabled)
        self._hotkey.enabled = self._bootstrap_done and not self._engine.paused

    # ── Engine→UI (laufen in beliebigen Threads, daher: Queue) ────────

    def _on_engine_status(self, status: str) -> None:
        self._tasks.put(lambda s=status: self._apply_status(s, ""))

    def _on_engine_history(self) -> None:
        self._tasks.put(self._build_history_menu)

    def _drain_tasks(self, _sender) -> None:
        while True:
            try:
                fn = self._tasks.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as e:
                print(f"[tray] task error: {e}")

    # ── Menü-Aktionen ─────────────────────────────────────────────────

    def _set_title(self, title: str) -> None:
        self.title = title

    def _set_status_bar_image(self, image: Optional[NSImage]) -> None:
        """Nutzt denselben NSStatusItem wie rumps (Delegate ``_nsapp``)."""
        nsapp = getattr(self, "_nsapp", None)
        if nsapp is None or image is None:
            return
        item = nsapp.nsstatusitem
        image.setSize_((20, 20))
        item.setImage_(image)

    def _status_bar_button(self):
        nsapp = getattr(self, "_nsapp", None)
        if nsapp is None:
            return None
        item = nsapp.nsstatusitem
        if not hasattr(item, "button"):
            return None
        return item.button()

    def _stop_recording_pulse(self) -> None:
        if self._recording_pulse.is_alive():
            self._recording_pulse.stop()
        btn = self._status_bar_button()
        if btn is not None:
            btn.setAlphaValue_(1.0)

    def _start_recording_pulse(self) -> None:
        self._rec_pulse_t0 = time.monotonic()
        btn = self._status_bar_button()
        if btn is None:
            return
        btn.setAlphaValue_(_REC_PULSE_ALPHA_MAX)
        if not self._recording_pulse.is_alive():
            self._recording_pulse.start()

    def _recording_pulse_tick(self, _timer: rumps.Timer) -> None:
        if self._engine.status() != STATUS_RECORDING:
            self._stop_recording_pulse()
            return
        btn = self._status_bar_button()
        if btn is None:
            return
        phase = (time.monotonic() - self._rec_pulse_t0) / _REC_PULSE_PERIOD_S
        w = 0.5 + 0.5 * math.sin(phase * math.tau)
        alpha = _REC_PULSE_ALPHA_MIN + (_REC_PULSE_ALPHA_MAX - _REC_PULSE_ALPHA_MIN) * w
        btn.setAlphaValue_(alpha)

    def _stop_transcribing_spin(self) -> None:
        if self._transcribing_spin.is_alive():
            self._transcribing_spin.stop()

    def _refresh_transcribing_tray_icon(self) -> None:
        if self._engine.status() != STATUS_TRANSCRIBING:
            return
        elapsed = time.monotonic() - self._trans_spin_t0
        theta = transcribing_theta_at(elapsed)
        image = transcribing_spinner_nsimage(theta)
        image.setTemplate_(True)
        self._set_status_bar_image(image)

    def _start_transcribing_spin(self) -> None:
        self._trans_spin_t0 = time.monotonic()
        btn = self._status_bar_button()
        if btn is not None:
            btn.setAlphaValue_(1.0)
        self._refresh_transcribing_tray_icon()
        if not self._transcribing_spin.is_alive():
            self._transcribing_spin.start()

    def _transcribing_spin_tick(self, _timer: rumps.Timer) -> None:
        if self._engine.status() != STATUS_TRANSCRIBING:
            self._stop_transcribing_spin()
            return
        self._refresh_transcribing_tray_icon()

    def _apply_status(self, status: str, _label: str) -> None:
        if status == STATUS_RECORDING:
            self._stop_transcribing_spin()
            self._indicator.show("recording")
            if _TRAY_ICON_REC_PATH.exists():
                image = NSImage.alloc().initWithContentsOfFile_(
                    str(_TRAY_ICON_REC_PATH)
                )
                if image is None:
                    return
                image.setTemplate_(False)
                self._set_status_bar_image(image)
                self._start_recording_pulse()
        elif status == STATUS_TRANSCRIBING:
            self._stop_recording_pulse()
            self._indicator.show("transcribing")
            self._start_transcribing_spin()
        else:
            self._stop_recording_pulse()
            self._stop_transcribing_spin()
            self._indicator.hide()
            if _TRAY_ICON_PATH.exists():
                image = NSImage.alloc().initWithContentsOfFile_(
                    str(_TRAY_ICON_PATH)
                )
                if image is None:
                    return
                image.setTemplate_(True)
                self._set_status_bar_image(image)

    def _toggle_pause(self, item: rumps.MenuItem) -> None:
        new_state = not self._engine.paused
        self._engine.set_paused(new_state)
        self._hotkey.enabled = (not new_state) and self._bootstrap_done
        item.title = "Fortsetzen" if new_state else "Pause"
        self._set_title("⏸" if new_state else "")
        self._indicator.hide()

    def _build_history_menu(self) -> None:
        try:
            self._history_menu.clear()
        except Exception:
            pass
        items = self._history.all()
        if not items:
            self._history_menu.add(rumps.MenuItem("(noch leer)"))
            return
        for entry in items:
            label = _truncate(entry.get("text", ""))
            text = entry.get("text", "")
            ts = entry.get("ts", "")
            sub = rumps.MenuItem(label)
            sub.add(
                rumps.MenuItem(
                    f"In Zwischenablage kopieren  ({ts})",
                    callback=lambda _i, t=text: pyperclip.copy(t),
                )
            )
            self._history_menu.add(sub)

    def _paste_again(self, text: str) -> None:
        from .paster import paste_text

        paste_text(text)

    def _open_history_file(self, _sender: rumps.MenuItem) -> None:
        try:
            subprocess.Popen(["open", str(self._history.path)])
        except Exception as e:
            rumps.alert("Konnte Verlaufsdatei nicht öffnen", str(e))

    def _clear_history(self, _sender: rumps.MenuItem) -> None:
        if rumps.alert(
            "Verlauf löschen?",
            "Alle gespeicherten Transkriptionen werden entfernt.",
            ok="Löschen",
            cancel="Abbrechen",
        ) == 1:
            self._history.clear()
            self._build_history_menu()

    def _quit(self, _sender: rumps.MenuItem) -> None:
        rumps.quit_application()
