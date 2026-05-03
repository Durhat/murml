# murml

Push-to-talk Sprach­eingabe für macOS. Globe-Taste halten, sprechen, loslassen.
Der erkannte Text wird in das fokussierte Textfeld eingefügt. Lebt als kleines
Symbol in der Menüleiste.

Lokale Transkription mit `faster-whisper`, optional Cloud-Backends (Groq,
OpenAI). Verlauf der letzten Transkriptionen lokal in der Menüleiste abrufbar.

## Voraussetzungen

- macOS (Apple Silicon empfohlen)
- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

## Installation

```bash
git clone https://github.com/Durhat/murml.git
cd murml
uv run murml
```

`uv run murml` legt bei Bedarf eine virtuelle Umgebung an, installiert die
Abhängigkeiten aus `pyproject.toml`/`uv.lock` und startet murml. Beim ersten
Lauf wird einmalig das Whisper-Modell geladen (Default `small`, ca. 460 MB).

## Als App betreiben (ohne Terminal)

```bash
./build_app.sh
cp -R dist/murml.app /Applications/
```

Das Build-Skript erzeugt ein schlankes Bundle, das beim Doppelklick
`uv run murml` im Hintergrund startet. murml erscheint anschließend nur als
Symbol in der Menüleiste — kein Dock-Icon, kein Terminal.

Damit murml automatisch beim Login startet:
**Systemeinstellungen → Allgemein → Anmeldeobjekte → +** → `murml.app` wählen.

Logs landen unter `~/Library/Logs/murml.log`. Beim ersten Start sind die
gleichen Berechtigungen wie beim Terminal-Modus zu erteilen — aber dieses
Mal für `murml.app`.

## Berechtigungen

In **Systemeinstellungen → Datenschutz & Sicherheit** muss der Prozess, der
murml startet (`murml.app`, Terminal.app, iTerm, …), folgende Rechte haben:

- **Eingabeüberwachung** — globaler Hotkey
- **Bedienungshilfen** — Cmd+V senden, Emoji-Picker öffnen
- **Mikrofon** — Audio aufnehmen (Dialog kommt automatisch)

Außerdem: **Systemeinstellungen → Tastatur → „🌐 Drücken zum:"** auf
**„Nichts ausführen"** stellen. Sonst stiehlt macOS uns das FN-Release-Event.
Den Tap der Globe-Taste bauen wir intern selbst nach.

## Bedienung

| Aktion | Effekt |
| --- | --- |
| Globe-Taste halten | Aufnahme; Loslassen → Transkription + Einfügen |
| Globe-Taste kurz tippen | Emoji-Picker (`Ctrl+Cmd+Space`) |
| Symbol in der Menüleiste | Pause, Verlauf, Beenden |
| Verlauf-Eintrag | Erneut kopieren oder einfügen |

Beenden via Menüleiste oder `Ctrl+C` im Terminal.

## Konfiguration

Alles in `.env` (Vorlage: `.env.example`).

| Variable | Default | Beschreibung |
| --- | --- | --- |
| `MURML_BACKEND` | `local` | `local`, `groq`, `openai` |
| `MURML_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` |
| `MURML_COMPUTE_TYPE` | `int8` | Quantisierung des lokalen Modells |
| `MURML_LANGUAGE` | `de` | Sprachhinweis. Leer = Auto-Detect |
| `MURML_HOTKEY` | `fn` | `fn` (Globe-Taste) oder `ralt` |
| `MURML_TAP_THRESHOLD_MS` | `250` | Tap-vs-Halten-Grenze |
| `MURML_HISTORY_MAX` | `50` | Anzahl gespeicherter Transkriptionen |

Eigene Sounds (`start.wav`, `stop.wav`, `done.wav`, `error.wav`) in `sounds/`
ablegen. Fehlt eine Datei, fällt murml auf den gleichnamigen Apple-Systemsound
in `/System/Library/Sounds/` zurück.

## Backends

`faster-whisper` läuft auf Apple Silicon CPU-only mit `int8`. Richtwerte für
10 Sekunden Audio:

| Modell | Tempo | Qualität |
| --- | --- | --- |
| tiny | < 1 s | mittel |
| base | ~ 1 s | gut |
| small | ~ 2 s | sehr gut |
| medium | ~ 5–8 s | exzellent |
| large-v3 | ~ 10–15 s | exzellent |

Für Sub-Sekunden-Antworten Groq verwenden (Free-Tier reicht für persönliche
Nutzung):

```ini
MURML_BACKEND=groq
GROQ_API_KEY=gsk_...
MURML_GROQ_MODEL=whisper-large-v3-turbo
```

API-Key: <https://console.groq.com/keys>

Der Verlauf liegt unter
`~/Library/Application Support/murml/history.json`.

## Architektur

```
murml/
  __main__.py     Entry-Point
  tray.py         Menüleisten-App (rumps)
  engine.py      Push-to-Talk-Logik (UI-agnostisch)
  hotkey.py      FN via CGEventTap, Right-Option via pynput
  recorder.py    Audio-Aufnahme (sounddevice → WAV)
  transcriber.py faster-whisper / OpenAI / Groq
  paster.py      Clipboard + Cmd+V
  history.py     Persistenter Verlauf
  sounds.py      afplay-Wrapper
```

Der Quartz-Eventtap und die rumps-App teilen sich denselben Main-RunLoop.
UI-Updates aus Hintergrund-Threads (Transkription) wandern über eine Queue
zurück auf den Main-Thread.

## Lizenz

MIT
