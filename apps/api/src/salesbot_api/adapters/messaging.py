"""Messaging adapter (WhatsApp). The provider is an OPEN decision (docs/DECISIONS.md)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class OutboundMessage(BaseModel):
    to: str
    template: str | None = None  # pre-approved WhatsApp template name
    text: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class MessagingAdapter(ABC):
    name: str

    @abstractmethod
    async def send(self, message: OutboundMessage) -> str:
        """Send and return the provider message id."""


class MockMessaging(MessagingAdapter):
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, message: OutboundMessage) -> str:
        self.sent.append(message)
        return f"mock-msg-{len(self.sent)}"


def get_messaging(provider: str) -> MessagingAdapter:
    if provider == "mock":
        return MockMessaging()
    # TODO: add the chosen WhatsApp provider once decided (docs/DECISIONS.md).
    raise NotImplementedError(f"WhatsApp provider {provider!r} not implemented (open decision)")
