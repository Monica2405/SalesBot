"""Text-to-speech ("voice"). Planned default: Sarvam Bulbul."""

from __future__ import annotations

from salesbot_agent.providers import SARVAM_DOCS
from salesbot_core.packs.schema import Language
from salesbot_core.providers import SpeechAudio, TTSProvider


class MockTTS(TTSProvider):
    """Returns 100 ms of silence per character so durations look plausible."""

    name = "mock"

    async def synthesize(self, text: str, language: Language) -> SpeechAudio:
        return SpeechAudio(audio=b"\x00\x00" * 1600 * len(text), characters=len(text))


class SarvamTTS(TTSProvider):
    """TODO(sarvam): implement Bulbul text-to-speech.

    - Endpoint, model/voice names, language codes, sample rate: see SARVAM_DOCS (text-to-speech).
    - Set SpeechAudio.characters to what Sarvam bills on (cost tracking).
    """

    name = "sarvam"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def synthesize(self, text: str, language: Language) -> SpeechAudio:
        raise NotImplementedError(f"Sarvam TTS not implemented. See {SARVAM_DOCS}")


def get_tts(name: str, api_key: str | None = None) -> TTSProvider:
    if name == "mock":
        return MockTTS()
    if name == "sarvam":
        if not api_key:
            raise ValueError("TTS_PROVIDER=sarvam needs SARVAM_API_KEY")
        return SarvamTTS(api_key)
    raise ValueError(f"unknown TTS provider {name!r}")
