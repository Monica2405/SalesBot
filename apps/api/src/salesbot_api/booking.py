"""Booking logic (placeholder).

TODO: real slot finding = business hours (businesses.settings) minus calendar busy slots minus
existing appointments, sized by the pack service's duration_minutes, in the business timezone.
Every booking must write an appointments row and a `booking_created` funnel event.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from salesbot_api.adapters.calendar import TimeSlot


def slot_for_service(starts_at: datetime, duration_minutes: int) -> TimeSlot:
    return TimeSlot(starts_at=starts_at, ends_at=starts_at + timedelta(minutes=duration_minutes))


def overlaps(a: TimeSlot, b: TimeSlot) -> bool:
    return a.starts_at < b.ends_at and b.starts_at < a.ends_at
