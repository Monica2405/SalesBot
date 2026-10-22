"""The booking engine. Staff (admin) and the AI channels (WhatsApp, voice) all call these
functions, so every booking follows the same rules and writes the same records.

- Availability comes from salesbot_core.scheduling (pure) fed with calendars loaded here.
- A hold is an appointments row with status 'held' and an expiry. The database exclusion
  constraint `appointments_no_overlap` makes double-booking impossible even under concurrency;
  this module turns a violation into SlotUnavailable.
- Every state change writes a funnel event and an audit row in the same transaction.
- Rescheduling never touches the original appointment until the new slot is booked; then both
  rows change in one transaction, old -> 'rescheduled' with a link to the new one, and the old
  appointment's queued jobs (reminders, confirmations) are cancelled.

Functions take a psycopg connection in autocommit mode and open their own transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg import errors

from salesbot_api.records import Actor, cancel_queued_jobs, record_audit, record_event
from salesbot_core.events import EventType, FunnelEvent
from salesbot_core.scheduling import (
    ACTIVE_STATUSES,
    BLOCKING_STATUSES,
    AppointmentStatus,
    Interval,
    PractitionerCalendar,
    SchedulingSettings,
    Scope,
    Slot,
    VisitType,
    WeeklyWindow,
    days_with_openings,
    distinct_times,
    next_opening,
    slots_on_day,
)
from salesbot_core.scheduling.availability import MAX_SCAN_DAYS
from salesbot_core.scheduling.settings import PractitionerSelection, RescheduleApproval

Row = dict[str, Any]


class BookingError(Exception):
    """Base class. `code` is stable and safe to show to API clients."""

    code = "booking_error"


class NotFoundError(BookingError):
    code = "not_found"


class SlotUnavailableError(BookingError):
    code = "slot_unavailable"


class HoldExpiredError(BookingError):
    code = "hold_expired"


class InvalidStateError(BookingError):
    code = "invalid_state"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_settings(conn: psycopg.Connection, business_id: UUID) -> SchedulingSettings:
    row = conn.execute(
        """
        select b.timezone, b.default_language, s.hold_minutes, s.min_lead_minutes,
               s.lookahead_days, s.days_per_list, s.slot_step_minutes,
               s.practitioner_selection, s.default_practitioner_id, s.reschedule_approval,
               s.confirmation_policy, s.reminder_policy, s.call_policy
        from public.businesses b
        left join public.scheduling_settings s on s.business_id = b.id
        where b.id = %s
        """,
        (business_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("business not found")
    # No settings row yet = all defaults
    return SchedulingSettings.model_validate({k: v for k, v in row.items() if v is not None})


def _practitioner_ids(
    conn: psycopg.Connection, business_id: UUID, settings: SchedulingSettings, scope: Scope
) -> list[UUID]:
    if scope.practitioner_id is not None:
        wanted: UUID | None = scope.practitioner_id
    elif settings.practitioner_selection is PractitionerSelection.DEFAULT_PRACTITIONER:
        wanted = settings.default_practitioner_id
    else:
        wanted = None
    rows = conn.execute(
        """
        select id from public.practitioners
        where business_id = %s and is_active and (%s::uuid is null or id = %s::uuid)
        order by created_at, id
        """,
        (business_id, wanted, wanted),
    ).fetchall()
    if wanted is not None and not rows:
        raise NotFoundError("practitioner not found or inactive")
    return [r["id"] for r in rows]


def load_calendars(
    conn: psycopg.Connection,
    business_id: UUID,
    practitioner_ids: Sequence[UUID],
    start: datetime,
    end: datetime,
    now: datetime,
) -> list[PractitionerCalendar]:
    """Calendars with exceptions and busy time between start and end. Expired holds are free."""
    if not practitioner_ids:
        return []
    ids = list(practitioner_ids)
    practitioners = {
        r["id"]: r
        for r in conn.execute(
            "select id, consultation_minutes, first_visit_minutes from public.practitioners "
            "where business_id = %s and id = any(%s)",
            (business_id, ids),
        ).fetchall()
    }
    hours = conn.execute(
        "select practitioner_id, kind, weekday, start_time, end_time "
        "from public.practitioner_hours where business_id = %s and practitioner_id = any(%s)",
        (business_id, ids),
    ).fetchall()
    exceptions = conn.execute(
        """
        select practitioner_id, kind, starts_at, ends_at from public.schedule_exceptions
        where business_id = %s and starts_at < %s and ends_at > %s
          and (practitioner_id is null or practitioner_id = any(%s))
        """,
        (business_id, end, start, ids),
    ).fetchall()
    busy = conn.execute(
        """
        select practitioner_id, starts_at, ends_at from public.appointments
        where business_id = %s and practitioner_id = any(%s)
          and starts_at < %s and ends_at > %s
          and status = any(%s)
          and (status <> 'held' or hold_expires_at > %s)
        """,
        (business_id, ids, end, start, [s.value for s in BLOCKING_STATUSES], now),
    ).fetchall()

    def window(h: Row) -> WeeklyWindow:
        return WeeklyWindow(weekday=h["weekday"], start=h["start_time"], end=h["end_time"])

    def interval(r: Row) -> Interval:
        return Interval(start=r["starts_at"], end=r["ends_at"])

    calendars = []
    for pid in ids:
        p = practitioners[pid]
        own_hours = [h for h in hours if h["practitioner_id"] == pid]
        calendars.append(
            PractitionerCalendar(
                practitioner_id=pid,
                consultation_minutes=p["consultation_minutes"],
                first_visit_minutes=p["first_visit_minutes"],
                work=[window(h) for h in own_hours if h["kind"] == "work"],
                breaks=[window(h) for h in own_hours if h["kind"] == "break"],
                # practitioner_id null = the whole business is closed
                closed=[
                    interval(e)
                    for e in exceptions
                    if e["kind"] == "closed" and e["practitioner_id"] in (None, pid)
                ],
                extra_open=[
                    interval(e)
                    for e in exceptions
                    if e["kind"] == "open" and e["practitioner_id"] == pid
                ],
                busy=[interval(b) for b in busy if b["practitioner_id"] == pid],
            )
        )
    return calendars


def _calendars_for_days(
    conn: psycopg.Connection,
    business_id: UUID,
    settings: SchedulingSettings,
    scope: Scope,
    first_day: date,
    days: int,
    now: datetime,
) -> tuple[list[PractitionerCalendar], ZoneInfo]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(first_day, datetime.min.time(), tz)
    end = start + timedelta(days=days + 1)
    ids = _practitioner_ids(conn, business_id, settings, scope)
    return load_calendars(conn, business_id, ids, start, end, now), tz


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def open_days(
    conn: psycopg.Connection,
    business_id: UUID,
    *,
    scope: Scope,
    now: datetime,
    from_day: date | None = None,
    limit: int | None = None,
) -> list[date]:
    """Days with openings, for the day list. Starts today (business timezone) by default."""
    settings = load_settings(conn, business_id)
    tz = ZoneInfo(settings.timezone)
    first = from_day or now.astimezone(tz).date()
    calendars, tz = _calendars_for_days(
        conn, business_id, settings, scope, first, MAX_SCAN_DAYS, now
    )
    return days_with_openings(
        calendars,
        first,
        limit=limit or settings.days_per_list,
        visit=scope.visit,
        now=now,
        tz=tz,
        min_lead=settings.min_lead,
        step_minutes=settings.slot_step_minutes,
    )


def open_slots(
    conn: psycopg.Connection, business_id: UUID, *, day: date, scope: Scope, now: datetime
) -> list[Slot]:
    """Start times on one day. With several practitioners, one entry per start time."""
    settings = load_settings(conn, business_id)
    calendars, tz = _calendars_for_days(conn, business_id, settings, scope, day, 1, now)
    slots = slots_on_day(
        calendars,
        day,
        visit=scope.visit,
        now=now,
        tz=tz,
        min_lead=settings.min_lead,
        step_minutes=settings.slot_step_minutes,
    )
    return distinct_times(slots)


def first_opening(
    conn: psycopg.Connection, business_id: UUID, *, scope: Scope, now: datetime
) -> tuple[Slot | None, bool]:
    """(next opening, whether it falls inside the lookahead window)."""
    settings = load_settings(conn, business_id)
    tz = ZoneInfo(settings.timezone)
    calendars, tz = _calendars_for_days(
        conn, business_id, settings, scope, now.astimezone(tz).date(), MAX_SCAN_DAYS, now
    )
    slot = next_opening(
        calendars,
        visit=scope.visit,
        now=now,
        tz=tz,
        min_lead=settings.min_lead,
        step_minutes=settings.slot_step_minutes,
    )
    if slot is None:
        return None, False
    horizon = datetime.combine(
        now.astimezone(tz).date() + timedelta(days=settings.lookahead_days),
        datetime.min.time(),
        tz,
    )
    return slot, slot.starts_at < horizon


# ---------------------------------------------------------------------------
# Holds and bookings
# ---------------------------------------------------------------------------


def _get_appointment(
    conn: psycopg.Connection, business_id: UUID, appointment_id: UUID, *, lock: bool = False
) -> Row:
    sql = "select * from public.appointments where id = %s and business_id = %s"
    row = conn.execute(sql + (" for update" if lock else ""), (appointment_id, business_id))
    found = row.fetchone()
    if found is None:
        raise NotFoundError("appointment not found")
    return found


def _event(
    business_id: UUID, kind: EventType, appt: Row, actor: Actor, **properties: Any
) -> FunnelEvent:
    return FunnelEvent(
        business_id=business_id,
        type=kind,
        appointment_id=appt["id"],
        client_id=appt["client_id"],
        channel=actor.channel,
        language=actor.language,
        properties=properties,
    )


def hold_slot(
    conn: psycopg.Connection,
    business_id: UUID,
    *,
    client_id: UUID,
    starts_at: datetime,
    scope: Scope,
    actor: Actor,
    now: datetime,
    reschedule_of: UUID | None = None,
) -> Row:
    """Reserve a start time for settings.hold_minutes. Raises SlotUnavailableError if taken.

    For a reschedule the practitioner defaults to the original appointment's practitioner.
    """
    with conn.transaction():
        settings = load_settings(conn, business_id)
        client = conn.execute(
            "select id from public.clients where id = %s and business_id = %s",
            (client_id, business_id),
        ).fetchone()
        if client is None:
            raise NotFoundError("client not found")

        if reschedule_of is not None:
            original = _get_appointment(conn, business_id, reschedule_of)
            if original["client_id"] != client_id:
                raise InvalidStateError("appointment belongs to another client")
            if original["status"] not in ACTIVE_STATUSES:
                raise InvalidStateError(f"cannot reschedule a {original['status']} appointment")
            scope = Scope(
                visit=VisitType(original["visit_type"]),
                practitioner_id=scope.practitioner_id or original["practitioner_id"],
            )

        tz = ZoneInfo(settings.timezone)
        day = starts_at.astimezone(tz).date()
        # Expired holds count as free (load_calendars filters them by `now`)
        calendars, tz = _calendars_for_days(conn, business_id, settings, scope, day, 1, now)
        candidates = [
            s
            for s in slots_on_day(
                calendars,
                day,
                visit=scope.visit,
                now=now,
                tz=tz,
                min_lead=settings.min_lead,
                step_minutes=settings.slot_step_minutes,
            )
            if s.starts_at == starts_at
        ]
        for slot in candidates:
            try:
                with conn.transaction():  # savepoint: a lost race tries the next practitioner
                    conn.execute(
                        """
                        delete from public.appointments
                        where business_id = %s and practitioner_id = %s and status = 'held'
                          and hold_expires_at <= %s
                          and tstzrange(starts_at, ends_at, '[)') && tstzrange(%s, %s, '[)')
                        """,
                        (business_id, slot.practitioner_id, now, slot.starts_at, slot.ends_at),
                    )
                    return conn.execute(
                        """
                        insert into public.appointments (business_id, practitioner_id, client_id,
                          visit_type, starts_at, ends_at, status, hold_expires_at,
                          rescheduled_from_id, booked_via, language)
                        values (%s, %s, %s, %s, %s, %s, 'held', %s, %s, %s, %s)
                        returning *
                        """,
                        (
                            business_id,
                            slot.practitioner_id,
                            client_id,
                            scope.visit.value,
                            slot.starts_at,
                            slot.ends_at,
                            now + settings.hold,
                            reschedule_of,
                            actor.channel.value,
                            actor.language,
                        ),
                    ).fetchone()
            except errors.ExclusionViolation:
                continue
        raise SlotUnavailableError("that time is no longer available")


def release_hold(conn: psycopg.Connection, business_id: UUID, hold_id: UUID) -> None:
    with conn.transaction():
        conn.execute(
            "delete from public.appointments where id = %s and business_id = %s "
            "and status = 'held'",
            (hold_id, business_id),
        )


def book_hold(
    conn: psycopg.Connection,
    business_id: UUID,
    hold_id: UUID,
    *,
    actor: Actor,
    now: datetime,
    client_message: str | None = None,
) -> Row:
    """Turn a live hold into a booking (or finish a reschedule). Commit happens here, so a
    confirmation must only be sent after this returns."""
    # A failure that must still release the hold is returned from the transaction (so the
    # delete commits) and raised afterwards.
    with conn.transaction():
        result = _book_hold_tx(conn, business_id, hold_id, actor, now, client_message)
    if isinstance(result, BookingError):
        raise result
    return result


def _release(conn: psycopg.Connection, hold_id: UUID) -> None:
    conn.execute("delete from public.appointments where id = %s and status = 'held'", (hold_id,))


def _book_hold_tx(
    conn: psycopg.Connection,
    business_id: UUID,
    hold_id: UUID,
    actor: Actor,
    now: datetime,
    client_message: str | None,
) -> Row | BookingError:
    hold = _get_appointment(conn, business_id, hold_id, lock=True)
    if hold["status"] != AppointmentStatus.HELD:
        raise InvalidStateError(f"appointment is {hold['status']}, not held")
    if hold["hold_expires_at"] <= now:
        _release(conn, hold_id)
        return HoldExpiredError("the hold expired; pick the time again")

    if hold["rescheduled_from_id"] is None:
        booked = conn.execute(
            """
            update public.appointments
            set status = 'booked', booked_at = %s, hold_expires_at = null
            where id = %s returning *
            """,
            (now, hold_id),
        ).fetchone()
        record_event(conn, _event(business_id, EventType.BOOKING_CREATED, booked, actor))
        record_audit(
            conn,
            business_id=business_id,
            entity_type="appointment",
            entity_id=hold_id,
            action="booked",
            actor=actor,
            changes={"status": ["held", "booked"]},
            client_message=client_message,
        )
        return booked

    original = _get_appointment(conn, business_id, hold["rescheduled_from_id"], lock=True)
    if original["status"] not in ACTIVE_STATUSES:
        _release(conn, hold_id)
        return InvalidStateError(f"original appointment is {original['status']}")

    settings = load_settings(conn, business_id)
    if settings.reschedule_approval is RescheduleApproval.STAFF and actor.type != "staff":
        pending = conn.execute(
            """
            update public.appointments
            set status = 'pending_approval', hold_expires_at = null
            where id = %s returning *
            """,
            (hold_id,),
        ).fetchone()
        record_event(
            conn,
            _event(
                business_id,
                EventType.RESCHEDULE_REQUESTED,
                pending,
                actor,
                original_appointment_id=str(original["id"]),
            ),
        )
        record_audit(
            conn,
            business_id=business_id,
            entity_type="appointment",
            entity_id=hold_id,
            action="reschedule_pending_approval",
            actor=actor,
            changes={"status": ["held", "pending_approval"]},
            client_message=client_message,
        )
        return pending

    return _complete_reschedule(conn, business_id, original, hold, actor, now, client_message)


def _complete_reschedule(
    conn: psycopg.Connection,
    business_id: UUID,
    original: Row,
    new: Row,
    actor: Actor,
    now: datetime,
    client_message: str | None,
) -> Row:
    booked = conn.execute(
        """
        update public.appointments
        set status = 'booked', booked_at = %s, hold_expires_at = null
        where id = %s returning *
        """,
        (now, new["id"]),
    ).fetchone()
    conn.execute(
        "update public.appointments set status = 'rescheduled', rescheduled_to_id = %s "
        "where id = %s",
        (new["id"], original["id"]),
    )
    stopped = cancel_queued_jobs(conn, original["id"])
    record_event(
        conn,
        _event(
            business_id,
            EventType.APPOINTMENT_RESCHEDULED,
            booked,
            actor,
            original_appointment_id=str(original["id"]),
        ),
    )
    record_audit(
        conn,
        business_id=business_id,
        entity_type="appointment",
        entity_id=original["id"],
        action="rescheduled",
        actor=actor,
        changes={
            "status": [original["status"], "rescheduled"],
            "rescheduled_to_id": [None, str(new["id"])],
            "jobs_cancelled": stopped,
        },
    )
    record_audit(
        conn,
        business_id=business_id,
        entity_type="appointment",
        entity_id=new["id"],
        action="booked_by_reschedule",
        actor=actor,
        changes={
            "status": [new["status"], "booked"],
            "rescheduled_from_id": [None, str(original["id"])],
        },
        client_message=client_message,
    )
    return booked


def decide_reschedule(
    conn: psycopg.Connection,
    business_id: UUID,
    appointment_id: UUID,
    *,
    approve: bool,
    actor: Actor,
    now: datetime,
) -> Row:
    """Staff approve or reject a reschedule waiting for approval."""
    with conn.transaction():
        new = _get_appointment(conn, business_id, appointment_id, lock=True)
        if new["status"] != AppointmentStatus.PENDING_APPROVAL:
            raise InvalidStateError(f"appointment is {new['status']}, not pending approval")
        original = _get_appointment(conn, business_id, new["rescheduled_from_id"], lock=True)
        if approve and original["status"] in ACTIVE_STATUSES:
            return _complete_reschedule(conn, business_id, original, new, actor, now, None)
        rejected = conn.execute(
            "update public.appointments set status = 'cancelled', cancelled_at = %s "
            "where id = %s returning *",
            (now, appointment_id),
        ).fetchone()
        record_audit(
            conn,
            business_id=business_id,
            entity_type="appointment",
            entity_id=appointment_id,
            action="reschedule_rejected",
            actor=actor,
            changes={"status": ["pending_approval", "cancelled"]},
        )
        return rejected


def confirm(
    conn: psycopg.Connection,
    business_id: UUID,
    appointment_id: UUID,
    *,
    actor: Actor,
    now: datetime,
    client_message: str | None = None,
) -> Row:
    """Mark confirmed after an explicit response. Idempotent for confirmed appointments."""
    with conn.transaction():
        appt = _get_appointment(conn, business_id, appointment_id, lock=True)
        if appt["status"] == AppointmentStatus.CONFIRMED:
            return appt
        if appt["status"] not in (AppointmentStatus.BOOKED, AppointmentStatus.UNCONFIRMED):
            raise InvalidStateError(f"cannot confirm a {appt['status']} appointment")
        confirmed = conn.execute(
            "update public.appointments set status = 'confirmed', confirmed_at = %s "
            "where id = %s returning *",
            (now, appointment_id),
        ).fetchone()
        cancel_queued_jobs(
            conn,
            appointment_id,
            kinds=["confirmation_request", "confirmation_nudge", "confirmation_call"],
        )
        record_event(conn, _event(business_id, EventType.APPOINTMENT_CONFIRMED, confirmed, actor))
        record_audit(
            conn,
            business_id=business_id,
            entity_type="appointment",
            entity_id=appointment_id,
            action="confirmed",
            actor=actor,
            changes={"status": [appt["status"], "confirmed"]},
            client_message=client_message,
        )
        return confirmed


def cancel(
    conn: psycopg.Connection,
    business_id: UUID,
    appointment_id: UUID,
    *,
    actor: Actor,
    now: datetime,
    reason: str | None = None,
    client_message: str | None = None,
) -> Row:
    """Cancel and free the slot. The caller must already have the client's explicit
    confirmation of WHICH appointment to cancel."""
    with conn.transaction():
        appt = _get_appointment(conn, business_id, appointment_id, lock=True)
        if appt["status"] not in ACTIVE_STATUSES:
            raise InvalidStateError(f"cannot cancel a {appt['status']} appointment")
        cancelled = conn.execute(
            "update public.appointments set status = 'cancelled', cancelled_at = %s "
            "where id = %s returning *",
            (now, appointment_id),
        ).fetchone()
        stopped = cancel_queued_jobs(conn, appointment_id)
        record_event(
            conn, _event(business_id, EventType.BOOKING_CANCELLED, cancelled, actor, reason=reason)
        )
        record_audit(
            conn,
            business_id=business_id,
            entity_type="appointment",
            entity_id=appointment_id,
            action="cancelled",
            actor=actor,
            changes={"status": [appt["status"], "cancelled"], "jobs_cancelled": stopped},
            client_message=client_message,
        )
        return cancelled


def sweep_expired_holds(conn: psycopg.Connection, now: datetime) -> int:
    """Delete expired holds across all businesses (run by the worker)."""
    with conn.transaction():
        cur = conn.execute(
            "delete from public.appointments where status = 'held' and hold_expires_at <= %s",
            (now,),
        )
        return cur.rowcount
