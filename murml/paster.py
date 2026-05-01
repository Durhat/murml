"""Text in die fokussierte App einfügen via Clipboard + Cmd+V."""

from __future__ import annotations

import time

import pyperclip
from pynput.keyboard import Controller, Key

_kb = Controller()


def paste_text(text: str, restore_clipboard: bool = True) -> None:
    if not text:
        return

    previous: str | None = None
    if restore_clipboard:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

    pyperclip.copy(text)
    # Kurze Pause, damit das System die Zwischenablage übernommen hat,
    # bevor wir Cmd+V auslösen.
    time.sleep(0.05)

    with _kb.pressed(Key.cmd):
        _kb.press("v")
        _kb.release("v")

    if restore_clipboard and previous is not None:
        # Erst nach dem Paste die alte Clipboard-Hist wiederherstellen.
        time.sleep(0.15)
        try:
            pyperclip.copy(previous)
        except Exception:
            pass
