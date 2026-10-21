"""Client intake: how newly registered clients (patients) arrive from a system we do not own.

The registration form belongs to someone else and its architecture is undecided, so intake is
an adapter. Every adapter turns an inbound request into an IntakeRecord; register_client() does
the rest (idempotent upsert, funnel event, audit, welcome job). Contract: docs/INTAKE_CONTRACT.md.

First adapter: an HMAC-signed JSON webhook.
  X-Intake-Timestamp: <unix seconds>
  X-Intake-Signature: v1=<hex HMAC-SHA256(secret, "<timestamp>.<raw body>")>
"""

from __future__ import annotations

import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

import psycopg
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from salesbot_api.records import Actor, enqueue_job, record_audit, record_event
from salesbot_core.events import Channel, EventType, FunnelEvent, LeadSource
from salesbot_core.packs.schema import Language

E164 = r"^\+[1-9][0-9]{7,14}$"
SIGNATURE_HEADER = "x-intake-signature"
TIMESTAMP_HEADER = "x-intake-timestamp"
# Sent only by the dev simulator; ignored when APP_ENV=production.
SIMULATION_HEADER = "x-intake-simulation"
SIGNATURE_VERSION = "v1"
# Reject requests signed more than this many seconds ago (or in the future): replay protection.
MAX_SKEW_SECONDS = 300

WELCOME_JOB = "welcome"


class IntakeRecord(BaseModel):
    """One registered client, exactly as the registration system sends it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    clinic_id: UUID
    external_patient_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(pattern=E164)
    preferred_language: Language
    dob: date | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    # The caregiver is a separate person: stored apart from the client, never merged.
    caregiver_name: str | None = Field(default=None, max_length=200)
    caregiver_phone: str | None = Field(default=None, pattern=E164)
    whatsapp_opt_in: bool
    call_opt_in: bool
    consent_at: AwareDatetime | None = None
    consent_source: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _consent_for_opt_in(self) -> IntakeRecord:
        if (self.whatsapp_opt_in or self.call_opt_in) and self.consent_at is None:
            raise ValueError("consent_at is required when whatsapp_opt_in or call_opt_in is true")
        return self


class IntakeRejectedError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


class IntakeAdapter(ABC):
    name: str

    @abstractmethod
    def parse(self, headers: Mapping[str, str], body: bytes, now: datetime) -> IntakeRecord:
        """Authenticate and parse a request. Raises IntakeRejectedError."""


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"{SIGNATURE_VERSION}={mac.hexdigest()}"


class HmacWebhookIntake(IntakeAdapter):
    name = "hmac_webhook"

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("INTAKE_HMAC_SECRET must be at least 32 characters")
        self._secret = secret

    def parse(self, headers: Mapping[str, str], body: bytes, now: datetime) -> IntakeRecord:
        lower = {k.lower(): v for k, v in headers.items()}
        try:
            timestamp = int(lower.get(TIMESTAMP_HEADER, ""))
        except ValueError as exc:
            raise IntakeRejectedError(401, "missing or invalid timestamp") from exc
        if abs(now.timestamp() - timestamp) > MAX_SKEW_SECONDS:
            raise IntakeRejectedError(401, "timestamp outside the allowed window")
        expected = sign(self._secret, timestamp, body)
        if not hmac.compare_digest(expected, lower.get(SIGNATURE_HEADER, "")):
            raise IntakeRejectedError(401, "bad signature")
        try:
            return IntakeRecord.model_validate(json.loads(body))
        except (ValueError, ValidationError) as exc:
            # Field names only: validation messages could echo personal data back into logs.
            fields = (
                sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
                if isinstance(exc, ValidationError)
                else []
            )
            raise IntakeRejectedError(422, f"invalid payload: {fields or 'not JSON'}") from exc


@dataclass(frozen=True)
class RegistrationResult:
    client_id: UUID
    created: bool
    welcome_queued: bool


def register_client(
    conn: psycopg.Connection,
    record: IntakeRecord,
    *,
    now: datetime,
    source: LeadSource = LeadSource.REGISTRATION_FORM,
) -> RegistrationResult:
    """Idempotent on (clinic_id, external_patient_id). A repeat updates the stored details
    (e.g. an opt-out) but never re-registers or re-sends the welcome."""
    actor = Actor(type="integration", channel=Channel.API, language=record.preferred_language)
    with conn.transaction():
        business = conn.execute(
            "select id from public.businesses where id = %s", (record.clinic_id,)
        ).fetchone()
        if business is None:
            raise IntakeRejectedError(422, "unknown clinic_id")
        row = conn.execute(
            """
            insert into public.clients (business_id, external_id, name, phone,
              preferred_language, date_of_birth, age, caregiver_name, caregiver_phone,
              whatsapp_opt_in, call_opt_in, consent_at, consent_source, source)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (business_id, external_id) do update set
              name = excluded.name, phone = excluded.phone,
              preferred_language = excluded.preferred_language,
              date_of_birth = excluded.date_of_birth, age = excluded.age,
              caregiver_name = excluded.caregiver_name,
              caregiver_phone = excluded.caregiver_phone,
              whatsapp_opt_in = excluded.whatsapp_opt_in, call_opt_in = excluded.call_opt_in,
              consent_at = excluded.consent_at, consent_source = excluded.consent_source
            returning id, (xmax = 0) as created
            """,
            (
                record.clinic_id,
                record.external_patient_id,
                record.name,
                record.phone,
                record.preferred_language,
                record.dob,
                record.age,
                record.caregiver_name,
                record.caregiver_phone,
                record.whatsapp_opt_in,
                record.call_opt_in,
                record.consent_at,
                record.consent_source,
                source.value,
            ),
        ).fetchone()
        client_id, created = row["id"], row["created"]

        if created:
            record_event(
                conn,
                FunnelEvent(
                    business_id=record.clinic_id,
                    type=EventType.CLIENT_REGISTERED,
                    occurred_at=now,
                    client_id=client_id,
                    channel=Channel.API,
                    language=record.preferred_language,
                    source=source,
                ),
            )
        record_audit(
            conn,
            business_id=record.clinic_id,
            entity_type="client",
            entity_id=client_id,
            action="registered" if created else "updated_by_intake",
            actor=actor,
            # Which consent flags arrived; no personal details in the audit diff.
            changes={
                "whatsapp_opt_in": record.whatsapp_opt_in,
                "call_opt_in": record.call_opt_in,
            },
        )

        # The welcome is a WhatsApp template, so it needs a WhatsApp opt-in. Calls are blocked
        # until Stage G. The dedupe key makes this a no-op once a welcome job exists.
        welcome_queued = False
        if record.whatsapp_opt_in:
            welcome_queued = (
                enqueue_job(
                    conn,
                    business_id=record.clinic_id,
                    kind=WELCOME_JOB,
                    run_at=now,
                    payload={"client_id": str(client_id)},
                    dedupe_key=f"{WELCOME_JOB}:{client_id}",
                    client_id=client_id,
                )
                is not None
            )
    return RegistrationResult(client_id=client_id, created=created, welcome_queued=welcome_queued)
