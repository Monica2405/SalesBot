"""Human handoff. How it works is an OPEN decision (docs/DECISIONS.md): live transfer via the
telephony provider, a WhatsApp alert to the owner, or both.

Whatever is chosen, the fallback is always the same: take a callback request so the lead is
never lost.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from salesbot_core.packs.schema import Language


class HandoffResult(BaseModel):
    connected: bool
    reason: str | None = None


class HandoffHandler(ABC):
    @abstractmethod
    async def request(self, call_id: str, reason: str) -> HandoffResult: ...


class StubHandoff(HandoffHandler):
    """Never connects, so every handoff exercises the callback fallback."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def request(self, call_id: str, reason: str) -> HandoffResult:
        self.requests.append((call_id, reason))
        return HandoffResult(connected=False, reason="handoff not configured (open decision)")


CALLBACK_MESSAGE: dict[Language, str] = {
    "en": "I could not reach the team right now. They will call you back on this number shortly.",
    "hi": "अभी टीम से संपर्क नहीं हो पाया। वे जल्द ही इसी नंबर पर आपको वापस कॉल करेंगे।",
    "mr": "आत्ता टीमशी संपर्क झाला नाही. ते लवकरच याच नंबरवर तुम्हाला परत फोन करतील.",
}
