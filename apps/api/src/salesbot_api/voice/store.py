"""Database reads and writes for the voice channel. Every query filters by business_id (this
connection bypasses RLS). Bookings themselves go through salesbot_api.booking."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from salesbot_api.records import Actor, record_audit, record_event
from salesbot_core.events import Channel, EventType, FunnelEvent, LeadSource
from salesbot_core.packs.schema import Language
from salesbot_core.scheduling import ACTIVE_STATUSES

Row = dict[str, Any]
PROVIDER = "sarvam"
# How long a duplicate tool call waits for the first one to finish before giving up.
DUPLICATE_WAIT_SECONDS = 2.0


@dataclass(frozen=True)
class Business:
    id: UUID
    name: str
    slug: str
    pack_id: str
    timezone: str
    default_language: Language
    allowed_languages: list[Language]
    emergency_numbers: list[str]
    contact_phone: str | None


_BUSINESS_COLUMNS = (
    "id, name, slug, pack_id, timezone, default_language, allowed_languages, "
    "emergency_numbers, coalesce(contact_phone, phone_number) as contact_phone"
)


def business_by_slug(conn: psycopg.Connection, slug: str) -> Business | None:
    row = conn.execute(
        f"select {_BUSINESS_COLUMNS} from public.businesses where slug = %s",  # noqa: S608
        (slug,),
    ).fetchone()
    return Business(**row) if row else None


def business_by_number(conn: psycopg.Connection, number: str) -> Business | None:
    row = conn.execute(
        f"select {_BUSINESS_COLUMNS} from public.businesses where phone_number = %s",  # noqa: S608
        (number,),
    ).fetchone()
    return Business(**row) if row else None


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def ensure_call(
    conn: psycopg.Connection,
    business_id: UUID,
    interaction_id: str,
    *,
    caller_phone: str | None,
    now: datetime,
    call_ref: UUID | None = None,
) -> tuple[UUID, bool]:
    """The calls row for this Sarvam interaction, created on first sight. `call_ref` is our
    calls.id passed to an outbound call as an agent variable; its row is linked to the
    interaction. Returns (call_id, created)."""
    if call_ref is not None:
        row = conn.execute(
            """
            update public.calls set provider_call_id = %s, status = 'in_progress'
            where id = %s and business_id = %s and provider_call_id is null
            returning id
            """,
            (interaction_id, call_ref, business_id),
        ).fetchone()
        if row:
            return row["id"], False
    row = conn.execute(
        """
        insert into public.calls (business_id, telephony_provider, provider_call_id, direction,
          from_number, status, started_at)
        values (%s, %s, %s, 'inbound', %s, 'in_progress', %s)
        on conflict (telephony_provider, provider_call_id) do update
          set from_number = coalesce(public.calls.from_number, excluded.from_number)
        returning id, business_id, (xmax = 0) as created
        """,
        (business_id, PROVIDER, interaction_id, caller_phone, now),
    ).fetchone()
    if row["business_id"] != business_id:
        raise PermissionError("interaction belongs to another business")
    return row["id"], row["created"]


def link_call_client(conn: psycopg.Connection, call_id: UUID, client: Row) -> None:
    """Attach the identified patient. consent_recording comes from the registration form's
    consent (call_opt_in covers recording, docs/INTAKE_CONTRACT.md)."""
    conn.execute(
        """
        update public.calls set client_id = %s, consent_recording = %s,
          source = case when source = 'unknown' then %s::public.lead_source else source end
        where id = %s
        """,
        (client["id"], bool(client["call_opt_in"]), client["source"], call_id),
    )


def call_event(
    conn: psycopg.Connection,
    business_id: UUID,
    kind: EventType,
    *,
    call_id: UUID,
    interaction_id: str,
    now: datetime,
    language: str | None = None,
    client_id: UUID | None = None,
    source: LeadSource = LeadSource.UNKNOWN,
    **properties: Any,
) -> None:
    record_event(
        conn,
        FunnelEvent(
            business_id=business_id,
            type=kind,
            occurred_at=now,
            call_id=call_id,
            client_id=client_id,
            channel=Channel.VOICE,
            language=language,
            source=source,
            properties={"interaction_id": interaction_id, **properties},
        ),
    )


# ---------------------------------------------------------------------------
# Patients and appointments
# ---------------------------------------------------------------------------


def clients_for_phone(conn: psycopg.Connection, business_id: UUID, phone: str) -> list[Row]:
    """Patients registered on this number, or with it as their caregiver's number. Shared
    family numbers are normal, so there may be several."""
    return conn.execute(
        """
        select * from public.clients
        where business_id = %s and (phone = %s or caregiver_phone = %s)
        order by created_at, id
        """,
        (business_id, phone, phone),
    ).fetchall()


def get_client(conn: psycopg.Connection, business_id: UUID, client_id: UUID) -> Row | None:
    return conn.execute(
        "select * from public.clients where id = %s and business_id = %s",
        (client_id, business_id),
    ).fetchone()


def upcoming_appointment(
    conn: psycopg.Connection, business_id: UUID, client_id: UUID, now: datetime
) -> Row | None:
    return conn.execute(
        """
        select * from public.appointments
        where business_id = %s and client_id = %s and starts_at > %s and status = any(%s)
        order by starts_at limit 1
        """,
        (business_id, client_id, now, [s.value for s in ACTIVE_STATUSES]),
    ).fetchone()


def has_past_visits(conn: psycopg.Connection, business_id: UUID, client_id: UUID) -> bool:
    return (
        conn.execute(
            """
            select 1 from public.appointments
            where business_id = %s and client_id = %s
              and status in ('booked', 'confirmed', 'unconfirmed', 'showed', 'completed',
                             'pending_approval')
            limit 1
            """,
            (business_id, client_id),
        ).fetchone()
        is not None
    )


def get_appointment(
    conn: psycopg.Connection, business_id: UUID, appointment_id: UUID
) -> Row | None:
    return conn.execute(
        "select * from public.appointments where id = %s and business_id = %s",
        (appointment_id, business_id),
    ).fetchone()


def practitioner_names(
    conn: psycopg.Connection, business_id: UUID, ids: list[UUID], language: Language
) -> dict[UUID, str]:
    rows = conn.execute(
        "select id, name, display_names from public.practitioners "
        "where business_id = %s and id = any(%s)",
        (business_id, ids),
    ).fetchall()
    return {r["id"]: (r["display_names"] or {}).get(language) or r["name"] for r in rows}


# ---------------------------------------------------------------------------
# Staff tasks
# ---------------------------------------------------------------------------


def create_staff_task(
    conn: psycopg.Connection,
    business_id: UUID,
    *,
    kind: str,
    urgency: str,
    summary: str,
    actor: Actor,
    now: datetime,
    client_id: UUID | None = None,
    appointment_id: UUID | None = None,
) -> UUID:
    with conn.transaction():
        task_id = conn.execute(
            """
            insert into public.staff_tasks (business_id, client_id, appointment_id, call_id,
              kind, urgency, summary, channel, created_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id
            """,
            (
                business_id,
                client_id,
                appointment_id,
                actor.call_id,
                kind,
                urgency,
                summary,
                actor.channel.value,
                now,
            ),
        ).fetchone()["id"]
        record_event(
            conn,
            FunnelEvent(
                business_id=business_id,
                type=EventType.HANDOFF_TASK_CREATED,
                occurred_at=now,
                call_id=actor.call_id,
                client_id=client_id,
                appointment_id=appointment_id,
                channel=actor.channel,
                language=actor.language,
                properties={"kind": kind, "urgency": urgency, "task_id": str(task_id)},
            ),
        )
        if kind == "emergency":
            record_event(
                conn,
                FunnelEvent(
                    business_id=business_id,
                    type=EventType.EMERGENCY_DETECTED,
                    occurred_at=now,
                    call_id=actor.call_id,
                    client_id=client_id,
                    channel=actor.channel,
                    language=actor.language,
                ),
            )
        record_audit(
            conn,
            business_id=business_id,
            entity_type="staff_task",
            entity_id=task_id,
            action="created",
            actor=actor,
            changes={"kind": kind, "urgency": urgency},
        )
    return task_id


# ---------------------------------------------------------------------------
# Tool calls: log and idempotency per (business, interaction_id, tool, request hash)
# ---------------------------------------------------------------------------


def begin_tool_call(
    conn: psycopg.Connection,
    business_id: UUID,
    *,
    call_id: UUID,
    interaction_id: str,
    tool: str,
    request_hash: str,
    request: dict[str, Any],
) -> tuple[int | None, dict[str, Any] | None]:
    """(row id to finish, None) for a new call, or (None, stored response) for a repeat."""
    row = conn.execute(
        """
        insert into public.voice_tool_calls (business_id, call_id, interaction_id, tool,
          request_hash, request)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (business_id, interaction_id, tool, request_hash) do nothing
        returning id
        """,
        (business_id, call_id, interaction_id, tool, request_hash, Jsonb(request)),
    ).fetchone()
    if row is not None:
        return row["id"], None
    deadline = time.monotonic() + DUPLICATE_WAIT_SECONDS
    while True:
        existing = conn.execute(
            """
            select status, response from public.voice_tool_calls
            where business_id = %s and interaction_id = %s and tool = %s and request_hash = %s
            """,
            (business_id, interaction_id, tool, request_hash),
        ).fetchone()
        if existing is None:  # the first attempt failed and was cleared: run again
            return begin_tool_call(
                conn,
                business_id,
                call_id=call_id,
                interaction_id=interaction_id,
                tool=tool,
                request_hash=request_hash,
                request=request,
            )
        if existing["status"] == "done":
            return None, existing["response"]
        if time.monotonic() > deadline:
            return None, None
        time.sleep(0.1)


def finish_tool_call(
    conn: psycopg.Connection, row_id: int, response: dict[str, Any], *, ok: bool, duration_ms: int
) -> None:
    conn.execute(
        """
        update public.voice_tool_calls
        set status = 'done', response = %s, ok = %s, duration_ms = %s, completed_at = now()
        where id = %s
        """,
        (Jsonb(response), ok, duration_ms, row_id),
    )


def clear_tool_call(conn: psycopg.Connection, row_id: int) -> None:
    """After an unexpected error, so a retry runs the tool again."""
    conn.execute("delete from public.voice_tool_calls where id = %s", (row_id,))


def is_active(appointment: Row) -> bool:
    return appointment["status"] in {s.value for s in ACTIVE_STATUSES}
