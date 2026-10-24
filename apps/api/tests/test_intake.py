import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from salesbot_api import api_v1
from salesbot_api.intake import (
    HmacWebhookIntake,
    IntakeRecord,
    IntakeRejectedError,
    RegistrationResult,
    register_client,
    sign,
)
from salesbot_api.main import app
from salesbot_core.events import LeadSource

SECRET = "test-only-" + "x" * 32  # dummy HMAC key, long enough for the min-length check
NOW = datetime(2030, 1, 7, 3, 0, tzinfo=UTC)
CLINIC = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def payload(**overrides) -> dict:
    data = {
        "clinic_id": str(CLINIC),
        "external_patient_id": "P-1001",
        "name": "Test Patient",
        "phone": "+919000000001",
        "preferred_language": "mr",
        "age": 34,
        "caregiver_name": "Test Caregiver",
        "caregiver_phone": "+919000000002",
        "whatsapp_opt_in": True,
        "call_opt_in": False,
        "consent_at": "2030-01-06T10:00:00+05:30",
        "consent_source": "registration_form_v1",
    }
    data.update(overrides)
    return data


def signed(body: bytes, *, ts: int | None = None, secret: str = SECRET) -> dict[str, str]:
    ts = int(NOW.timestamp()) if ts is None else ts
    return {"X-Intake-Timestamp": str(ts), "X-Intake-Signature": sign(secret, ts, body)}


# ---------------------------------------------------------------------------
# HMAC adapter
# ---------------------------------------------------------------------------


def test_valid_signature_parses_record():
    body = json.dumps(payload()).encode()
    record = HmacWebhookIntake(SECRET).parse(signed(body), body, NOW)
    assert record.external_patient_id == "P-1001"
    assert record.caregiver_phone == "+919000000002"  # kept separate from the patient
    assert record.phone == "+919000000001"


@pytest.mark.parametrize(
    "headers",
    [
        lambda b: {},
        lambda b: signed(b, secret="wrong-secret-that-is-also-long-enough-xx"),
        lambda b: signed(b, ts=int(NOW.timestamp()) - 301),  # replay window
        lambda b: signed(b, ts=int(NOW.timestamp()) + 301),
        lambda b: {**signed(b), "X-Intake-Timestamp": "yesterday"},
    ],
)
def test_bad_or_stale_signature_is_401(headers):
    body = json.dumps(payload()).encode()
    with pytest.raises(IntakeRejectedError) as exc:
        HmacWebhookIntake(SECRET).parse(headers(body), body, NOW)
    assert exc.value.status_code == 401


def test_tampered_body_is_401():
    body = json.dumps(payload()).encode()
    headers = signed(body)
    tampered = json.dumps(payload(phone="+919999999999")).encode()
    with pytest.raises(IntakeRejectedError):
        HmacWebhookIntake(SECRET).parse(headers, tampered, NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"phone": "9000000001"},  # not E.164
        {"preferred_language": "ta"},
        {"whatsapp_opt_in": True, "consent_at": None},  # opt-in without consent
        {"whatsapp_opt_in": False, "call_opt_in": False, "consent_at": None},  # always required
        {"consent_source": None},
        {"consent_source": ""},
        {"consent_at": "2030-01-06T10:00:00"},  # naive timestamp
        {"unexpected": "field"},
        {"age": 200},
    ],
)
def test_invalid_payload_is_422_without_echoing_values(overrides):
    body = json.dumps(payload(**overrides)).encode()
    with pytest.raises(IntakeRejectedError) as exc:
        HmacWebhookIntake(SECRET).parse(signed(body), body, NOW)
    assert exc.value.status_code == 422
    assert "9000000001" not in exc.value.reason and "Test Patient" not in exc.value.reason


def test_consent_is_required_even_without_opt_in():
    record = IntakeRecord.model_validate(payload(whatsapp_opt_in=False, call_opt_in=False))
    assert record.consent_at is not None and record.consent_source


def test_short_secret_is_refused():
    with pytest.raises(ValueError):
        HmacWebhookIntake("short")


# ---------------------------------------------------------------------------
# Route (DB replaced by a stub)
# ---------------------------------------------------------------------------


def test_route_returns_503_when_secret_not_configured(client):
    assert client.post("/api/v1/intake/patients", content=b"{}").status_code == 503


