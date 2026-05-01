# Eigene Sounds

Lege hier WAV/AIFF/MP3-Dateien ab. murml sucht standardmäßig nach:

| Datei | Wann er gespielt wird |
| --- | --- |
| `start.wav` | FN gedrückt – Aufnahme beginnt |
| `stop.wav` | FN losgelassen – Transkription läuft |
| `done.wav` | Text wurde eingefügt |
| `error.wav` | Etwas ist schiefgelaufen |

Wenn eine Datei fehlt, fällt das Modul auf den Apple-System-Sound mit gleichem Namen
in `/System/Library/Sounds/` zurück (z. B. `Tink`, `Pop`, `Morse`, `Funk`).

## Empfehlungen für die Klanggestaltung

- **Maximal 80–100 ms** Länge für `start` und `stop`. Alles länger nervt.
- **Schneller Decay**, kein Reverb-Tail (sonst überlappen sich Sounds bei schneller Wiederholung).
- **Mono, 44,1 kHz, 16 bit WAV** ist das sauberste Format.
- **Frequenzen unter ~150 Hz vermeiden** – Bass überträgt sich sonst aufs Mikro und landet in der Aufnahme.
- Mische die Datei eher leise (Peak ~ -6 dBFS); die App regelt zusätzlich auf 40 % runter.

## Andere Datei-Namen verwenden

In `.env`:

```ini
MURML_SOUND_START=mein_start
MURML_SOUND_STOP=mein_stop
MURML_SOUND_START_VOL=0.6
```

`mein_start.wav` und `mein_stop.wav` müssen dann in diesem Ordner liegen.
