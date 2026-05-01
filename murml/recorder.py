"""Mikrofonaufnahme via sounddevice → WAV-Datei."""

from __future__ import annotations

import tempfile
import threading
import wave
from typing import Optional

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._stream: Optional[sd.InputStream] = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            # Drop-outs etc. nur loggen, nicht abbrechen.
            print(f"[recorder] Stream-Status: {status}")
        with self._lock:
            self._frames.append(indata.copy())

    def start(self) -> None:
        with self._lock:
            self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(
        self,
        min_seconds: float = 0.35,
        min_rms: float = 80.0,
    ) -> Optional[str]:
        """Beendet die Aufnahme und gibt den Pfad zur WAV-Datei zurück.

        Aufnahmen, die kürzer als ``min_seconds`` sind oder im Schnitt unter
        ``min_rms`` liegen (also Stille), werden verworfen — das verhindert
        Whisper-Halluzinationen bei versehentlichem FN-Antippen.
        """
        if self._stream is None:
            return None
        self._stream.stop()
        self._stream.close()
        self._stream = None

        with self._lock:
            if not self._frames:
                return None
            data = np.concatenate(self._frames, axis=0)
            self._frames = []

        if data.size == 0:
            return None

        duration = data.shape[0] / float(self.sample_rate)
        if duration < min_seconds:
            print(f"[recorder] zu kurz ({duration:.2f}s) — verworfen")
            return None

        # int16-RMS: Stille liegt typisch unter 50, leises Sprechen ab ~150.
        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
        if rms < min_rms:
            print(f"[recorder] zu leise (rms={rms:.0f}) — verworfen")
            return None

        tmp = tempfile.NamedTemporaryFile(prefix="murml_", suffix=".wav", delete=False)
        tmp.close()
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16
            wf.setframerate(self.sample_rate)
            wf.writeframes(data.tobytes())
        return tmp.name
