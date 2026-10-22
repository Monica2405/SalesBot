"""Appointment scheduling shared by the API, the flow engine and the voice agent.

Generic: no industry knowledge. A clinic calls clients "patients" and practitioners "doctors";
that vocabulary lives in packs.
"""

from salesbot_core.scheduling.availability import (
    days_with_openings,
    distinct_times,
    has_opening_within,
    next_opening,
    practitioner_slots,
    slots_on_day,
    subtract,
)
from salesbot_core.scheduling.models import (
    ACTIVE_STATUSES,
    BLOCKING_STATUSES,
    AppointmentStatus,
    Interval,
    PractitionerCalendar,
    Scope,
    Slot,
    VisitType,
    WeeklyWindow,
)
from salesbot_core.scheduling.settings import SchedulingSettings

__all__ = [
    "ACTIVE_STATUSES",
    "BLOCKING_STATUSES",
    "AppointmentStatus",
    "Interval",
    "PractitionerCalendar",
    "SchedulingSettings",
    "Scope",
    "Slot",
    "VisitType",
    "WeeklyWindow",
    "days_with_openings",
    "distinct_times",
    "has_opening_within",
    "next_opening",
    "practitioner_slots",
    "slots_on_day",
    "subtract",
]
