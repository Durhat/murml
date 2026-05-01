"""Single-Instance-Lock und Welcome-Notification.

macOS' Launch Services lassen einen Bundle-Doppelklick gerne mehrfach durch:
einmal startet der User aus ``dist/``, danach aus ``/Applications/``, oder
clickt zweimal versehentlich. Wir wollen verhindern, dass dann zwei murml-
Prozesse gleichzeitig auf das Mikrofon und denselben Hotkey-Tap gehen.

Strategie: PID-Datei in ``~/Library/Application Support/murml/murml.pid``.
Beim Start wird geprüft, ob die dort eingetragene PID noch lebt. Falls ja:
sofort beenden. Falls nein (Stale-File nach Crash): überschreiben.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


def _pid_file() -> Path:
    base = Path.home() / "Library" / "Application Support" / "murml"
    base.mkdir(parents=True, exist_ok=True)
    return base / "murml.pid"


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # Signal 0 prüft Existenz, sendet aber nichts.
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Prozess gehört zu anderem User — existiert also.
        return True
    return True


def acquire() -> bool:
    """``True``, wenn wir der einzige Prozess sind. ``False`` sonst."""
    pf = _pid_file()
    if pf.exists():
        try:
            old = int(pf.read_text().strip())
            if _is_alive(old) and old != os.getpid():
                return False
        except Exception:
            pass
    try:
        pf.write_text(str(os.getpid()))
    except Exception:
        pass
    return True


def release() -> None:
    pf = _pid_file()
    try:
        if pf.exists():
            current = pf.read_text().strip()
            if current == str(os.getpid()):
                pf.unlink()
    except Exception:
        pass


def notify(title: str, subtitle: str = "", message: str = "") -> None:
    """Banner-Notification über osascript. Funktioniert auch ohne signed Bundle."""
    parts = [f'display notification "{message}"', f'with title "{title}"']
    if subtitle:
        parts.append(f'subtitle "{subtitle}"')
    script = " ".join(parts)
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def already_running_notice() -> None:
    notify(
        title="murml läuft schon",
        subtitle="",
        message="Es gibt bereits eine laufende Instanz in der Menüleiste.",
    )


def welcome() -> None:
    notify(
        title="murml ist bereit",
        subtitle="Symbol oben rechts in der Menüleiste",
        message="FN gedrückt halten zum Diktieren.",
    )
