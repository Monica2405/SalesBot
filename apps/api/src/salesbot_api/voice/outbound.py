"""Outbound calls (confirmation and reminder calls) through an OutboundCallAdapter.

No real call is placed unless BOTH are true:
- OUTBOUND_CALLS_ENABLED=true (env, off by default), and
- the clinic's call_policy.outbound_enabled, which the schema pins to false until the owner's
  go (salesbot_core.scheduling.settings.CallPolicy).
Otherwise the request is a dry run: every check below still runs, and a calls row with status
'dry_run' plus an outbound_call_requested event record what would have been called.

Checks, in order: the appointment is active and not paused; the patient opted in to calls with
recorded consent and is not paused; now is inside the clinic's call window and outside quiet
hours (clinic timezone); fewer than max_attempts attempts for this appointment and purpose; the
last attempt is at least retry_spacing_minutes old. A live call then reserves its worst-case
cost against the spend caps (salesbot_api.voice.spend) before dialling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from salesbot_api import booking
from salesbot_api.records import record_event
from salesbot_api.settings import Settings
from salesbot_api.voice import spend, store
from salesbot_api.voice.sarvam import (
    DryRunOutboundAdapter,
    OutboundCallAdapter,
    OutboundRequest,
    SarvamOutboundAdapter,
)
from salesbot_api.voice.security import mask_phone
from salesbot_core.costs import SpendKind, max_call_cost
from salesbot_core.events import Channel, EventType, FunnelEvent
from salesbot_core.voice import SARVAM_LANGUAGE_NAMES

log = logging.getLogger("salesbot.voice")
Purpose = Literal["confirmation_call", "reminder_call"]


@dataclass(frozen=True)
class OutboundResult:
    # placed: a real call was started. dry_run: everything passed, nothing was dialled.
    # blocked: a check failed (`reason`).
    status: Literal["placed", "dry_run", "blocked"]
    reason: str | None = None
    call_id: UUID | None = None
    attempt_id: str | None = None


def live_calls_allowed(settings: Settings, policy_enabled: bool) -> bool:
    return settings.outbound_calls_enabled and policy_enabled


def adapter_for(settings: Settings, live: bool) -> OutboundCallAdapter:
    return SarvamOutboundAdapter(settings) if live else DryRunOutboundAdapter()


def webhook_url(settings: Settings) -> str | None:
    if not (settings.public_base_url and settings.voice_webhook_secret):
        return None
    secret = settings.voice_webhook_secret.get_secret_value()
    return f"{settings.public_base_url.rstrip('/')}/api/v1/voice/webhooks/{secret}/outbound"


def _blocked(reason: str) -> OutboundResult:
    log.info("outbound call blocked: %s", reason)
    return OutboundResult(status="blocked", reason=reason)


def request_call(
    conn: psycopg.Connection,
    settings: Settings,
    *,
    business_id: UUID,
    appointment_id: UUID,
    purpose: Purpose,
    now: datetime,
    adapter: OutboundCallAdapter | None = None,
) -> OutboundResult:
    appt = store.get_appointment(conn, business_id, appointment_id)
    if appt is None or not store.is_active(appt) or appt["starts_at"] <= now:
        return _blocked("appointment_not_active")
    if appt["automation_paused"]:
        return _blocked("appointment_paused")
    client = store.get_client(conn, business_id, appt["client_id"])
    if client is None or not client["call_opt_in"] or client["consent_at"] is None:
        return _blocked("no_call_opt_in")
    if client["automation_paused"]:
        return _blocked("client_paused")

    sched = booking.load_settings(conn, business_id)
    local = now.astimezone(ZoneInfo(sched.timezone)).time()
    policy = sched.call_policy
    if not policy.window.contains(local):
        return _blocked("outside_call_window")
    quiet = sched.reminder_policy.quiet_hours
    if quiet is not None and quiet.contains(local):
        return _blocked("quiet_hours")

    attempts = conn.execute(
        """
        select count(*) as n, max(started_at) as last from public.calls
        where business_id = %s and appointment_id = %s and purpose = %s
          and status <> 'failed'
        """,
        (business_id, appointment_id, purpose),
    ).fetchone()
    if attempts["n"] >= policy.max_attempts:
        return _blocked("max_attempts")
    if attempts["last"] and now - attempts["last"] < timedelta(
        minutes=policy.retry_spacing_minutes
    ):
        return _blocked("too_soon")

    live = live_calls_allowed(settings, policy.outbound_enabled)
    adapter = adapter or adapter_for(settings, live)
    language = client["preferred_language"]
    with conn.transaction():
        call = conn.execute(
            """
            insert into public.calls (business_id, telephony_provider, direction, to_number,
              status, client_id, appointment_id, purpose, dry_run, started_at, language,
              consent_recording)
            values (%s, 'sarvam', 'outbound', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (business_id, client["phone"], "queued" if adapter.places_real_calls else "dry_run",
             client["id"], appointment_id, purpose, not adapter.places_real_calls, now,
             language, bool(client["call_opt_in"])),
        ).fetchone()  # fmt: skip
        record_event(
            conn,
            FunnelEvent(
                business_id=business_id,
                type=EventType.OUTBOUND_CALL_REQUESTED,
                occurred_at=now,
                call_id=call["id"],
                appointment_id=appointment_id,
                client_id=client["id"],
                channel=Channel.VOICE,
                language=language,
                properties={"purpose": purpose, "dry_run": not adapter.places_real_calls},
            ),
        )
    call_id = call["id"]

    ledger_id = None
    if adapter.places_real_calls:
        # Raises SpendCapReachedError (nothing dialled) when a cap would be passed.
        try:
            ledger_id = spend.reserve(
                conn, settings, kind=SpendKind.OUTBOUND_CALL,
                estimate=max_call_cost(settings.call_max_seconds), now=now,
                business_id=business_id, note=purpose,
            )  # fmt: skip
        except Exception:
            conn.execute("update public.calls set status = 'failed', failure_reason = "
                         "'spend_cap_reached' where id = %s", (call_id,))  # fmt: skip
            raise

    request = OutboundRequest(
        to_number=client["phone"],
        agent_variables={
            "call_ref": str(call_id),
            "patient_id": str(client["id"]),
            "appointment_id": str(appointment_id),
            "call_purpose": purpose,
        },
        webhook_url=webhook_url(settings),
        metadata={"call_ref": str(call_id), "purpose": purpose},
        initial_language=SARVAM_LANGUAGE_NAMES.get(language),
    )
    try:
        attempt_id = adapter.place(request)
    except Exception as exc:
        if ledger_id is not None:
            spend.release(conn, ledger_id)
        conn.execute(
            "update public.calls set status = 'failed', failure_reason = %s where id = %s",
            (f"adapter error: {type(exc).__name__}", call_id),
        )
        log.warning("outbound call to %s failed to start (%s)", mask_phone(client["phone"]),
                    type(exc).__name__)  # fmt: skip
        return OutboundResult(status="blocked", reason="adapter_error", call_id=call_id)

    conn.execute("update public.calls set attempt_id = %s where id = %s", (attempt_id, call_id))
    if ledger_id is not None:
        spend.link_attempt(conn, ledger_id, attempt_id, call_id)
    return OutboundResult(
        status="placed" if adapter.places_real_calls else "dry_run",
        call_id=call_id,
        attempt_id=attempt_id,
    )
