"""Plain data for the availability engine. No database, no clock: callers pass everything in."""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class VisitType(StrEnum):
    FIRST_VISIT = "first_visit"
    CONSULTATION = "consultation"


class AppointmentStatus(StrEnum):
    """Matches the appointments.status CHECK constraint."""

    HELD = "held"
    PENDING_APPROVAL = "pending_approval"
    BOOKED = "booked"
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    SHOWED = "showed"
    NO_SHOW = "no_show"
    COMPLETED = "completed"


# Statuses that occupy the calendar. Must match the WHERE clause of appointments_no_overlap.
BLOCKING_STATUSES: frozenset[AppointmentStatus] = frozenset(
    {
        AppointmentStatus.HELD,
        AppointmentStatus.PENDING_APPROVAL,
        AppointmentStatus.BOOKED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.UNCONFIRMED,
    }
)

# Statuses a client can still confirm, cancel or reschedule.
ACTIVE_STATUSES: frozenset[AppointmentStatus] = frozenset(
    {AppointmentStatus.BOOKED, AppointmentStatus.CONFIRMED, AppointmentStatus.UNCONFIRMED}
)


class Interval(_Frozen):
    """Half-open [start, end), timezone-aware."""

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _valid(self) -> Interval:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("interval bounds must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("interval end must be after start")
        return self

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Interval) -> bool:
        return self.start <= other.start and other.end <= self.end


class WeeklyWindow(_Frozen):
    """Local wall-clock window on an ISO weekday (1 = Monday)."""

    weekday: int = Field(ge=1, le=7)
    start: time
    end: time

    @model_validator(mode="after")
    def _valid(self) -> WeeklyWindow:
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        return self


class PractitionerCalendar(_Frozen):
    practitioner_id: UUID
    consultation_minutes: int = Field(ge=5, le=480)
    first_visit_minutes: int | None = Field(default=None, ge=5, le=480)
    work: list[WeeklyWindow] = Field(default_factory=list)
    breaks: list[WeeklyWindow] = Field(default_factory=list)
    # Dated exceptions in absolute time. `closed` includes business-wide closures.
    closed: list[Interval] = Field(default_factory=list)
    extra_open: list[Interval] = Field(default_factory=list)
    # Existing holds and appointments in blocking statuses.
    busy: list[Interval] = Field(default_factory=list)

    def duration_minutes(self, visit: VisitType) -> int:
        if visit is VisitType.FIRST_VISIT and self.first_visit_minutes:
            return self.first_visit_minutes
        return self.consultation_minutes


class Slot(_Frozen):
    practitioner_id: UUID
    starts_at: datetime
    ends_at: datetime
