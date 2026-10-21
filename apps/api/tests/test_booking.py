"""Booking engine against a real Postgres (Supabase local in CI). Marked `db`."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg import errors
from psycopg.rows import dict_row

from salesbot_api import booking
from salesbot_api.records import Actor, enqueue_job
from salesbot_core.events import Channel
from salesbot_core.scheduling import VisitType

pytestmark = pytest.mark.db

IST = ZoneInfo("Asia/Kolkata")
# A fixed Monday far from today. Booking functions take `now` as a parameter, so these tests
# never depend on the real clock.
MONDAY = date(2030, 1, 7)


def ist(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), IST)


NOW = ist(MONDAY, 8)  # 08:00 IST on the Monday; first offered slot is 10:00
PATIENT = Actor(type="client", channel=Channel.WHATSAPP, language="hi")
STAFF = Actor(type="staff", channel=Channel.STAFF)
ANY = booking.Scope()


def _appt(conn, appointment_id):
    return conn.execute(
        "select * from public.appointments where id = %s", (appointment_id,)
    ).fetchone()


def _events(conn, clinic, kind):
    return conn.execute(
        "select * from public.events where business_id = %s and type = %s",
        (clinic.business_id, kind),
    ).fetchall()


def _book(conn, clinic, starts_at, *, client_id=None, scope=ANY, actor=PATIENT, now=NOW):
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=client_id or clinic.client_id,
        starts_at=starts_at,
        scope=scope,
        actor=actor,
        now=now,
    )
    return booking.book_hold(conn, clinic.business_id, hold["id"], actor=actor, now=now)


def _raw_insert(conn, clinic, practitioner, start, minutes=30, status="booked"):
    return conn.execute(
        "insert into public.appointments (business_id, practitioner_id, client_id, starts_at, "
        "ends_at, status) values (%s, %s, %s, %s, %s, %s) returning id",
        (
            clinic.business_id,
            practitioner,
            clinic.client_id,
            start,
            start + timedelta(minutes=minutes),
            status,
        ),
    ).fetchone()["id"]


# ---------------------------------------------------------------------------
# The database itself refuses double-booking
# ---------------------------------------------------------------------------


def test_exclusion_constraint_rejects_overlap(conn, clinic):
    _raw_insert(conn, clinic, clinic.dr_a, ist(MONDAY, 10))
    with pytest.raises(errors.ExclusionViolation):
        _raw_insert(conn, clinic, clinic.dr_a, ist(MONDAY, 10, 15))
    # Another practitioner, back-to-back, and non-blocking statuses are all fine
    _raw_insert(conn, clinic, clinic.dr_b, ist(MONDAY, 10, 15))
    _raw_insert(conn, clinic, clinic.dr_a, ist(MONDAY, 10, 30))
    _raw_insert(conn, clinic, clinic.dr_a, ist(MONDAY, 10), status="cancelled")


def test_concurrent_inserts_one_wins(db_url, conn, clinic):
    """Two transactions insert overlapping rows; the second waits for the first, then fails."""
    first = psycopg.connect(db_url, row_factory=dict_row)
    second = psycopg.connect(db_url, row_factory=dict_row)
    try:
        _raw_insert(first, clinic, clinic.dr_a, ist(MONDAY, 10))  # uncommitted
        outcome: dict[str, object] = {}

        def run_second():
            try:
                _raw_insert(second, clinic, clinic.dr_a, ist(MONDAY, 10, 10))
                second.commit()
                outcome["result"] = "inserted"
            except errors.ExclusionViolation:
                second.rollback()
                outcome["result"] = "rejected"

        t = threading.Thread(target=run_second)
        t.start()
        t.join(timeout=1)
        assert t.is_alive(), "second insert should block on the first transaction"
        first.commit()
        t.join(timeout=10)
        assert outcome["result"] == "rejected"
    finally:
        first.close()
        second.close()


def test_many_clients_racing_for_one_slot_get_exactly_one_hold(db_url, clinic):
    scope = booking.Scope(practitioner_id=clinic.dr_a)
    start = ist(MONDAY, 10)
    barrier = threading.Barrier(8)

    def attempt(_):
        with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
            barrier.wait()
            try:
                booking.hold_slot(
                    c,
                    clinic.business_id,
                    client_id=clinic.client_id,
                    starts_at=start,
                    scope=scope,
                    actor=PATIENT,
                    now=NOW,
                )
                return "held"
            except booking.SlotUnavailableError:
                return "taken"

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("held") == 1
    assert results.count("taken") == 7


# ---------------------------------------------------------------------------
# Hold -> book
# ---------------------------------------------------------------------------


def test_hold_then_book_writes_event_and_audit(conn, clinic):
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 10),
        scope=ANY,
        actor=PATIENT,
        now=NOW,
    )
    assert hold["status"] == "held"
    assert hold["hold_expires_at"] == NOW + timedelta(minutes=5)
    assert _events(conn, clinic, "booking_created") == []  # nothing until the booking commits

    booked = booking.book_hold(
        conn,
        clinic.business_id,
        hold["id"],
        actor=PATIENT,
        now=NOW,
        client_message="Your booking is done.",
    )
    assert booked["status"] == "booked"
    assert booked["hold_expires_at"] is None
    [event] = _events(conn, clinic, "booking_created")
    assert (event["channel"], event["language"]) == ("whatsapp", "hi")
    audit = conn.execute(
        "select * from public.audit_log where entity_id = %s", (hold["id"],)
    ).fetchall()
    assert [a["action"] for a in audit] == ["booked"]
    assert audit[0]["client_message"] == "Your booking is done."


def test_first_visit_uses_longer_duration(conn, clinic):
    appt = _book(conn, clinic, ist(MONDAY, 10), scope=booking.Scope(visit=VisitType.FIRST_VISIT))
    assert appt["ends_at"] - appt["starts_at"] == timedelta(minutes=45)
    assert appt["visit_type"] == "first_visit"


def test_expired_hold_cannot_be_booked_and_frees_the_slot(conn, clinic):
    scope = booking.Scope(practitioner_id=clinic.dr_a)
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 10),
        scope=scope,
        actor=PATIENT,
        now=NOW,
    )
    later = NOW + timedelta(minutes=6)
    with pytest.raises(booking.HoldExpiredError):
        booking.book_hold(conn, clinic.business_id, hold["id"], actor=PATIENT, now=later)
    assert _appt(conn, hold["id"]) is None
    # Someone else can take it now
    _book(conn, clinic, ist(MONDAY, 10), client_id=clinic.other_client_id, scope=scope, now=later)


def test_expired_hold_does_not_block_a_new_hold(conn, clinic):
    scope = booking.Scope(practitioner_id=clinic.dr_a)
    booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 10),
        scope=scope,
        actor=PATIENT,
        now=NOW,
    )
    later = NOW + timedelta(minutes=6)
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.other_client_id,
        starts_at=ist(MONDAY, 10),
        scope=scope,
        actor=PATIENT,
        now=later,
    )
    assert hold["client_id"] == clinic.other_client_id


def test_live_hold_blocks_others(conn, clinic):
    scope = booking.Scope(practitioner_id=clinic.dr_a)
    booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 10),
        scope=scope,
        actor=PATIENT,
        now=NOW,
    )
    with pytest.raises(booking.SlotUnavailableError):
        booking.hold_slot(
            conn,
            clinic.business_id,
            client_id=clinic.other_client_id,
            starts_at=ist(MONDAY, 10),
            scope=scope,
            actor=PATIENT,
            now=NOW,
        )


def test_any_available_falls_through_to_the_next_practitioner(conn, clinic):
    first = _book(conn, clinic, ist(MONDAY, 10))
    second = _book(conn, clinic, ist(MONDAY, 10), client_id=clinic.other_client_id)
    assert {first["practitioner_id"], second["practitioner_id"]} == {clinic.dr_a, clinic.dr_b}
    with pytest.raises(booking.SlotUnavailableError):
        _book(conn, clinic, ist(MONDAY, 10))


@pytest.mark.parametrize(
    "starts_at",
    [
        ist(MONDAY, 7),  # before NOW (past)
        ist(MONDAY, 8, 30),  # before opening hours
        ist(MONDAY, 11, 30),  # break
        ist(MONDAY, 10, 10),  # off the grid
        ist(MONDAY, 13),  # after hours
    ],
)
def test_unofferable_times_are_refused(conn, clinic, starts_at):
    with pytest.raises(booking.SlotUnavailableError):
        _book(conn, clinic, starts_at)


def test_lead_time(conn, clinic):
    with pytest.raises(booking.SlotUnavailableError):
        _book(conn, clinic, ist(MONDAY, 10), now=ist(MONDAY, 9, 30))
    _book(conn, clinic, ist(MONDAY, 10, 30), now=ist(MONDAY, 9, 30))


# ---------------------------------------------------------------------------
# Availability from the DB
# ---------------------------------------------------------------------------


def test_open_slots_and_days_respect_bookings_and_holidays(conn, clinic):
    _book(conn, clinic, ist(MONDAY, 10), scope=booking.Scope(practitioner_id=clinic.dr_a))
    times = booking.open_slots(
        conn,
        clinic.business_id,
        day=MONDAY,
        scope=booking.Scope(practitioner_id=clinic.dr_a),
        now=NOW,
    )
    assert [s.starts_at for s in times] == [
        ist(MONDAY, h, m) for h, m in ((10, 30), (11, 0), (12, 0), (12, 30))
    ]
    # Business-wide holiday on Tuesday
    conn.execute(
        "insert into public.schedule_exceptions (business_id, kind, starts_at, ends_at) "
        "values (%s, 'closed', %s, %s)",
        (clinic.business_id, ist(MONDAY + timedelta(1), 0), ist(MONDAY + timedelta(2), 0)),
    )
    days = booking.open_days(conn, clinic.business_id, scope=ANY, now=NOW, limit=3)
    assert days == [MONDAY, MONDAY + timedelta(2), MONDAY + timedelta(3)]


def test_first_opening_reports_lookahead(conn, clinic):
    conn.execute(
        "insert into public.schedule_exceptions (business_id, kind, starts_at, ends_at) "
        "values (%s, 'closed', %s, %s)",
        (clinic.business_id, ist(MONDAY, 0), ist(MONDAY + timedelta(days=20), 0)),
    )
    slot, within = booking.first_opening(conn, clinic.business_id, scope=ANY, now=NOW)
    assert slot is not None and not within
    assert slot.starts_at == ist(MONDAY + timedelta(days=21), 10)


# ---------------------------------------------------------------------------
# Reschedule, confirm, cancel
# ---------------------------------------------------------------------------


def _queue_reminder(conn, clinic, appt):
    return enqueue_job(
        conn,
        business_id=clinic.business_id,
        kind="reminder",
        run_at=appt["starts_at"] - timedelta(hours=2),
        appointment_id=appt["id"],
        dedupe_key=f"reminder:{appt['id']}:2h",
    )


def test_reschedule_keeps_original_until_booked_then_moves_atomically(conn, clinic):
    original = _book(conn, clinic, ist(MONDAY, 10))
    job_id = _queue_reminder(conn, clinic, original)

    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY + timedelta(1), 12),
        scope=ANY,
        actor=PATIENT,
        now=NOW,
        reschedule_of=original["id"],
    )
    assert hold["practitioner_id"] == original["practitioner_id"]  # same practitioner by default
    assert _appt(conn, original["id"])["status"] == "booked"  # untouched while held

    new = booking.book_hold(conn, clinic.business_id, hold["id"], actor=PATIENT, now=NOW)
    old = _appt(conn, original["id"])
    assert new["status"] == "booked"
    assert new["rescheduled_from_id"] == original["id"]
    assert (old["status"], old["rescheduled_to_id"]) == ("rescheduled", new["id"])
    job = conn.execute("select status from public.jobs where id = %s", (job_id,)).fetchone()
    assert job["status"] == "cancelled"
    assert len(_events(conn, clinic, "appointment_rescheduled")) == 1
    # The old time is free again
    _book(
        conn,
        clinic,
        ist(MONDAY, 10),
        client_id=clinic.other_client_id,
        scope=booking.Scope(practitioner_id=original["practitioner_id"]),
    )


def test_abandoned_reschedule_leaves_original_alone(conn, clinic):
    original = _book(conn, clinic, ist(MONDAY, 10))
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 12),
        scope=ANY,
        actor=PATIENT,
        now=NOW,
        reschedule_of=original["id"],
    )
    booking.release_hold(conn, clinic.business_id, hold["id"])
    assert _appt(conn, original["id"])["status"] == "booked"
    assert _appt(conn, hold["id"]) is None


def test_reschedule_with_staff_approval(conn, clinic):
    conn.execute(
        "update public.scheduling_settings set reschedule_approval = 'staff' "
        "where business_id = %s",
        (clinic.business_id,),
    )
    original = _book(conn, clinic, ist(MONDAY, 10))
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 12),
        scope=ANY,
        actor=PATIENT,
        now=NOW,
        reschedule_of=original["id"],
    )
    pending = booking.book_hold(conn, clinic.business_id, hold["id"], actor=PATIENT, now=NOW)
    assert pending["status"] == "pending_approval"
    assert _appt(conn, original["id"])["status"] == "booked"
    assert len(_events(conn, clinic, "reschedule_requested")) == 1

    moved = booking.decide_reschedule(
        conn, clinic.business_id, hold["id"], approve=True, actor=STAFF, now=NOW
    )
    assert moved["status"] == "booked"
    assert _appt(conn, original["id"])["status"] == "rescheduled"


def test_rejected_reschedule_keeps_original(conn, clinic):
    conn.execute(
        "update public.scheduling_settings set reschedule_approval = 'staff' "
        "where business_id = %s",
        (clinic.business_id,),
    )
    original = _book(conn, clinic, ist(MONDAY, 10))
    hold = booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 12),
        scope=ANY,
        actor=PATIENT,
        now=NOW,
        reschedule_of=original["id"],
    )
    booking.book_hold(conn, clinic.business_id, hold["id"], actor=PATIENT, now=NOW)
    rejected = booking.decide_reschedule(
        conn, clinic.business_id, hold["id"], approve=False, actor=STAFF, now=NOW
    )
    assert rejected["status"] == "cancelled"
    assert _appt(conn, original["id"])["status"] == "booked"


def test_cannot_reschedule_someone_elses_appointment(conn, clinic):
    original = _book(conn, clinic, ist(MONDAY, 10))
    with pytest.raises(booking.InvalidStateError):
        booking.hold_slot(
            conn,
            clinic.business_id,
            client_id=clinic.other_client_id,
            starts_at=ist(MONDAY, 12),
            scope=ANY,
            actor=PATIENT,
            now=NOW,
            reschedule_of=original["id"],
        )


def test_confirm_is_idempotent_and_stops_confirmation_jobs(conn, clinic):
    appt = _book(conn, clinic, ist(MONDAY, 10))
    nudge = enqueue_job(
        conn,
        business_id=clinic.business_id,
        kind="confirmation_nudge",
        run_at=NOW,
        appointment_id=appt["id"],
    )
    reminder = _queue_reminder(conn, clinic, appt)
    booking.confirm(conn, clinic.business_id, appt["id"], actor=PATIENT, now=NOW)
    again = booking.confirm(conn, clinic.business_id, appt["id"], actor=PATIENT, now=NOW)
    assert again["status"] == "confirmed"
    assert len(_events(conn, clinic, "appointment_confirmed")) == 1
    statuses = {
        r["id"]: r["status"]
        for r in conn.execute(
            "select id, status from public.jobs where appointment_id = %s", (appt["id"],)
        )
    }
    assert statuses == {nudge: "cancelled", reminder: "queued"}  # reminders still go out


def test_cancel_frees_slot_and_stops_reminders(conn, clinic):
    appt = _book(conn, clinic, ist(MONDAY, 10), scope=booking.Scope(practitioner_id=clinic.dr_a))
    job_id = _queue_reminder(conn, clinic, appt)
    booking.cancel(conn, clinic.business_id, appt["id"], actor=PATIENT, now=NOW)
    assert _appt(conn, appt["id"])["status"] == "cancelled"
    assert (
        conn.execute("select status from public.jobs where id = %s", (job_id,)).fetchone()["status"]
        == "cancelled"
    )
    with pytest.raises(booking.InvalidStateError):
        booking.cancel(conn, clinic.business_id, appt["id"], actor=PATIENT, now=NOW)
    _book(
        conn,
        clinic,
        ist(MONDAY, 10),
        client_id=clinic.other_client_id,
        scope=booking.Scope(practitioner_id=clinic.dr_a),
    )


def test_other_business_ids_are_not_found(conn, clinic):
    appt = _book(conn, clinic, ist(MONDAY, 10))
    with pytest.raises(booking.NotFoundError):
        booking.cancel(conn, uuid.uuid4(), appt["id"], actor=STAFF, now=NOW)


def test_sweep_expired_holds(conn, clinic):
    booking.hold_slot(
        conn,
        clinic.business_id,
        client_id=clinic.client_id,
        starts_at=ist(MONDAY, 10),
        scope=ANY,
        actor=PATIENT,
        now=NOW,
    )
    assert booking.sweep_expired_holds(conn, NOW + timedelta(minutes=1)) == 0
    assert booking.sweep_expired_holds(conn, NOW + timedelta(minutes=5)) >= 1
