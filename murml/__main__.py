"""
murml: Push-to-talk Diktieren auf macOS.

Halte den konfigurierten Hotkey gedrückt (Standard: FN), sprich, lasse los.
Der erkannte Text wird in dein aktuell fokussiertes Textfeld eingefügt.
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import instance
from .engine import Engine
from .history import History
from .recorder import Recorder
from .transcriber import build_transcriber
from .tray import WisprTray


def _load_env() -> None:
    here = Path(__file__).resolve().parent.parent
    env_path = here / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def main() -> int:
    _load_env()

    if not instance.acquire():
        # Schon eine murml-Instanz aktiv – freundlich abmelden.
        instance.already_running_notice()
        print("[!] murml läuft bereits – beende mich.")
        return 0
    atexit.register(instance.release)

    backend = os.getenv("MURML_BACKEND", "local")
    model_size = os.getenv("MURML_MODEL", "small")
    language = os.getenv("MURML_LANGUAGE") or None
    sample_rate = int(os.getenv("MURML_SAMPLE_RATE", "16000"))
    hotkey_mode = os.getenv("MURML_HOTKEY", "fn")
    max_duration = float(os.getenv("MURML_MAX_RECORD_SECONDS", "0"))
    tap_threshold = float(os.getenv("MURML_TAP_THRESHOLD_MS", "250")) / 1000.0
    emoji_on_tap = os.getenv("MURML_EMOJI_ON_TAP", "on").lower() in {
        "1", "on", "true", "yes",
    }
    history_max = int(os.getenv("MURML_HISTORY_MAX", "50"))

    print("─" * 60)
    print(" murml")
    print(f"   Backend : {backend}")
    print(f"   Modell  : {model_size if backend == 'local' else backend}")
    print(f"   Sprache : {language or 'auto'}")
    print(f"   Hotkey  : {hotkey_mode}")
    print("─" * 60)

    # FRÜHE Notification: das lokale Whisper-Modell zu laden kann beim ersten
    # Mal eine ganze Weile dauern (Download). Damit der User zwischen "App
    # läuft schon" und "App hängt" unterscheiden kann, melden wir uns vorher.
    if backend == "local":
        instance.starting()

    try:
        transcribe = build_transcriber(backend, model_size=model_size, language=language)
    except Exception as e:
        print(f"[fatal] Transkriber konnte nicht gestartet werden: {e}")
        return 1

    recorder = Recorder(sample_rate=sample_rate)
    history = History(max_items=history_max)

    engine = Engine(
        transcribe=transcribe,
        recorder=recorder,
        history=history,
        tap_threshold=tap_threshold,
        emoji_on_tap=emoji_on_tap,
        max_record_seconds=max_duration,
    )

    if hotkey_mode == "fn":
        print(
            "Hinweis: Globe-Taste sollte auf 'Nichts ausführen' stehen\n"
            "         (Systemeinstellungen → Tastatur → '🌐 Drücken zum:').\n"
            f"  • kurz tippen (< {int(tap_threshold * 1000)} ms) → "
            f"{'Emoji-Picker' if emoji_on_tap else 'nichts'}\n"
            "  • halten          → Push-to-Talk\n"
        )

    print("Bereit. Symbol erscheint oben in der Menüleiste.\n")
    instance.ready()

    try:
        WisprTray(engine, history, hotkey_mode).run()
    except KeyboardInterrupt:
        print("\nBeendet.")
    except RuntimeError as e:
        # Häufigster Grund: CGEventTap ließ sich nicht erstellen (fehlende
        # Eingabeüberwachung/Bedienungshilfen). Dem User Bescheid sagen,
        # statt im Hintergrund zu sterben.
        msg = str(e)
        print(f"[fatal] {msg}")
        if "Tap" in msg or "Eingabe" in msg or "Bedienungs" in msg:
            instance.permissions_missing()
        return 1
    except Exception as e:
        print(f"[fatal] Tray: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
