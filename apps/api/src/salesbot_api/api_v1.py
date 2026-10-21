"""Versioned HTTP API: client intake (signed webhook) and the staff booking endpoints.

Staff endpoints authenticate with the admin's Supabase JWT and check the caller's role in
business_members. They call the same booking engine as the WhatsApp and voice channels.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AwareDatetime, BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from salesbot_api import booking, db
from salesbot_api.auth import AuthUser, current_user
from salesbot_api.intake import (
    SIMULATION_HEADER,
    HmacWebhookIntake,
    IntakeAdapter,
    IntakeRejectedError,
    register_client,
)
from salesbot_api.records import Actor
from salesbot_api.settings import Settings, get_settings
from salesbot_core.events import Channel, LeadSource
from salesbot_core.scheduling import VisitType

router = APIRouter(prefix="/api/v1")

SettingsDep = Annotated[Settings, Depends(get_settings)]
STAFF_ROLES = ("owner", "admin", "receptionist", "staff")


def utcnow() -> datetime:
    return datetime.now(UTC)


def get_conn(settings: SettingsDep) -> Iterator[psycopg.Connection]:
    try:
        with db.connect(settings, autocommit=True) as conn:
            yield conn
    except db.DatabaseNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database not configured") from exc


ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
NowDep = Annotated[datetime, Depends(utcnow)]


def staff_actor(
    business_id: UUID, user: Annotated[AuthUser, Depends(current_user)], conn: ConnDep
) -> Actor:
    row = conn.execute(
        "select role from public.business_members where business_id = %s and user_id = %s",
        (business_id, user.id),
    ).fetchone()
    if row is None or row["role"] not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not staff of this business")
    return Actor(type="staff", channel=Channel.STAFF, user_id=user.id)


StaffDep = Annotated[Actor, Depends(staff_actor)]


def _http(exc: booking.BookingError) -> HTTPException:
    code = {
        booking.NotFoundError: status.HTTP_404_NOT_FOUND,
        booking.SlotUnavailableError: status.HTTP_409_CONFLICT,
        booking.InvalidStateError: status.HTTP_409_CONFLICT,
        booking.HoldExpiredError: status.HTTP_410_GONE,
    }.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return HTTPException(code, {"code": exc.code, "message": str(exc)})


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def get_intake_adapter(settings: SettingsDep) -> IntakeAdapter:
    if settings.intake_hmac_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "intake is not configured")
    return HmacWebhookIntake(settings.intake_hmac_secret.get_secret_value())


@router.post("/intake/patients")
async def intake_patient(
    request: Request,
    response: Response,
    adapter: Annotated[IntakeAdapter, Depends(get_intake_adapter)],
    settings: SettingsDep,
) -> dict[str, Any]:
    body = await request.body()
    now = utcnow()
    try:
        record = adapter.parse(request.headers, body, now)
    except IntakeRejectedError as exc:
        raise HTTPException(exc.status_code, exc.reason) from exc

    # The dev-only simulator marks its submissions so they never count in metrics.
    simulated = request.headers.get(SIMULATION_HEADER) == "1" and settings.app_env != "production"
    source = LeadSource.SIMULATION if simulated else LeadSource.REGISTRATION_FORM

    def _register() -> Any:
        with db.connect(settings, autocommit=True) as conn:
            return register_client(conn, record, now=now, source=source)

    try:
        result = await run_in_threadpool(_register)
    except IntakeRejectedError as exc:
        raise HTTPException(exc.status_code, exc.reason) from exc
    except db.DatabaseNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database not configured") from exc
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return {
        "client_id": str(result.client_id),
        "status": "created" if result.created else "already_registered",
        "welcome_queued": result.welcome_queued,
    }


# ---------------------------------------------------------------------------
# Staff booking endpoints
# ---------------------------------------------------------------------------


class SlotOut(BaseModel):
    practitioner_id: UUID
    starts_at: datetime
    ends_at: datetime


class AppointmentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    business_id: UUID
    practitioner_id: UUID
    client_id: UUID
    visit_type: VisitType
    status: str
    starts_at: datetime
    ends_at: datetime
    hold_expires_at: datetime | None = None
    rescheduled_from_id: UUID | None = None
    rescheduled_to_id: UUID | None = None


class HoldIn(BaseModel):
    client_id: UUID
    starts_at: AwareDatetime
    visit_type: VisitType = VisitType.CONSULTATION
    practitioner_id: UUID | None = None
    reschedule_of: UUID | None = None


class CancelIn(BaseModel):
    reason: str | None = None


class DecisionIn(BaseModel):
    approve: bool


@router.get("/businesses/{business_id}/availability/days")
def availability_days(
    business_id: UUID,
    actor: StaffDep,
    conn: ConnDep,
    now: NowDep,
    visit_type: VisitType = VisitType.CONSULTATION,
    practitioner_id: UUID | None = None,
    from_day: date | None = None,
    limit: int | None = None,
) -> list[date]:
    scope = booking.Scope(visit=visit_type, practitioner_id=practitioner_id)
    try:
        return booking.open_days(
            conn, business_id, scope=scope, now=now, from_day=from_day, limit=limit
        )
    except booking.BookingError as exc:
        raise _http(exc) from exc


@router.get("/businesses/{business_id}/availability/slots")
def availability_slots(
    business_id: UUID,
    day: date,
    actor: StaffDep,
    conn: ConnDep,
    now: NowDep,
    visit_type: VisitType = VisitType.CONSULTATION,
    practitioner_id: UUID | None = None,
) -> list[SlotOut]:
    scope = booking.Scope(visit=visit_type, practitioner_id=practitioner_id)
    try:
        slots = booking.open_slots(conn, business_id, day=day, scope=scope, now=now)
    except booking.BookingError as exc:
        raise _http(exc) from exc
    return [SlotOut.model_validate(s.model_dump()) for s in slots]


@router.post("/businesses/{business_id}/holds", status_code=status.HTTP_201_CREATED)
def create_hold(
    business_id: UUID, body: HoldIn, actor: StaffDep, conn: ConnDep, now: NowDep
) -> AppointmentOut:
    scope = booking.Scope(visit=body.visit_type, practitioner_id=body.practitioner_id)
    try:
        row = booking.hold_slot(
            conn,
            business_id,
            client_id=body.client_id,
            starts_at=body.starts_at,
            scope=scope,
            actor=actor,
            now=now,
            reschedule_of=body.reschedule_of,
        )
    except booking.BookingError as exc:
        raise _http(exc) from exc
    return AppointmentOut.model_validate(row)


@router.post("/businesses/{business_id}/holds/{hold_id}/book")
def book(
    business_id: UUID, hold_id: UUID, actor: StaffDep, conn: ConnDep, now: NowDep
) -> AppointmentOut:
    try:
        return AppointmentOut.model_validate(
            booking.book_hold(conn, business_id, hold_id, actor=actor, now=now)
        )
    except booking.BookingError as exc:
        raise _http(exc) from exc


@router.delete("/businesses/{business_id}/holds/{hold_id}", status_code=204)
def release(business_id: UUID, hold_id: UUID, actor: StaffDep, conn: ConnDep) -> None:
    booking.release_hold(conn, business_id, hold_id)


@router.post("/businesses/{business_id}/appointments/{appointment_id}/confirm")
def confirm(
    business_id: UUID, appointment_id: UUID, actor: StaffDep, conn: ConnDep, now: NowDep
) -> AppointmentOut:
    try:
        return AppointmentOut.model_validate(
            booking.confirm(conn, business_id, appointment_id, actor=actor, now=now)
        )
    except booking.BookingError as exc:
        raise _http(exc) from exc


@router.post("/businesses/{business_id}/appointments/{appointment_id}/cancel")
def cancel(
    business_id: UUID,
    appointment_id: UUID,
    body: CancelIn,
    actor: StaffDep,
    conn: ConnDep,
    now: NowDep,
) -> AppointmentOut:
    try:
        return AppointmentOut.model_validate(
            booking.cancel(
                conn, business_id, appointment_id, actor=actor, now=now, reason=body.reason
            )
        )
    except booking.BookingError as exc:
        raise _http(exc) from exc


@router.post("/businesses/{business_id}/appointments/{appointment_id}/reschedule-decision")
def reschedule_decision(
    business_id: UUID,
    appointment_id: UUID,
    body: DecisionIn,
    actor: StaffDep,
    conn: ConnDep,
    now: NowDep,
) -> AppointmentOut:
    try:
        return AppointmentOut.model_validate(
            booking.decide_reschedule(
                conn, business_id, appointment_id, approve=body.approve, actor=actor, now=now
            )
        )
    except booking.BookingError as exc:
        raise _http(exc) from exc
