"""Speech-to-Text-Backends: lokal (faster-whisper), OpenAI oder Groq Whisper API."""

from __future__ import annotations

import os
from typing import Callable, Optional

Transcriber = Callable[[str], str]


def build_transcriber(
    backend: str,
    model_size: str = "small",
    language: Optional[str] = None,
) -> Transcriber:
    backend = (backend or "local").lower()
    if backend == "openai":
        return _openai_transcriber(language=language)
    if backend == "groq":
        return _groq_transcriber(language=language)
    if backend == "local":
        return _local_transcriber(model_size=model_size, language=language)
    raise ValueError(
        f"Unbekanntes Backend: {backend!r} (erwartet 'local' | 'openai' | 'groq')"
    )


def _local_transcriber(model_size: str, language: Optional[str]) -> Transcriber:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper ist nicht installiert. Führe `pip install faster-whisper` aus."
        ) from e

    # Auf Apple Silicon CPU ist int8 der schnellste Pfad ohne Qualitätseinbußen,
    # die fürs Diktieren spürbar wären. "auto" wählt manchmal float32 — daher
    # explizit int8.
    compute_type = os.getenv("MURML_COMPUTE_TYPE", "int8")
    print(
        f"[transcriber] Lade lokales Whisper-Modell '{model_size}' "
        f"(compute_type={compute_type})…"
    )
    model = WhisperModel(model_size, device="auto", compute_type=compute_type)
    lang = language or None

    beam_size = int(os.getenv("MURML_BEAM_SIZE", "5"))
    initial_prompt = os.getenv("MURML_INITIAL_PROMPT") or None

    def transcribe(audio_path: str) -> str:
        segments, _info = model.transcribe(
            audio_path,
            language=lang,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    return transcribe


def _openai_transcriber(language: Optional[str]) -> Transcriber:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY ist nicht gesetzt. Trage ihn in deine .env ein.")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai ist nicht installiert. Führe `pip install openai` aus."
        ) from e

    client = OpenAI(api_key=api_key)
    lang = language or None
    model_id = os.getenv("MURML_OPENAI_MODEL", "whisper-1")

    def transcribe(audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            kwargs = {"model": model_id, "file": f}
            if lang:
                kwargs["language"] = lang
            resp = client.audio.transcriptions.create(**kwargs)
        return (resp.text or "").strip()

    return transcribe


def _groq_transcriber(language: Optional[str]) -> Transcriber:
    """Groq stellt Whisper hinter ein OpenAI-kompatibles SDK bereit.

    Free-Tier reicht für persönliche Nutzung locker. Modelle:
      - whisper-large-v3-turbo  (sehr schnell, sehr gut)
      - whisper-large-v3        (etwas langsamer, etwas genauer)
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY ist nicht gesetzt. Trage ihn in deine .env ein.")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai ist nicht installiert. Führe `pip install openai` aus."
        ) from e

    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    lang = language or None
    model_id = os.getenv("MURML_GROQ_MODEL", "whisper-large-v3-turbo")

    def transcribe(audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            kwargs = {"model": model_id, "file": f}
            if lang:
                kwargs["language"] = lang
            resp = client.audio.transcriptions.create(**kwargs)
        return (resp.text or "").strip()

    return transcribe
