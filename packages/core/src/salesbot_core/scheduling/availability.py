"""Availability engine: which start times can be offered.

Pure functions. The caller loads practitioner calendars (weekly hours, breaks, dated exceptions,
busy intervals) and passes `now`, so every rule is unit-testable without a database or a clock.

A start time is offered only if the whole visit fits inside working time, avoids breaks,
closures and existing holds/appointments, and starts at or after `now + min_lead`. Start times
sit on a grid that begins at each working window's start (step = the visit length unless the
business sets slot_step_minutes). The database exclusion constraint is the final guard against
double-booking; this engine only decides what to offer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from salesbot_core.scheduling.models import (
    Interval,
    PractitionerCalendar,
    Slot,
    VisitType,
    WeeklyWindow,
)

# Upper bound on how far ahead day lists and "next opening" searches go.
MAX_SCAN_DAYS = 120


def subtract(intervals: Iterable[Interval], cuts: Iterable[Interval]) -> list[Interval]:
    """Remove every cut from every interval. Result is sorted and non-overlapping per input."""
    result = sorted(intervals, key=lambda i: i.start)
    for cut in sorted(cuts, key=lambda c: c.start):
        nxt: list[Interval] = []
        for iv in result:
            if not iv.overlaps(cut):
                nxt.append(iv)
                continue
            if iv.start < cut.start:
                nxt.append(Interval(start=iv.start, end=cut.start))
            if cut.end < iv.end:
                nxt.append(Interval(start=cut.end, end=iv.end))
        result = nxt
    return result


def _day_bounds(day: date, tz: ZoneInfo) -> Interval:
    start = datetime.combine(day, datetime.min.time(), tz)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tz)
    return Interval(start=start, end=end)


def _weekly_on(day: date, windows: Sequence[WeeklyWindow], tz: ZoneInfo) -> list[Interval]:
    return [
        Interval(start=datetime.combine(day, w.start, tz), end=datetime.combine(day, w.end, tz))
        for w in windows
        if w.weekday == day.isoweekday()
    ]


def _clip(intervals: Iterable[Interval], bounds: Interval) -> list[Interval]:
    out = []
    for iv in intervals:
        start, end = max(iv.start, bounds.start), min(iv.end, bounds.end)
        if start < end:
            out.append(Interval(start=start, end=end))
    return out


def practitioner_slots(
    cal: PractitionerCalendar,
    day: date,
    *,
    visit: VisitType,
    now: datetime,
    tz: ZoneInfo,
    min_lead: timedelta,
    step_minutes: int | None = None,
) -> list[Slot]:
    """Bookable start times for one practitioner on one local calendar day."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    duration = timedelta(minutes=cal.duration_minutes(visit))
    step = timedelta(minutes=step_minutes) if step_minutes else duration
    earliest = now + min_lead
    bounds = _day_bounds(day, tz)

    working = _weekly_on(day, cal.work, tz) + _clip(cal.extra_open, bounds)
    blocked = _weekly_on(day, cal.breaks, tz) + _clip(cal.closed + cal.busy, bounds)
    free = subtract(working, blocked)

    starts: set[datetime] = set()
    for window in working:
        t = window.start
        while t + duration <= window.end:
            candidate = Interval(start=t, end=t + duration)
            if t >= earliest and any(f.contains(candidate) for f in free):
                starts.add(t)
            t += step
    return [
        Slot(practitioner_id=cal.practitioner_id, starts_at=s, ends_at=s + duration)
        for s in sorted(starts)
    ]


def slots_on_day(
    calendars: Sequence[PractitionerCalendar],
    day: date,
    *,
    visit: VisitType,
    now: datetime,
    tz: ZoneInfo,
    min_lead: timedelta,
    step_minutes: int | None = None,
) -> list[Slot]:
    """All practitioners' slots on a day, ordered by start time, then calendar order."""
    slots = [
        slot
        for cal in calendars
        for slot in practitioner_slots(
            cal, day, visit=visit, now=now, tz=tz, min_lead=min_lead, step_minutes=step_minutes
        )
    ]
    order = {cal.practitioner_id: i for i, cal in enumerate(calendars)}
    return sorted(slots, key=lambda s: (s.starts_at, order[s.practitioner_id]))


def distinct_times(slots: Iterable[Slot]) -> list[Slot]:
    """One slot per start time (the first practitioner wins). Used for 'any available'."""
    seen: dict[datetime, Slot] = {}
    for slot in slots:
        seen.setdefault(slot.starts_at, slot)
    return sorted(seen.values(), key=lambda s: s.starts_at)


def days_with_openings(
    calendars: Sequence[PractitionerCalendar],
    start_day: date,
    *,
    limit: int,
    visit: VisitType,
    now: datetime,
    tz: ZoneInfo,
    min_lead: timedelta,
    step_minutes: int | None = None,
    max_scan_days: int = MAX_SCAN_DAYS,
) -> list[date]:
    """The first `limit` days from start_day that have at least one slot."""
    found: list[date] = []
    for offset in range(max_scan_days):
        day = start_day + timedelta(days=offset)
        if slots_on_day(
            calendars,
            day,
            visit=visit,
            now=now,
            tz=tz,
            min_lead=min_lead,
            step_minutes=step_minutes,
        ):
            found.append(day)
            if len(found) >= limit:
                break
    return found


def next_opening(
    calendars: Sequence[PractitionerCalendar],
    *,
    visit: VisitType,
    now: datetime,
    tz: ZoneInfo,
    min_lead: timedelta,
    step_minutes: int | None = None,
    max_scan_days: int = MAX_SCAN_DAYS,
) -> Slot | None:
    """Earliest bookable slot across all calendars, or None within max_scan_days."""
    today = now.astimezone(tz).date()
    for offset in range(max_scan_days):
        slots = slots_on_day(
            calendars,
            today + timedelta(days=offset),
            visit=visit,
            now=now,
            tz=tz,
            min_lead=min_lead,
            step_minutes=step_minutes,
        )
        if slots:
            return slots[0]
    return None


def has_opening_within(
    calendars: Sequence[PractitionerCalendar],
    *,
    days: int,
    visit: VisitType,
    now: datetime,
    tz: ZoneInfo,
    min_lead: timedelta,
    step_minutes: int | None = None,
) -> bool:
    """False means 'nothing free in the lookahead window': offer next_opening() directly."""
    return (
        next_opening(
            calendars,
            visit=visit,
            now=now,
            tz=tz,
            min_lead=min_lead,
            step_minutes=step_minutes,
            max_scan_days=days,
        )
        is not None
    )
