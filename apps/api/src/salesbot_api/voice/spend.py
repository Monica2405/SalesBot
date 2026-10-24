"""Spend guard for the shared Sarvam credit wallet (docs/COSTS.md, "Spend guard").

Before we start anything that spends credits (an outbound call, simulated test runs), its
worst-case cost is reserved in spend_ledger. If the reservation would pass the session cap
(SPEND_SESSION_CAP_INR, default Rs 100) or the daily cap (SPEND_DAILY_CAP_INR, default Rs 500,
IST day), nothing is started and SpendCapReachedError explains why. The end-of-call payload
then settles the actual amount. Inbound calls cannot be refused by us, but their actual spend
is recorded and counts toward the daily cap.

Used = settled amounts + open reservations. Reservations are serialised with an advisory lock
so two concurrent requests cannot both squeeze under a cap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from salesbot_api.records import record_event
from salesbot_api.settings import Settings
from salesbot_core.costs import SpendCapReachedError, SpendKind, check_spend_caps
from salesbot_core.events import Channel, EventType, FunnelEvent

log = logging.getLogger("salesbot.spend")
IST = ZoneInfo("Asia/Kolkata")
# One session per API process unless SPEND_SESSION_ID is set.
PROCESS_SESSION = f"api-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
_LOCK_KEY = 4_242_001  # pg_advisory_xact_lock key for spend reservations


def session_id(settings: Settings) -> str:
    return settings.spend_session_id or PROCESS_SESSION


def spend_day(now: datetime) -> date:
    return now.astimezone(IST).date()


@dataclass(frozen=True)
class SpendStatus:
    session_id: str
    day: date
    session_used: Decimal
    day_used: Decimal
    session_cap: Decimal
    day_cap: Decimal


_USED = """
    select coalesce(sum(case status when 'settled' then actual_inr
                                    when 'reserved' then estimated_inr else 0 end), 0) as used
    from public.spend_ledger where {where}
"""


def status(conn: psycopg.Connection, settings: Settings, now: datetime) -> SpendStatus:
    sid, day = session_id(settings), spend_day(now)
    session_used = conn.execute(_USED.format(where="session_id = %s"), (sid,)).fetchone()["used"]
    day_used = conn.execute(_USED.format(where="spend_day = %s"), (day,)).fetchone()["used"]
    return SpendStatus(
        sid,
        day,
        Decimal(session_used),
        Decimal(day_used),
        settings.spend_session_cap_inr,
        settings.spend_daily_cap_inr,
    )


def reserve(
    conn: psycopg.Connection,
    settings: Settings,
    *,
    kind: SpendKind,
    estimate: Decimal,
    now: datetime,
    business_id: UUID | None = None,
    note: str | None = None,
) -> int:
    """Reserve `estimate` rupees or raise SpendCapReachedError. Returns the ledger id."""
    with conn.transaction():
        conn.execute("select pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
        s = status(conn, settings, now)
        try:
            check_spend_caps(
                needed=estimate,
                session_used=s.session_used,
                day_used=s.day_used,
                session_cap=s.session_cap,
                day_cap=s.day_cap,
            )
        except SpendCapReachedError as exc:
            log.warning("spend cap reached: %s (kind=%s)", exc, kind.value)
            if business_id is not None:
                record_event(
                    conn,
                    FunnelEvent(
                        business_id=business_id,
                        type=EventType.SPEND_CAP_REACHED,
                        occurred_at=now,
                        channel=Channel.SYSTEM,
                        properties={
                            "kind": kind.value,
                            "scope": exc.scope,
                            "used_inr": str(exc.used),
                            "cap_inr": str(exc.cap),
                            "needed_inr": str(exc.needed),
                        },
                    ),
                )
            # The event must survive the failed reservation: commit it, then raise.
            return_exc: SpendCapReachedError | None = exc
        else:
            return_exc = None
            row = conn.execute(
                """
                insert into public.spend_ledger (business_id, kind, session_id, spend_day,
                  estimated_inr, note)
                values (%s, %s, %s, %s, %s, %s) returning id
                """,
                (business_id, kind.value, s.session_id, s.day, estimate, note),
            ).fetchone()
            log.info(
                "spend reserved: Rs %s for %s (session Rs %s/%s, day Rs %s/%s)",
                estimate,
                kind.value,
                s.session_used + estimate,
                s.session_cap,
                s.day_used + estimate,
                s.day_cap,
            )
    if return_exc is not None:
        raise return_exc
    return row["id"]


def release(conn: psycopg.Connection, ledger_id: int) -> None:
    conn.execute(
        "update public.spend_ledger set status = 'released', settled_at = now() "
        "where id = %s and status = 'reserved'",
        (ledger_id,),
    )


def link_attempt(conn: psycopg.Connection, ledger_id: int, attempt_id: str, call_id: UUID) -> None:
    conn.execute(
        "update public.spend_ledger set attempt_id = %s, call_id = %s where id = %s",
        (attempt_id, call_id, ledger_id),
    )


def settle_call(
    conn: psycopg.Connection,
    settings: Settings,
    *,
    business_id: UUID | None,
    call_id: UUID | None,
    attempt_id: str | None,
    interaction_id: str | None,
    actual: Decimal,
    now: datetime,
) -> None:
    """Record a finished call's actual spend from the end-of-call payload. Settles the
    outbound reservation, or adds an inbound row. Idempotent per interaction."""
    if interaction_id is not None:
        done = conn.execute(
            "select 1 from public.spend_ledger where interaction_id = %s and status = 'settled'",
            (interaction_id,),
        ).fetchone()
        if done:
            return
    updated = None
    if attempt_id is not None:
        updated = conn.execute(
            """
            update public.spend_ledger
            set status = 'settled', actual_inr = %s, interaction_id = %s, settled_at = %s
            where attempt_id = %s and status = 'reserved' returning id
            """,
            (actual, interaction_id, now, attempt_id),
        ).fetchone()
    if updated is None:
        conn.execute(
            """
            insert into public.spend_ledger (business_id, kind, session_id, spend_day,
              estimated_inr, actual_inr, status, call_id, attempt_id, interaction_id,
              settled_at)
            values (%s, %s, %s, %s, 0, %s, 'settled', %s, %s, %s, %s)
            on conflict (interaction_id) where interaction_id is not null do nothing
            """,
            (
                business_id,
                (SpendKind.OUTBOUND_CALL if attempt_id else SpendKind.INBOUND_CALL).value,
                session_id(settings),
                spend_day(now),
                actual,
                call_id,
                attempt_id,
                interaction_id,
                now,
            ),
        )
