# Decisions

Status: **Decided** / **Open** / **Deferred**. Open decisions must not be made in code without
the owner's sign-off (see CLAUDE.md).

## Decided

### Hosting split
- Supabase for Postgres, Auth and Storage.
- Vercel hosts only `apps/admin` (static SPA, Root Directory `apps/admin`).
- `apps/api` and `apps/voice-agent` ship as Docker images for a long-running container host.
  Voice is never on Vercel (time-limited functions; WebSockets close at the time limit).

### Supabase region: Mumbai (ap-south-1)
Closest Supabase region to India for latency to the voice agent and owners.

### Hosted Supabase dev project (2026-10-21)
The owner created a hosted dev project and fills `.env` themselves (keys never go in chat or
commits). Approved for linking and pushing migrations. **Test patients only: no real patient
data in dev.**

### Schema source of truth
`supabase/migrations/*.sql` only. No Alembic.

### Anvia Health Phase 1: appointment management (2026-10-21)
Built as generic code plus a clinic pack, so other verticals (e.g. a Kyvo prototype) become
another pack. Generic names in the schema: `clients` (patients), `practitioners` (doctors).
- **Intake** goes through a swappable adapter. First implementation: an HMAC-signed, idempotent
  webhook (docs/INTAKE_CONTRACT.md). Registration itself is out of scope (owned by another team).
- **WhatsApp: Meta Cloud API directly**, starting with Meta's test number. Webhook signatures
  are verified with the app secret.
- **Dev webhook URL: Cloudflare quick tunnel** from the owner's laptop until the container host
  is chosen. The URL changes on every restart; the owner is told each time to update Meta.
- **Anvia's database is the source of truth** for availability and bookings. Google Calendar is
  optional, one-way (Anvia → doctor's calendar), no two-way sync in Phase 1.
- **No call audio is recorded or stored.** Transcripts, summaries, per-turn language and
  appointment data only. Transcripts are kept in dev until the retention decision below.
- **Wording policy (owner's decision):** patient-facing text never says or hints that the patient
  is talking to an AI, bot, virtual or automated assistant, and never claims to be a person or
  staff member. If sincerely asked, one short truthful line (pack text, DRAFT until reviewed).
  Enforced by a word-scan test. Admin screens and docs may say AI.
- **Every scheduling value is a per-clinic setting** (`scheduling_settings`). Defaults approved
  by the owner: slot hold 5 min, minimum lead time 60 min, lookahead 14 days, 9 days per list,
  doctor choice `any_available` (or `default_practitioner`; the form may send a doctor),
  optional first-visit duration per doctor (falls back to consultation length),
  `reschedule_approval = auto` (or `staff`), fallback language = clinic `default_language`
  (English if unset).
- **Reminder, confirmation and call policy defaults** (per clinic; clinics choose WhatsApp,
  call or both): confirmation request on WhatsApp right after booking; nudge after 6h; if still
  unconfirmed 24h before, one call; then a staff task. Reminders 24h and 2h before on WhatsApp.
  Quiet hours 21:00–08:00 IST. Call window 09:00–19:00 IST, max 3 attempts, 60 min apart.
  **Outbound calls stay blocked until the telephony decision (Stage G).**
- **Escalations in testing:** staff tasks in the admin only (see "Alert channel" below).

## Deferred

### Local database (deferred 2026-10-19)
Docker is not running on the dev machine for now, so the local Supabase stack is not used.
- `make db-up`, `db-down`, `db-reset` need Docker + Supabase CLI and fail with a clear message
  when Docker is not running.
- Migrations and seed are written but not run locally. CI runs them on every PR against a local
  Supabase in GitHub Actions, together with the cross-business RLS isolation test.
- Locally the RLS test skips when no database is reachable.

**When a database is needed**, pick one:
1. **Hosted Supabase dev project** (Mumbai). Free plan pauses after 7 days of inactivity, so expect
   to un-pause it. Never put real customer data in it. Created and approved 2026-10-21.
2. **Start Docker** and run `make db-up && make db-reset`.

## Open

### Container host for api and voice-agent
Needs: long-running processes, WebSockets, low latency to India (Mumbai region), Docker images,
secrets management, cheap at low volume. Not chosen. Candidates to evaluate later.

### Telephony provider: Plivo vs Exotel
Both behind `TelephonyAdapter`; only the mock exists. Compare: Indian number availability and
KYC, media streaming over WebSocket (needed for Pipecat), per-minute cost, transfer support (for
handoff), recording, webhook signatures.

### WhatsApp provider for production
Phase 1 builds on the Meta Cloud API directly (see Decided). Still open for production: stay on
the Cloud API or move to a BSP; Meta business verification, a real number and display-name
approval; per-message pricing by template category. Hindi and Marathi templates need native
review and separate Meta approval.

### Human handoff and alert channel (required before any pilot)
How an emergency or "talk to a human" request reaches a person: live transfer through telephony,
an urgent WhatsApp/SMS to clinic staff, or both; business-hours rules. Today: `StubHandoff` never
connects, so the **callback request** fallback is used, and Anvia creates **staff tasks** in the
admin. **Staff tasks alone are acceptable for testing only. A real alert channel for emergencies
and escalations is required before any pilot with real patients.**

### Supabase plan
Free plan pauses projects after 7 days idle and has small limits. **Move to Pro before any real
pilot** (no pausing, daily backups).

### Data retention and DPDP compliance
Transcripts, intake data, appointment history and health-adjacent details (age, reason for a
visit) are personal data under the DPDP Act 2023. No call audio is stored. To decide (legal input
needed):
- Retention periods for transcripts, conversation turns, audit log and inactive patients;
  deletion on request (right to erasure) and what must be kept for clinic records.
- Consent: is the intake form's `consent_at` / `consent_source` enough for WhatsApp messages and
  outbound calls, per purpose (appointment management vs anything else)? Wording per language.
- Caregivers: consent when a caregiver's number is used; whose data it is.
- Data processors and location: Supabase (Mumbai), Meta (WhatsApp), Sarvam (STT/LLM/TTS),
  telephony provider, Google (optional calendar). Processing terms with each.
- Children's data: verifiable parental consent for patients under 18.
- Breach process and the notice owed to patients and the Data Protection Board.
- Legal review of the wording policy: patient-facing text does not mention automation (owner's
  decision, see Decided). Confirm it is compatible with any disclosure rule that applies.

### Telecom rules for outbound calls (TRAI / DLT, Stage G)
Blocks real outbound calls. To decide with the chosen telephony provider:
- Are appointment confirmation and reminder calls "transactional/service" calls under TRAI's
  commercial communication rules (TCCCPR 2018 and later amendments), and what registration does
  that need (DLT entity, headers, consent templates)?
- Number declaration: which numbers the clinic calls from, the 140/160-series rules for
  promotional vs service calls, and caller-ID display.
- DND / NCPR scrubbing: needed for service calls to patients who opted in?
- Calling hours and frequency limits; how a patient opts out on a call.
- Automated voice calls: any extra registration or disclosure the carrier requires.
