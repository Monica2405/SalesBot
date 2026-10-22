# Intake contract: new patient registered

Patients register through a form that **another team owns**. Anvia does not build that form and
never registers patients on calls or WhatsApp. When a patient registers, the form's backend tells
Anvia with one signed HTTP request. Anvia then stores the patient and starts the welcome flow.

The form's architecture is not decided, so intake sits behind an adapter
(`salesbot_api.intake.IntakeAdapter`). This page describes the first adapter: a signed webhook.

## Endpoint

```
POST /api/v1/intake/patients
Content-Type: application/json
X-Intake-Timestamp: <unix time in seconds>
X-Intake-Signature: v1=<hex HMAC-SHA256>
```

## Body

| Field | Type | Required | Notes |
|---|---|---|---|
| `clinic_id` | UUID | yes | Anvia's id for the clinic (printed by `load_clinic`). |
| `external_patient_id` | string (≤200) | yes | The form's own patient id. **Idempotency key** together with `clinic_id`. |
| `name` | string (≤200) | yes | Patient's name. |
| `phone` | string | yes | Patient's phone in **E.164**, e.g. `+919000000001`. Family members may share a number. |
| `preferred_language` | `en` \| `hi` \| `mr` | yes | First message language. Later turns follow the patient's replies. |
| `dob` | date `YYYY-MM-DD` | no | Either `dob` or `age` (or neither). |
| `age` | integer 0–130 | no | |
| `caregiver_name` | string | no | A caregiver is a **separate person**. Stored apart from the patient, never merged. |
| `caregiver_phone` | string (E.164) | no | |
| `whatsapp_opt_in` | boolean | yes | Anvia sends **no WhatsApp message** without it. |
| `call_opt_in` | boolean | yes | Anvia makes **no call** without it. (Outbound calls are disabled until the telephony decision.) |
| `consent_at` | ISO 8601 with timezone | if any opt-in is true | When the patient gave consent. |
| `consent_source` | string | no | Where consent was captured, e.g. `registration_form_v3`. |

Unknown fields are rejected (`422`), so typos never pass silently.

```json
{
  "clinic_id": "6f1c…",
  "external_patient_id": "P-1001",
  "name": "Test Patient",
  "phone": "+919000000001",
  "preferred_language": "mr",
  "age": 34,
  "caregiver_name": "Test Caregiver",
  "caregiver_phone": "+919000000002",
  "whatsapp_opt_in": true,
  "call_opt_in": false,
  "consent_at": "2026-10-21T10:00:00+05:30",
  "consent_source": "registration_form_v1"
}
```

## Consent wording the form must show (for the form owner)

Calls to and from the clinic may be **recorded** by our voice provider (Sarvam). The call
itself does not ask for recording consent, so the registration form must. `call_opt_in: true`
means the patient agreed to the text below, including recording, and Anvia sets
`calls.consent_recording` from it (with `consent_at` and `consent_source`). Change the
`consent_source` value whenever the wording changes, so every patient's consent can be traced
to the exact text they saw.

Required points, in the patient's language:
1. The clinic may contact them on WhatsApp and by phone about their appointments
   (booking, confirmations, reminders, changes).
2. Phone calls may be recorded and transcribed, to manage appointments and improve service.
3. Their data is handled by the clinic and its service providers, and they can withdraw
   consent at any time (how: e.g. reply STOP, or ask the clinic).

**DRAFT wording (English), not yet legally reviewed:**

> I agree that {clinic name} may contact me on WhatsApp and by phone about my appointments.
> Calls may be recorded and transcribed to manage my appointments and improve service. I can
> withdraw this consent at any time by replying STOP or by telling the clinic.

Hindi and Marathi versions need a native speaker and the same legal review. **Until the
wording is agreed (docs/DECISIONS.md, "Data retention and DPDP compliance"), voice testing is
on the owner's team's phones only, and no real patient is called.**

## Signature

```
signature = "v1=" + hex(HMAC_SHA256(INTAKE_HMAC_SECRET, "<X-Intake-Timestamp>." + <raw request body bytes>))
```

- Sign the **exact bytes** you send. Re-serialising the JSON after signing breaks the signature.
- The timestamp must be within **±300 seconds** of Anvia's clock (replay protection).
- `INTAKE_HMAC_SECRET` is at least 32 characters, shared once over a secure channel, and rotated
  if it leaks. Never put it in the form's browser code: sign on the form's server.

Python example:

```python
import hashlib, hmac, json, time, urllib.request

body = json.dumps(payload).encode()
ts = str(int(time.time()))
sig = hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    URL,
    data=body,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-Intake-Timestamp": ts,
        "X-Intake-Signature": f"v1={sig}",
    },
)
```

## Responses

| Status | Body | Meaning |
|---|---|---|
| `201` | `{"client_id", "status": "created", "welcome_queued"}` | New patient stored. Welcome queued if WhatsApp opt-in. |
| `200` | `{"client_id", "status": "already_registered", "welcome_queued": false}` | Same `(clinic_id, external_patient_id)` seen before. Details (name, phone, language, opt-ins, consent) are **updated**, so a later opt-out is honoured. The welcome is never sent twice. |
| `401` | | Missing/invalid signature or timestamp outside ±300 s. |
| `422` | `{"detail": "invalid payload: [field names]"}` | Validation failed. Only field names are returned, never values. Unknown `clinic_id` also returns 422. |
| `503` | | Intake or database not configured. Retry later. |

**Retries:** safe. The same request any number of times gives the same patient, one
`client_registered` event and at most one welcome. Retry on network errors and 5xx with backoff.

## What Anvia does with it

1. Upserts the patient (`clients` table, RLS by clinic) in one transaction with:
   a `client_registered` funnel event (channel `api`, language = `preferred_language`) and an
   audit row (consent flags only, no personal details in the diff).
2. If `whatsapp_opt_in`, queues one `welcome` job. The worker (Stage D) sends the approved
   registration template with a "Book my first appointment" button. Opt-in is checked again
   at send time.
3. No opt-in: the patient is stored but never contacted automatically.

## Testing without the real form (dev only)

Set `INTAKE_HMAC_SECRET` in `.env`, run the API (`make dev-api`), then:

```bash
uv run --package salesbot-api python -m salesbot_api.tools.simulate_intake \
  --clinic-id <clinic uuid> --name "Test Patient" --phone +9198XXXXXXXX --lang mr
# --external-id P-1 to resend the same patient, --no-whatsapp, --call, --caregiver-name/-phone,
# --dry-run to print the signed request
```

Simulated submissions carry `X-Intake-Simulation: 1` and are stored with `source = simulation`,
which metrics exclude. The header is ignored when `APP_ENV=production`. Use test patients who
agreed to receive test messages; never real patient data.
