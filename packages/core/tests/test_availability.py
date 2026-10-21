import random
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from salesbot_core.scheduling import (
    Interval,
    PractitionerCalendar,
    VisitType,
    WeeklyWindow,
    days_with_openings,
    distinct_times,
    has_opening_within,
    next_opening,
    practitioner_slots,
    slots_on_day,
    subtract,
)

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 11, 2)  # a Monday
DR_A = UUID("00000000-0000-0000-0000-00000000000a")
DR_B = UUID("00000000-0000-0000-0000-00000000000b")
# "now" well before MONDAY so lead time does not interfere unless a test wants it to
EARLY = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
NO_LEAD = timedelta(0)


def ist(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), IST)


def weekdays(start: time, end: time) -> list[WeeklyWindow]:
    return [WeeklyWindow(weekday=d, start=start, end=end) for d in range(1, 7)]  # Mon-Sat


def calendar(**kw) -> PractitionerCalendar:
    base = {
        "practitioner_id": DR_A,
        "consultation_minutes": 30,
        "work": weekdays(time(10), time(12)),
    }
    base.update(kw)
    return PractitionerCalendar(**base)


def starts(slots) -> list[str]:
    return [s.starts_at.astimezone(IST).strftime("%H:%M") for s in slots]


def slots(cal, day=MONDAY, *, now=EARLY, lead=NO_LEAD, visit=VisitType.CONSULTATION, step=None):
    return practitioner_slots(
        cal, day, visit=visit, now=now, tz=IST, min_lead=lead, step_minutes=step
    )


# ---------------------------------------------------------------------------
# Basic grid, breaks, closures, busy
# ---------------------------------------------------------------------------


def test_grid_follows_visit_length_inside_working_hours():
    assert starts(slots(calendar())) == ["10:00", "10:30", "11:00", "11:30"]


def test_custom_step_gives_overlapping_offers_but_each_fits():
    assert starts(slots(calendar(), step=15)) == [
        "10:00",
        "10:15",
        "10:30",
        "10:45",
        "11:00",
        "11:15",
        "11:30",
    ]


def test_times_are_ist_and_stored_as_aware_utc_comparable():
    first = slots(calendar())[0]
    assert first.starts_at == datetime(2026, 11, 2, 4, 30, tzinfo=UTC)  # 10:00 IST


def test_no_work_on_sunday():
    assert slots(calendar(), MONDAY + timedelta(days=6)) == []


def test_break_is_skipped():
    cal = calendar(breaks=[WeeklyWindow(weekday=1, start=time(10, 30), end=time(11))])
    assert starts(slots(cal)) == ["10:00", "11:00", "11:30"]


def test_split_shift():
    cal = calendar(
        work=[
            WeeklyWindow(weekday=1, start=time(10), end=time(11)),
            WeeklyWindow(weekday=1, start=time(17), end=time(18)),
        ]
    )
    assert starts(slots(cal)) == ["10:00", "10:30", "17:00", "17:30"]


def test_holiday_closes_the_day():
    cal = calendar(closed=[Interval(start=ist(MONDAY, 0), end=ist(MONDAY + timedelta(1), 0))])
    assert slots(cal) == []


def test_partial_leave():
    cal = calendar(closed=[Interval(start=ist(MONDAY, 11), end=ist(MONDAY, 12))])
    assert starts(slots(cal)) == ["10:00", "10:30"]


def test_extra_open_hours_on_a_non_working_day():
    sunday = MONDAY + timedelta(days=6)
    cal = calendar(extra_open=[Interval(start=ist(sunday, 9), end=ist(sunday, 10))])
    assert starts(slots(cal, sunday)) == ["09:00", "09:30"]


def test_busy_appointment_blocks_and_partial_overlap_blocks_too():
    cal = calendar(busy=[Interval(start=ist(MONDAY, 10, 45), end=ist(MONDAY, 11, 15))])
    assert starts(slots(cal)) == ["10:00", "11:30"]


def test_back_to_back_is_allowed():
    cal = calendar(busy=[Interval(start=ist(MONDAY, 10), end=ist(MONDAY, 10, 30))])
    assert starts(slots(cal)) == ["10:30", "11:00", "11:30"]


def test_visit_that_does_not_fit_before_window_end_is_not_offered():
    cal = calendar(consultation_minutes=45)
    assert starts(slots(cal)) == ["10:00", "10:45"]  # 11:30 + 45 > 12:00


# ---------------------------------------------------------------------------
# First visit duration
# ---------------------------------------------------------------------------


def test_first_visit_uses_first_visit_minutes():
    cal = calendar(first_visit_minutes=60)
    assert starts(slots(cal, visit=VisitType.FIRST_VISIT)) == ["10:00", "11:00"]
    assert slots(cal, visit=VisitType.FIRST_VISIT)[0].ends_at == ist(MONDAY, 11)


def test_first_visit_falls_back_to_consultation_length():
    assert starts(slots(calendar(), visit=VisitType.FIRST_VISIT)) == starts(slots(calendar()))


# ---------------------------------------------------------------------------
# Past slots and minimum lead time
# ---------------------------------------------------------------------------


def test_never_offers_past_slots():
    now = ist(MONDAY, 10, 40)
    assert starts(slots(calendar(), now=now)) == ["11:00", "11:30"]


def test_min_lead_time():
    now = ist(MONDAY, 9, 45)
    assert starts(slots(calendar(), now=now, lead=timedelta(minutes=60))) == ["11:00", "11:30"]


def test_slot_exactly_at_lead_boundary_is_offered():
    now = ist(MONDAY, 10)
    assert starts(slots(calendar(), now=now, lead=timedelta(minutes=60)))[0] == "11:00"


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        slots(calendar(), now=datetime(2026, 11, 2, 9, 0))


