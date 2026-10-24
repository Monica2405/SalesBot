"""Sarvam's call-completion webhooks: the authoritative end-of-call record.

    POST /api/v1/voice/webhooks/{VOICE_WEBHOOK_SECRET}/inbound    inbound deployment webhook
    POST /api/v1/voice/webhooks/{VOICE_WEBHOOK_SECRET}/outbound   instant outbound webhook

Payloads follow docs.sarvam.ai (Deployments webhook payload, Instant Outbound webhook
payload). Sarvam documents no signature for them, so the secret is in the URL (see
security.py). Each payload sets the call's status, duration, transcript, final agent variables
and cost fields (agent minutes and telephony pulses derived from `duration`, which is the only
billing figure in the payload), settles the spend ledger and logs the call's spend. The
language of each turn is then fetched from the Analytics API when it is configured.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from salesbot_api import db
from salesbot_api.api_v1 import get_conn
from salesbot_api.settings import Settings, get_settings
from salesbot_api.voice import spend, store
from salesbot_api.voice.sarvam import analytics_client, recording_ref
from salesbot_api.voice.security import require_webhook_token
from salesbot_core.costs import call_cost
from salesbot_core.events import EventType
from salesbot_core.voice import language_code

log = logging.getLogger("salesbot.voice")
router = APIRouter(
    prefix="/api/v1/voice/webhooks/{token}",
    tags=["voice"],
    dependencies=[Depends(require_webhook_token)],
)
ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Turn(_Payload):
    role: str
    en_text: str | None = None
    indic_text: str | None = None


class InboundCallEnded(_Payload):
    """Deployments webhook payload."""

    app_id: str
    app_version: int | None = None
    deployment_id: str | None = None
    interaction_id: str
    user_phone_number: str | None = None
    agent_phone_number: str | None = None
    duration: float = 0.0
    final_agent_variables: dict[str, Any] | None = None
    output_agent_variables: dict[str, Any] | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    interaction_transcript: list[Turn] | None = None
    metadata: dict[str, Any] | None = None


class WebhookConfigEcho(_Payload):
    url: str | None = None
    metadata: dict[str, Any] | None = None


class OutboundCallEnded(_Payload):
    """Instant Outbound webhook payload."""

    attempt_id: str
    status: Literal["connected", "no_answer", "busy", "failed"]
    channel_info: dict[str, Any] | None = None
    duration: float | None = None
    interaction_id: str | None = None
    failure_reason: str | None = None
    final_agent_variables: dict[str, Any] | None = None
    webhook_config: WebhookConfigEcho | None = None
    interaction_transcript: list[Turn] | None = None


STATUS = {"connected": "completed", "no_answer": "no_answer", "busy": "busy", "failed": "failed"}


def _business_for(
    conn: psycopg.Connection, metadata: dict[str, Any] | None, variables: dict[str, Any] | None,
    agent_number: str | None,
) -> store.Business | None:  # fmt: skip
    for source in (metadata or {}, variables or {}):
        slug = source.get("clinic") or source.get("clinic_slug")
        if slug and (business := store.business_by_slug(conn, str(slug))):
            return business
    return store.business_by_number(conn, agent_number) if agent_number else None


def finalize_call(
    conn: psycopg.Connection,
    settings: Settings,
    *,
    business: store.Business,
    call_id: UUID,
    status: str,
    duration: float | None,
    interaction_id: str | None,
    attempt_id: str | None,
    app_id: str | None,
    transcript: list[Turn] | None,
    variables: dict[str, Any] | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    failure_reason: str | None,
    now: datetime,
) -> None:
    connected = status == "completed"
    cost = call_cost(duration if connected else 0)
    variables = variables or {}
    summary = variables.get("summary") or variables.get("call_summary")
    outcome = variables.get("outcome") or variables.get("call_outcome")
    with conn.transaction():
        conn.execute(
            """
            update public.calls set
              provider_call_id = coalesce(provider_call_id, %s),
              status = %s,
              duration_seconds = %s,
              started_at = coalesce(%s, started_at),
              ended_at = coalesce(%s, ended_at, %s),
              transcript = coalesce(transcript, '{}'::jsonb) || %s,
              agent_variables = %s,
              summary = coalesce(%s, summary),
              outcome = coalesce(%s, outcome),
              failure_reason = %s,
              recording_ref = %s,
              agent_minutes = %s, telephony_pulses = %s, forwarding_pulses = %s,
              cost_inr_estimate = %s, rates_verified_on = %s
            where id = %s
            """,
            (
                interaction_id,
                status,
                round(duration) if duration else None,
                started_at,
                ended_at,
                now,
                Jsonb({"sarvam": [t.model_dump() for t in transcript]} if transcript else {}),
                Jsonb(variables),
                str(summary)[:4000] if summary else None,
                str(outcome)[:100] if outcome else None,
                failure_reason,
                recording_ref(app_id, interaction_id) if connected and interaction_id else None,
                cost.agent_minutes,
                cost.telephony_pulses,
                cost.forwarding_pulses,
                cost.inr,
                cost.rates_verified_on,
                call_id,
            ),
        )
        spend.settle_call(
            conn,
            settings,
            business_id=business.id,
            call_id=call_id,
            attempt_id=attempt_id,
            interaction_id=interaction_id,
            actual=cost.inr,
            now=now,
        )
        ended = conn.execute(
            "select 1 from public.events where call_id = %s and type = 'call_ended'", (call_id,)
        ).fetchone()
        if not ended:
            store.call_event(
                conn, business.id, EventType.CALL_ENDED, call_id=call_id,
                interaction_id=interaction_id or "", now=now, status=status,
                attempt_id=attempt_id,
            )  # fmt: skip
    # Interaction ids, durations and amounts are not personal data.
    log.info(
        "call spend: interaction %s, %s, %ss -> %d agent min + %d pulses = Rs %s (rates of %s)",
        interaction_id, status, round(duration or 0), cost.agent_minutes, cost.telephony_pulses,
        cost.inr, cost.rates_verified_on,
    )  # fmt: skip


def store_turn_languages(settings: Settings, call_id: UUID, interaction_id: str) -> None:
    """Background task: language per turn from the Analytics API (read-only, not billed)."""
    try:
        languages = analytics_client(settings).turn_languages(interaction_id)
        if not languages:
            return
        with db.connect(settings, autocommit=True) as conn:
            conn.execute(
                "update public.calls set turn_languages = %s, language = coalesce(language, %s) "
                "where id = %s",
                (Jsonb(languages), language_code(languages[0]), call_id),
            )
    except Exception as exc:  # best effort: the call record is already complete
        log.warning("turn languages not fetched for %s (%s)", interaction_id, type(exc).__name__)


@router.post("/inbound")
def inbound_call_ended(
    payload: InboundCallEnded,
    conn: ConnDep,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    business = _business_for(
        conn, payload.metadata, payload.final_agent_variables, payload.agent_phone_number
    )
    if business is None:
        log.warning("inbound webhook for unknown clinic (interaction %s)", payload.interaction_id)
        return {"ok": False, "reason": "unknown clinic"}
    call_id, _ = store.ensure_call(
        conn, business.id, payload.interaction_id, caller_phone=payload.user_phone_number, now=now
    )
    finalize_call(
        conn, settings, business=business, call_id=call_id,
        status="completed" if payload.duration > 0 else "abandoned",
        duration=payload.duration, interaction_id=payload.interaction_id, attempt_id=None,
        app_id=payload.app_id, transcript=payload.interaction_transcript,
        variables={**(payload.final_agent_variables or {}),
                   **(payload.output_agent_variables or {})},
        started_at=payload.start_datetime, ended_at=payload.end_datetime,
        failure_reason=None, now=now,
    )  # fmt: skip
    background.add_task(store_turn_languages, settings, call_id, payload.interaction_id)
    return {"ok": True}


@router.post("/outbound")
def outbound_call_ended(
    payload: OutboundCallEnded,
    conn: ConnDep,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    row = conn.execute(
        "select id, business_id from public.calls where attempt_id = %s", (payload.attempt_id,)
    ).fetchone()
    if row is None:
        log.warning("outbound webhook for unknown attempt %s", payload.attempt_id)
        return {"ok": False, "reason": "unknown attempt"}
    business = conn.execute(
        "select slug from public.businesses where id = %s", (row["business_id"],)
    ).fetchone()
    found = store.business_by_slug(conn, business["slug"])
    assert found is not None  # noqa: S101 (the row exists: calls.business_id is a FK)
    finalize_call(
        conn, settings, business=found, call_id=row["id"], status=STATUS[payload.status],
        duration=payload.duration, interaction_id=payload.interaction_id,
        attempt_id=payload.attempt_id, app_id=settings.sarvam_app_id,
        transcript=payload.interaction_transcript, variables=payload.final_agent_variables,
        started_at=None, ended_at=None, failure_reason=payload.failure_reason, now=now,
    )  # fmt: skip
    if payload.interaction_id:
        background.add_task(store_turn_languages, settings, row["id"], payload.interaction_id)
    return {"ok": True}
