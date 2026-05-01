"""
murml: Push-to-talk Diktieren auf macOS.

Halte den konfigurierten Hotkey gedrückt (Standard: FN), sprich, lasse los.
Der erkannte Text wird in dein aktuell fokussiertes Textfeld eingefügt.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
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

    recorder = Recorder(sample_rate=sample_rate)
    history = History(max_items=history_max)

    def transcribe_not_ready(path: str) -> str:
        print("[!] Modell lädt noch — bitte ein paar Sekunden warten.")
        return ""

    engine = Engine(
        transcribe=transcribe_not_ready,
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

    print("Starte Menüleisten-App (Modell/Mikrofon werden im Hintergrund vorbereitet)…\n")

    try:
        tray = WisprTray(engine, history, hotkey_mode, hotkey_starts_enabled=False)
    except RuntimeError as e:
        msg = str(e)
        print(f"[fatal] {msg}")
        if "Tap" in msg or "Eingabe" in msg or "Bedienungs" in msg:
            instance.permissions_missing()
        return 1

    def background_bootstrap() -> None:
        try:
            if backend == "local":
                instance.starting()
            transcribe = build_transcriber(
                backend, model_size=model_size, language=language
            )
            engine._transcribe = transcribe  # type: ignore[method-assign]
            try:
                recorder.warmup_mic()
            except Exception as e:
                print(f"[recorder] Mic-Warmup: {e}")
                instance.microphone_missing()
            tray.set_hotkey_enabled(True)
            instance.ready()
        except Exception as e:
            print(f"[fatal] Start fehlgeschlagen: {e}")
            instance.notify(
                "murml",
                "Start fehlgeschlagen",
                str(e)[:120],
            )

    threading.Thread(
        target=background_bootstrap, daemon=True, name="murml-bootstrap"
    ).start()

    try:
        tray.run()
    except KeyboardInterrupt:
        print("\nBeendet.")
    except Exception as e:
        print(f"[fatal] Tray: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
