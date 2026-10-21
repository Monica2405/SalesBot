"""Telephony. Plivo vs Exotel is an OPEN decision (docs/DECISIONS.md): neither is built here."""

from __future__ import annotations

from typing import Any

from salesbot_core.providers import InboundCall, TelephonyAdapter


class MockTelephony(TelephonyAdapter):
    """Records actions instead of calling a carrier."""

    name = "mock"

    def __init__(self) -> None:
        self.actions: list[tuple[str, str, str | None]] = []

    def parse_inbound(self, payload: dict[str, Any]) -> InboundCall:
        return InboundCall(
            provider_call_id=str(payload.get("call_id", "mock-call")),
            from_number=str(payload.get("from", "+910000000001")),
            to_number=str(payload.get("to", "+910000000000")),
            raw=payload,
        )

    async def transfer(self, provider_call_id: str, to_number: str) -> None:
        self.actions.append(("transfer", provider_call_id, to_number))

    async def hangup(self, provider_call_id: str) -> None:
        self.actions.append(("hangup", provider_call_id, None))

    async def start_recording(self, provider_call_id: str) -> None:
        self.actions.append(("start_recording", provider_call_id, None))


class BrowserTestCall(MockTelephony):
    """Placeholder for "Test call from browser" on the admin Setup page.

    TODO: serve a WebRTC session (Pipecat ships a small WebRTC transport) so an owner can talk
    to their configured agent without a phone number. Calls are tagged source='test_call' so
    they never pollute funnel metrics.
    """

    name = "browser"


def get_telephony(name: str) -> TelephonyAdapter:
    if name == "mock":
        return MockTelephony()
    if name == "browser":
        return BrowserTestCall()
    if name in ("plivo", "exotel"):
        raise NotImplementedError(f"{name} adapter not built: provider is an open decision")
    raise ValueError(f"unknown telephony provider {name!r}")
