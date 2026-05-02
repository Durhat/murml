"""Text in die fokussierte App einfügen via Clipboard + Cmd+V."""

from __future__ import annotations

import time

import pyperclip
from pynput.keyboard import Controller, Key

_kb = Controller()


def paste_text(text: str) -> None:
    if not text:
        return
    pyperclip.copy(text)
    time.sleep(0.05)
    with _kb.pressed(Key.cmd):
        _kb.press("v")
        _kb.release("v")