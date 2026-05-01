"""Persistente Speicherung der letzten Transkriptionen.

Liegt unter ~/Library/Application Support/murml/history.json.
Thread-safe: alle Operationen sind durch einen Lock geschützt.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import List


def default_path() -> Path:
    base = Path.home() / "Library" / "Application Support" / "murml"
    base.mkdir(parents=True, exist_ok=True)
    return base / "history.json"


class History:
    def __init__(self, path: Path | None = None, max_items: int = 50) -> None:
        self.path = path or default_path()
        self.max_items = max_items
        self._lock = threading.Lock()
        self._items: List[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._items = data[: self.max_items]
        except Exception as e:
            print(f"[history] Konnte {self.path} nicht laden: {e}")

    def _save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self._items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[history] Konnte {self.path} nicht speichern: {e}")

    def add(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._items.insert(
                0,
                {
                    "text": text,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                },
            )
            self._items = self._items[: self.max_items]
            self._save()

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._save()
