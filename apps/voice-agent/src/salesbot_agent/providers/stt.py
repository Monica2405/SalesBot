"""Speech-to-text ("hearing"). Planned default: Sarvam Saaras."""

from __future__ import annotations

from salesbot_agent.providers import SARVAM_DOCS
from salesbot_core.packs.schema import Language
from salesbot_core.providers import STTProvider, Transcript

# 16 kHz, 16-bit mono PCM
_BYTES_PER_SECOND = 32000


class MockSTT(STTProvider):
    """Treats the 'audio' as UTF-8 text. Lets the text simulator drive the real pipeline."""

    name = "mock"

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        return Transcript(
            text=audio.decode("utf-8", errors="ignore").strip(),
            language=language,
            audio_seconds=len(audio) / _BYTES_PER_SECOND,
        )


class SarvamSTT(STTProvider):
    """TODO(sarvam): implement Saaras speech-to-text.

    - Endpoint, model name, streaming vs batch, auth header: see SARVAM_DOCS (speech-to-text).
    - Must support hi, mr, en and code-mixed speech; return the detected language.
    - Fill Transcript.audio_seconds from the request so calls.stt_seconds is accurate.
    """

    name = "sarvam"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        raise NotImplementedError(f"Sarvam STT not implemented. See {SARVAM_DOCS}")


def get_stt(name: str, api_key: str | None = None) -> STTProvider:
    if name == "mock":
        return MockSTT()
    if name == "sarvam":
        if not api_key:
            raise ValueError("STT_PROVIDER=sarvam needs SARVAM_API_KEY")
        return SarvamSTT(api_key)
    raise ValueError(f"unknown STT provider {name!r}")
