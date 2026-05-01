"""Single-Instance-Lock und Notifications.

macOS' Launch Services lassen einen Bundle-Doppelklick gerne mehrfach durch:
einmal startet der User aus ``dist/``, danach aus ``/Applications/``, oder
clickt zweimal versehentlich. Wir wollen verhindern, dass dann zwei murml-
Prozesse gleichzeitig auf das Mikrofon und denselben Hotkey-Tap gehen.

Strategie: ``fcntl.flock`` auf einer Datei in
``~/Library/Application Support/murml/murml.lock``. Das OS gibt das Lock
*automatisch* frei, sobald der Prozess endet — auch bei Force Quit oder
Crash. Damit gibt es keine "stale PID files" mehr.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path
from typing import Optional, IO


def _lock_file_path() -> Path:
    base = Path.home() / "Library" / "Application Support" / "murml"
    base.mkdir(parents=True, exist_ok=True)
    return base / "murml.lock"


# Wir halten das offene File-Handle absichtlich am Leben, damit das
# fcntl-Lock bestehen bleibt, bis der Prozess endet.
_kept_lock: Optional[IO[str]] = None


def acquire() -> bool:
    """``True``, wenn wir der einzige Prozess sind. ``False`` sonst."""
    global _kept_lock
    path = _lock_file_path()
    try:
        f = open(path, "a+")
    except OSError:
        return True  # ohne Lock weiterlaufen ist besser als gar nicht starten
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return False
    try:
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
    except OSError:
        pass
    _kept_lock = f
    return True


def release() -> None:
    global _kept_lock
    if _kept_lock is not None:
        try:
            fcntl.flock(_kept_lock.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            _kept_lock.close()
        except OSError:
            pass
        _kept_lock = None


def notify(title: str, subtitle: str = "", message: str = "") -> None:
    """Banner-Notification über osascript."""
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


def starting() -> None:
    notify(
        title="murml startet",
        subtitle="Bitte einen Moment",
        message="Das Whisper-Modell wird geladen.",
    )


def ready() -> None:
    notify(
        title="murml ist bereit",
        subtitle="Symbol oben rechts in der Menüleiste",
        message="FN gedrückt halten zum Diktieren.",
    )


def permissions_missing() -> None:
    notify(
        title="murml braucht Berechtigungen",
        subtitle="Datenschutz & Sicherheit",
        message="Bitte Eingabeüberwachung und Bedienungshilfen erlauben.",
    )


def microphone_missing() -> None:
    notify(
        title="murml braucht das Mikrofon",
        subtitle="Datenschutz & Sicherheit",
        message="Bitte Mikrofonzugriff erlauben und murml neu starten.",
    )
