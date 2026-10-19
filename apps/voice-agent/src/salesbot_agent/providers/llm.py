"""LLM ("thinking"). Planned default: Sarvam-30B."""

from __future__ import annotations

from salesbot_agent.providers import SARVAM_DOCS
from salesbot_core.providers import ChatMessage, LLMProvider, LLMResult


class MockLLM(LLMProvider):
    """Deterministic replies so tests and the simulator never need a network or a key."""

    name = "mock"

    async def complete(self, messages: list[ChatMessage]) -> LLMResult:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = f"Thank you. I have noted: {last_user}" if last_user else "Thank you."
        tokens_in = sum(len(m.content.split()) for m in messages)
        return LLMResult(text=text, tokens_in=tokens_in, tokens_out=len(text.split()))


class SarvamLLM(LLMProvider):
    """TODO(sarvam): implement the Sarvam-30B chat model.

    - Model id, endpoint, request/response shape and streaming: see SARVAM_DOCS (chat).
    - Return real usage numbers in LLMResult.tokens_in / tokens_out (cost tracking).
    """

    name = "sarvam"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def complete(self, messages: list[ChatMessage]) -> LLMResult:
        raise NotImplementedError(f"Sarvam LLM not implemented. See {SARVAM_DOCS}")


def get_llm(name: str, api_key: str | None = None) -> LLMProvider:
    if name == "mock":
        return MockLLM()
    if name == "sarvam":
        if not api_key:
            raise ValueError("LLM_PROVIDER=sarvam needs SARVAM_API_KEY")
        return SarvamLLM(api_key)
    raise ValueError(f"unknown LLM provider {name!r}")