# ---------------------------------------------------------------------------
# Several practitioners, day lists, next opening
# ---------------------------------------------------------------------------


def test_any_available_merges_practitioners_by_time():
    a = calendar(busy=[Interval(start=ist(MONDAY, 10), end=ist(MONDAY, 10, 30))])
    b = calendar(practitioner_id=DR_B)
    day = slots_on_day(
        [a, b], MONDAY, visit=VisitType.CONSULTATION, now=EARLY, tz=IST, min_lead=NO_LEAD
    )
    merged = distinct_times(day)
    assert starts(merged) == ["10:00", "10:30", "11:00", "11:30"]
    assert merged[0].practitioner_id == DR_B  # A is busy at 10:00
    assert merged[1].practitioner_id == DR_A  # calendar order wins when both are free


def test_days_with_openings_skips_full_days_and_respects_limit():
    full_tuesday = Interval(start=ist(MONDAY + timedelta(1), 0), end=ist(MONDAY + timedelta(2), 0))
    cal = calendar(closed=[full_tuesday])
    days = days_with_openings(
        [cal], MONDAY, limit=3, visit=VisitType.CONSULTATION, now=EARLY, tz=IST, min_lead=NO_LEAD
    )
    assert days == [MONDAY, MONDAY + timedelta(2), MONDAY + timedelta(3)]


def test_next_opening_and_lookahead():
    two_weeks_off = Interval(start=ist(MONDAY, 0), end=ist(MONDAY + timedelta(days=20), 0))
    cal = calendar(closed=[two_weeks_off])
    now = ist(MONDAY, 8)
    kw = {"visit": VisitType.CONSULTATION, "now": now, "tz": IST, "min_lead": NO_LEAD}
    assert not has_opening_within([cal], days=14, **kw)
    nxt = next_opening([cal], **kw)
    assert nxt is not None
    # Closure ends on day 20, a Sunday (no work), so the next opening is Monday day 21 at 10:00
    assert nxt.starts_at == ist(MONDAY + timedelta(days=21), 10)


def test_next_opening_none_when_nobody_works():
    cal = calendar(work=[])
    assert (
        next_opening(
            [cal],
            visit=VisitType.CONSULTATION,
            now=EARLY,
            tz=IST,
            min_lead=NO_LEAD,
            max_scan_days=30,
        )
        is None
    )


# ---------------------------------------------------------------------------
# Interval arithmetic
# ---------------------------------------------------------------------------


def test_subtract_splits_and_trims():
    whole = Interval(start=ist(MONDAY, 10), end=ist(MONDAY, 12))
    cut = Interval(start=ist(MONDAY, 10, 30), end=ist(MONDAY, 11))
    assert subtract([whole], [cut]) == [
        Interval(start=ist(MONDAY, 10), end=ist(MONDAY, 10, 30)),
        Interval(start=ist(MONDAY, 11), end=ist(MONDAY, 12)),
    ]
    assert subtract([whole], [whole]) == []


# ---------------------------------------------------------------------------
# Randomised: offered slots never overlap busy time, breaks or closures, never repeat, always
# lie inside working hours, and respect the lead time.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(200))
def test_random_calendars_never_offer_overlapping_slots(seed):
    rng = random.Random(seed)  # noqa: S311 (reproducible test data, not crypto)
    day = MONDAY + timedelta(days=rng.randrange(6))
    dur = rng.choice([10, 15, 20, 30, 45, 60])

    def rand_window(lo=7, hi=21):
        a = rng.randrange(lo * 60, hi * 60 - 15)
        b = rng.randrange(a + 15, hi * 60 + 1)
        return time(a // 60, a % 60), (time(b // 60, b % 60) if b < 24 * 60 else time(23, 59))

    def rand_interval():
        s, e = rand_window()
        return Interval(start=ist(day, s.hour, s.minute), end=ist(day, e.hour, e.minute))

    work = [
        WeeklyWindow(weekday=day.isoweekday(), start=s, end=e)
        for s, e in (rand_window() for _ in range(rng.randrange(1, 3)))
    ]
    breaks = [
        WeeklyWindow(weekday=day.isoweekday(), start=s, end=e)
        for s, e in (rand_window() for _ in range(rng.randrange(0, 2)))
    ]
    busy = [rand_interval() for _ in range(rng.randrange(0, 6))]
    closed = [rand_interval() for _ in range(rng.randrange(0, 2))]
    cal = PractitionerCalendar(
        practitioner_id=uuid4(),
        consultation_minutes=dur,
        work=work,
        breaks=breaks,
        busy=busy,
        closed=closed,
    )
    now = ist(day, rng.randrange(6, 20))
    lead = timedelta(minutes=rng.choice([0, 30, 60]))
    step = rng.choice([None, 5, 15])

    offered = practitioner_slots(
        cal, day, visit=VisitType.CONSULTATION, now=now, tz=IST, min_lead=lead, step_minutes=step
    )

    assert len({s.starts_at for s in offered}) == len(offered)
    for s in offered:
        iv = Interval(start=s.starts_at, end=s.ends_at)
        assert s.ends_at - s.starts_at == timedelta(minutes=dur)
        assert s.starts_at >= now + lead
        assert any(
            Interval(
                start=ist(day, w.start.hour, w.start.minute), end=ist(day, w.end.hour, w.end.minute)
            ).contains(iv)
            for w in work
        )
        for b in breaks:
            assert not iv.overlaps(
                Interval(
                    start=ist(day, b.start.hour, b.start.minute),
                    end=ist(day, b.end.hour, b.end.minute),
                )
            )
        for blocked in busy + closed:
            assert not iv.overlaps(blocked)
