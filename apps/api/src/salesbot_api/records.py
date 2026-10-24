"""Append-only records written alongside every state change: funnel events, audit log, jobs.

All functions take an open connection and run inside the caller's transaction, so a state
change and its records commit or roll back together. Never put personal data in job errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from salesbot_core.events import Channel, FunnelEvent

ActorType = Literal["client", "staff", "system", "integration"]


@dataclass(frozen=True)
class Actor:
    """Who or what caused a change. Recorded in the audit log and on funnel events."""

    type: ActorType
    channel: Channel
    user_id: UUID | None = None
    language: str | None = None
    # The call this change happened on (voice), so bookings are attributed to the call.
    call_id: UUID | None = None


SYSTEM = Actor(type="system", channel=Channel.SYSTEM)


def record_event(conn: psycopg.Connection, event: FunnelEvent) -> None:
    conn.execute(
        """
        insert into public.events (business_id, type, occurred_at, call_id, lead_id,
          appointment_id, client_id, channel, language, source, value_inr, properties)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event.business_id,
            event.type.value,
            event.occurred_at,
            event.call_id,
            event.lead_id,
            event.appointment_id,
            event.client_id,
            event.channel.value if event.channel else None,
            event.language,
            event.source.value,
            event.value_inr,
            Jsonb(event.properties),
        ),
    )


def record_audit(
    conn: psycopg.Connection,
    *,
    business_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
    actor: Actor,
    changes: dict[str, Any] | None = None,
    client_message: str | None = None,
) -> None:
    conn.execute(
        """
        insert into public.audit_log (business_id, entity_type, entity_id, action, actor_type,
          actor_user_id, channel, changes, client_message)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            business_id,
            entity_type,
            entity_id,
            action,
            actor.type,
            actor.user_id,
            actor.channel.value,
            Jsonb(changes or {}),
            client_message,
        ),
    )


def enqueue_job(
    conn: psycopg.Connection,
    *,
    business_id: UUID,
    kind: str,
    run_at: datetime,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    appointment_id: UUID | None = None,
    client_id: UUID | None = None,
) -> int | None:
    """Queue a job. Returns its id, or None if a job with the same dedupe_key already exists."""
    row = conn.execute(
        """
        insert into public.jobs (business_id, kind, run_at, payload, dedupe_key,
          appointment_id, client_id)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (business_id, dedupe_key) do nothing
        returning id
        """,
        (business_id, kind, run_at, Jsonb(payload or {}), dedupe_key, appointment_id, client_id),
    ).fetchone()
    return None if row is None else _first(row)


def cancel_queued_jobs(
    conn: psycopg.Connection, appointment_id: UUID, kinds: list[str] | None = None
) -> int:
    """Stop outdated work for an appointment (after a reschedule, cancel or confirm)."""
    if kinds is None:
        cur = conn.execute(
            "update public.jobs set status = 'cancelled' "
            "where appointment_id = %s and status = 'queued'",
            (appointment_id,),
        )
    else:
        cur = conn.execute(
            "update public.jobs set status = 'cancelled' "
            "where appointment_id = %s and status = 'queued' and kind = any(%s)",
            (appointment_id, kinds),
        )
    return cur.rowcount


def _first(row: Any) -> Any:
    return row["id"] if isinstance(row, dict) else row[0]
