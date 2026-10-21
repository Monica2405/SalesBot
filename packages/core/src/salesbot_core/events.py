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
    # Appointment management (clients registered through the intake adapter)
    CLIENT_REGISTERED = "client_registered"
    WELCOME_SENT = "welcome_sent"
    BOOKING_STARTED = "booking_started"
    CONFIRMATION_SENT = "confirmation_sent"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    RESCHEDULE_REQUESTED = "reschedule_requested"
    APPOINTMENT_RESCHEDULED = "appointment_rescheduled"
    REMINDER_SENT = "reminder_sent"
    NO_RESPONSE = "no_response"
    HANDOFF_TASK_CREATED = "handoff_task_created"


# The headline funnel, in order. Conversion between consecutive stages is the core metric.
FUNNEL: tuple[EventType, ...] = (
    EventType.CALL_RECEIVED,
    EventType.LEAD_CAPTURED,
    EventType.BOOKING_CREATED,
    EventType.APPOINTMENT_SHOWED,
    EventType.PAYMENT_RECORDED,
)

# Funnel for registered clients (appointment management): registration -> show.
APPOINTMENT_FUNNEL: tuple[EventType, ...] = (
    EventType.CLIENT_REGISTERED,
    EventType.BOOKING_CREATED,
    EventType.APPOINTMENT_CONFIRMED,
    EventType.APPOINTMENT_SHOWED,
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
    REGISTRATION_FORM = "registration_form"
    # Dev-only form simulator. Excluded from metrics, like TEST_CALL.
    SIMULATION = "simulation"


class Channel(StrEnum):
    """How a funnel step happened. Matches events.channel and appointments.booked_via."""

    WHATSAPP = "whatsapp"
    VOICE = "voice"
    STAFF = "staff"
    API = "api"
    SYSTEM = "system"


class FunnelEvent(BaseModel):
    business_id: UUID
    type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    call_id: UUID | None = None
    lead_id: UUID | None = None
    appointment_id: UUID | None = None
    client_id: UUID | None = None
    channel: Channel | None = None
    # Language of the turn or message that produced this event; "other" = unsupported language.
    language: str | None = None
    source: LeadSource = LeadSource.UNKNOWN
    # Revenue attached to this event (INR, paise not needed at this stage)
    value_inr: int | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
