"""Menüleisten-App auf Basis von rumps.

Die App registriert den Hotkey am Main-RunLoop und überlässt rumps das
eigentliche Run-Looping. Kommunikation aus Hintergrund-Threads (z. B. dem
Transkriber-Thread) läuft über eine threadsichere Queue, die ein
rumps-Timer auf dem Main-Thread abarbeitet.
"""

from __future__ import annotations

import queue
import subprocess
from pathlib import Path
from typing import Callable, Optional

import Quartz
import pyperclip
import rumps

from .engine import (
    Engine,
    STATUS_IDLE,
    STATUS_ARMED,
    STATUS_RECORDING,
    STATUS_TRANSCRIBING,
)
from .history import History
from .hotkey import build_hotkey
from .indicator import LoadingIndicator

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRAY_ICON_PATH = _REPO_ROOT / "assets" / "tray-icon.png"


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
            super().__init__("\u2007", icon=icon, template=True, quit_button=None)
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

    def set_hotkey_enabled(self, enabled: bool) -> None:
        """Wird vom Bootstrap-Thread aufgerufen, sobald das Modell bereit ist."""
        self._bootstrap_done = bool(enabled)
        self._hotkey.enabled = self._bootstrap_done and not self._engine.paused

    # ── Engine→UI (laufen in beliebigen Threads, daher: Queue) ────────

    def _on_engine_status(self, status: str) -> None:
        # Title bleibt leer — das Icon zeigt die App, der Indicator den Status.
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

    def _apply_status(self, status: str, _label: str) -> None:
        # Läuft im Main-Thread (rumps-Pump) — daher dürfen wir hier
        # gefahrlos Cocoa-Aufrufe machen.
        if status == STATUS_RECORDING:
            self._indicator.show("recording")
        elif status == STATUS_TRANSCRIBING:
            self._indicator.show("transcribing")
        else:
            self._indicator.hide()

    def _toggle_pause(self, item: rumps.MenuItem) -> None:
        new_state = not self._engine.paused
        self._engine.set_paused(new_state)
        self._hotkey.enabled = (not new_state) and self._bootstrap_done
        item.title = "Fortsetzen" if new_state else "Pause"
        # Title nutzen wir nur als kleines "Pause"-Hint neben dem Icon.
        self._set_title("⏸" if new_state else "")
        self._indicator.hide()

    def _build_history_menu(self) -> None:
        # clear() schlägt fehl, wenn das Submenu noch nicht ans Hauptmenü
        # gemountet ist (NSMenu existiert dann noch nicht).
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
            sub.add(
                rumps.MenuItem(
                    "Erneut einfügen",
                    callback=lambda _i, t=text: self._paste_again(t),
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
