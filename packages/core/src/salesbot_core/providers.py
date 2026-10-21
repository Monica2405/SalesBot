"""Provider interfaces for the voice stack.

Every external voice service sits behind one of these. The voice agent picks implementations
from env (STT_PROVIDER, LLM_PROVIDER, TTS_PROVIDER, TELEPHONY_PROVIDER). Each result carries
usage numbers so per-call cost (stt_seconds, llm_tokens_in/out, tts_characters) is tracked.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from salesbot_core.packs.schema import Language


class Transcript(BaseModel):
    text: str
    language: Language | None = None
    audio_seconds: float = 0.0


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMResult(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class SpeechAudio(BaseModel):
    audio: bytes
    sample_rate: int = 16000
    characters: int = 0


class InboundCall(BaseModel):
    provider_call_id: str
    from_number: str
    to_number: str
    raw: dict[str, Any] = Field(default_factory=dict)


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript: ...


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, messages: list[ChatMessage]) -> LLMResult: ...


class TTSProvider(ABC):
    name: str

    @abstractmethod
    async def synthesize(self, text: str, language: Language) -> SpeechAudio: ...


class TelephonyAdapter(ABC):
    """Plivo vs Exotel is an open decision. Both must fit this interface."""

    name: str

    @abstractmethod
    def parse_inbound(self, payload: dict[str, Any]) -> InboundCall:
        """Turn a provider webhook payload into an InboundCall."""

    @abstractmethod
    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        """Warm/cold transfer to a human (used by handoff)."""

    @abstractmethod
    async def hangup(self, provider_call_id: str) -> None: ...

    @abstractmethod
    async def start_recording(self, provider_call_id: str) -> None:
        """Only called after the caller has given recording consent."""