def test_route_created_then_duplicate(client, settings, monkeypatch):
    app.dependency_overrides[api_v1.get_intake_adapter] = lambda: HmacWebhookIntake(SECRET)
    monkeypatch.setattr(api_v1, "utcnow", lambda: NOW)
    calls = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_register(conn, record, *, now, source):
        calls.append(source)
        return RegistrationResult(uuid.uuid4(), created=len(calls) == 1, welcome_queued=True)

    monkeypatch.setattr(api_v1.db, "connect", lambda s, autocommit=False: FakeConn())
    monkeypatch.setattr(api_v1, "register_client", fake_register)
    body = json.dumps(payload()).encode()
    first = client.post("/api/v1/intake/patients", content=body, headers=signed(body))
    second = client.post("/api/v1/intake/patients", content=body, headers=signed(body))
    assert (first.status_code, first.json()["status"]) == (201, "created")
    assert (second.status_code, second.json()["status"]) == (200, "already_registered")
    bad = client.post("/api/v1/intake/patients", content=body, headers={})
    assert bad.status_code == 401
    assert calls == [LeadSource.REGISTRATION_FORM] * 2

    client.post(
        "/api/v1/intake/patients",
        content=body,
        headers={**signed(body), "X-Intake-Simulation": "1"},
    )
    assert calls[-1] == LeadSource.SIMULATION
    settings.app_env = "production"
    client.post(
        "/api/v1/intake/patients",
        content=body,
        headers={**signed(body), "X-Intake-Simulation": "1"},
    )
    assert calls[-1] == LeadSource.REGISTRATION_FORM  # never honoured in production


# ---------------------------------------------------------------------------
# register_client against the database
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_register_is_idempotent_and_queues_one_welcome(conn, clinic):
    record = IntakeRecord.model_validate(payload(clinic_id=str(clinic.business_id)))
    first = register_client(conn, record, now=NOW, source=LeadSource.SIMULATION)
    second = register_client(conn, record, now=NOW + timedelta(minutes=1))
    assert first.created and not second.created
    assert first.client_id == second.client_id
    assert first.welcome_queued and not second.welcome_queued

    jobs = conn.execute(
        "select kind from public.jobs where client_id = %s", (first.client_id,)
    ).fetchall()
    assert [j["kind"] for j in jobs] == ["welcome"]
    events = conn.execute(
        "select type, channel, language, source from public.events where client_id = %s",
        (first.client_id,),
    ).fetchall()
    assert events == [
        {"type": "client_registered", "channel": "api", "language": "mr", "source": "simulation"}
    ]
    row = conn.execute(
        "select caregiver_name, caregiver_phone, phone from public.clients where id = %s",
        (first.client_id,),
    ).fetchone()
    assert row == {
        "caregiver_name": "Test Caregiver",
        "caregiver_phone": "+919000000002",
        "phone": "+919000000001",
    }


@pytest.mark.db
def test_repeat_with_opt_out_updates_consent(conn, clinic):
    record = IntakeRecord.model_validate(payload(clinic_id=str(clinic.business_id)))
    first = register_client(conn, record, now=NOW)
    opted_out = IntakeRecord.model_validate(
        payload(clinic_id=str(clinic.business_id), whatsapp_opt_in=False)
    )
    register_client(conn, opted_out, now=NOW)
    row = conn.execute(
        "select whatsapp_opt_in from public.clients where id = %s", (first.client_id,)
    ).fetchone()
    assert row["whatsapp_opt_in"] is False


@pytest.mark.db
def test_no_whatsapp_opt_in_means_no_welcome(conn, clinic):
    record = IntakeRecord.model_validate(
        payload(
            clinic_id=str(clinic.business_id),
            external_patient_id="P-2",
            whatsapp_opt_in=False,
            call_opt_in=True,
        )
    )
    result = register_client(conn, record, now=NOW)
    assert result.created and not result.welcome_queued


@pytest.mark.db
def test_unknown_clinic_is_rejected(conn):
    record = IntakeRecord.model_validate(payload(clinic_id=str(uuid.uuid4())))
    with pytest.raises(IntakeRejectedError) as exc:
        register_client(conn, record, now=NOW)
    assert exc.value.status_code == 422
