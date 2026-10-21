"""Calendar adapter. Google Calendar is the planned real implementation (OAuth per business)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel


class TimeSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime


class CalendarAdapter(ABC):
    name: str

    @abstractmethod
    async def busy_slots(
        self, business_id: UUID, start: datetime, end: datetime
    ) -> list[TimeSlot]: ...

    @abstractmethod
    async def create_event(self, business_id: UUID, slot: TimeSlot, title: str) -> str:
        """Create the event and return the provider's event id."""

    @abstractmethod
    async def cancel_event(self, business_id: UUID, event_id: str) -> None: ...


class MockCalendar(CalendarAdapter):
    """In-memory calendar for dev and tests."""

    name = "mock"

    def __init__(self) -> None:
        self.events: dict[str, tuple[UUID, TimeSlot, str]] = {}

    async def busy_slots(self, business_id: UUID, start: datetime, end: datetime) -> list[TimeSlot]:
        return [
            slot
            for bid, slot, _ in self.events.values()
            if bid == business_id and slot.starts_at < end and slot.ends_at > start
        ]

    async def create_event(self, business_id: UUID, slot: TimeSlot, title: str) -> str:
        event_id = f"mock-{uuid4()}"
        self.events[event_id] = (business_id, slot, title)
        return event_id

    async def cancel_event(self, business_id: UUID, event_id: str) -> None:
        self.events.pop(event_id, None)


class GoogleCalendar(CalendarAdapter):
    """TODO: implement with Google Calendar API (freebusy.query, events.insert/delete).

    Needs GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI and a per-business refresh token stored
    server-side (never in the admin app). See docs/PROVIDERS.md.
    """

    name = "google"

    async def busy_slots(self, business_id: UUID, start: datetime, end: datetime) -> list[TimeSlot]:
        raise NotImplementedError("Google Calendar adapter not built yet")

    async def create_event(self, business_id: UUID, slot: TimeSlot, title: str) -> str:
        raise NotImplementedError("Google Calendar adapter not built yet")

    async def cancel_event(self, business_id: UUID, event_id: str) -> None:
        raise NotImplementedError("Google Calendar adapter not built yet")
