"""Funnel event types.

Every step of the revenue funnel (call -> lead -> booking -> show -> paid) is recorded as an
append-only row in the `events` table. These names must match the CHECK constraint in
supabase/migrations. Metrics are computed from these events, never from mutable state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EventType(StrEnum):
    CALL_RECEIVED = "call_received"
    CALL_ANSWERED = "call_answered"
    CONSENT_GIVEN = "consent_given"
    CONSENT_DECLINED = "consent_declined"
    LEAD_CAPTURED = "lead_captured"
    QUESTION_UNANSWERED = "question_unanswered"
    EMERGENCY_DETECTED = "emergency_detected"
    HANDOFF_REQUESTED = "handoff_requested"
    CALLBACK_REQUESTED = "callback_requested"
    BOOKING_CREATED = "booking_created"
    BOOKING_CANCELLED = "booking_cancelled"
    APPOINTMENT_SHOWED = "appointment_showed"
    APPOINTMENT_NO_SHOW = "appointment_no_show"
    PAYMENT_RECORDED = "payment_recorded"
    CALL_ENDED = "call_ended"


# The headline funnel, in order. Conversion between consecutive stages is the core metric.
FUNNEL: tuple[EventType, ...] = (
    EventType.CALL_RECEIVED,
    EventType.LEAD_CAPTURED,
    EventType.BOOKING_CREATED,
    EventType.APPOINTMENT_SHOWED,
    EventType.PAYMENT_RECORDED,
)


class LeadSource(StrEnum):
    """Where the caller came from. Stored on every call and lead for attribution."""

    UNKNOWN = "unknown"
    GOOGLE_BUSINESS = "google_business"
    WEBSITE = "website"
    WHATSAPP = "whatsapp"
    REFERRAL = "referral"
    WALK_IN = "walk_in"
    ADS = "ads"
    TEST_CALL = "test_call"


class FunnelEvent(BaseModel):
    business_id: UUID
    type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    call_id: UUID | None = None
    lead_id: UUID | None = None
    appointment_id: UUID | None = None
    source: LeadSource = LeadSource.UNKNOWN
    # Revenue attached to this event (INR, paise not needed at this stage)
    value_inr: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
