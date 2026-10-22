# Decisions

Status: **Decided** / **Open** / **Deferred**. Open decisions must not be made in code without
the owner's sign-off (see CLAUDE.md).

## Decided

### Hosting split
- Supabase for Postgres, Auth and Storage.
- Vercel hosts only `apps/admin` (static SPA, Root Directory `apps/admin`).
- `apps/api` ships as a Docker image for a long-running container host (host still open).
  Voice runs on Sarvam's managed platform (see below), so there is no voice container any
  more. The API is never on Vercel either: Sarvam's tool calls and the WhatsApp webhooks need
  an always-on, low-latency service.

### Voice platform: Sarvam Voice Agents (owner, 2026-10-22)
- **Pipecat is out.** Calls run entirely on Sarvam Voice Agents, a managed platform whose
  per-minute price includes the speech, language and voice models. We run no voice pipeline,
  WebRTC transport or telephony serializers. `apps/voice-agent` is removed (Step 3).
- **Telephony for the pilot: Sarvam telephony** (Vobiz, numbers rented from Sarvam).
  Bring-your-own (Plivo, Exotel) stays a documented fallback. No number is rented and no KYC
  is started without the owner's go.
- **WhatsApp stays ours:** Meta Cloud API through our own adapter in `apps/api`. Sarvam's
  WhatsApp channel is enterprise-only; we do not plan around it.
- **All business logic stays on our side** (booking, availability, patients, reminders,
  Google Calendar push, audit log) so the voice vendor can be swapped later. Sarvam's agent
  calls our API through API tools (webhooks) plus on-start and on-end hooks.
- The pack stays the source of truth: the Sarvam agent instruction, greetings and FAQ text
  are generated from it (`docs/SARVAM_AGENT.md`, Step 3).
- Prices and limits: `docs/COSTS.md` (Step 3).

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
- **Call audio may be recorded via Sarvam; consent is captured at registration.** We store
  transcripts, summaries, language per turn and appointment data. Access is scoped per
  clinic. Retention is a decision to make. (Owner, 2026-10-22; replaces the earlier "no
  audio" rule.) Details:
  - We prefer linking to Sarvam's recordings through their recording API: we store only the
    interaction id and the retrieval reference, not the audio. The private `recordings`
    bucket and `calls.recording_path` stay for optional copies later.
  - For review in the admin we keep transcript, summary, language per turn, outcome and tool
    calls.
  - The registration form's consent text must cover call recording (docs/INTAKE_CONTRACT.md).
    `calls.consent_recording` is set from that consent. No recording notice in the call
    opening line.
  - **Until the consent wording is agreed, voice testing is on the owner's team's phones
    only.** Sarvam's recording retention is being investigated (Step 3D).
- **Wording policy (owner's decision, final 2026-10-22)**, for the agent instruction, WhatsApp
  templates, pack text and every spoken line, in en, hi and mr:
  - Never say or imply unprompted that the person is talking to an AI, bot, virtual or
    automated assistant. Never claim to be human, a staff member or someone at the clinic.
    No fake human cues.
  - If someone sincerely asks whether they are talking to a person or a machine, answer
    truthfully in one short line (per-language pack text, DRAFT until reviewed), then
    continue. Never deny it.
  - Internal admin screens and docs may say AI.
  - Enforced by a word-scan test (en, hi, mr) over all patient-facing text, including the
    generated agent instruction. Only the sincere-ask answer lines are allowlisted.
- **Conversation decisions (owner, 2026-10-21, Stage B):**
  - Every patient-facing sentence comes from **pack templates** with slots (`{doctor}`,
    `{date}`). An LLM may later help understand messages but never writes replies.
  - Replies follow the language of each message. Romanized Hindi or Marathi ("kal 11 baje",
    "udya sakali") that clearly reads as one of them is answered in Devanagari. Short neutral
    replies ("ok", "2") never switch. Unsupported scripts get the clinic's default language.
  - **DRAFT text** is blocked from real patients until reviewed: the sincere-ask answer lines in
    every language, and every Hindi and Marathi line until a native speaker reviews it. Live
    sending of DRAFT text fails closed; the dev console shows it tagged `[DRAFT]`.
  - Voice opening line: the "AI assistant" wording is removed. The recording-consent
    question is dropped too (2026-10-22): consent comes from registration (see above).
  - Language detection here is ours and serves text channels (WhatsApp, the console). Voice
    calls use Sarvam's own language-switch setting; we do not build a detector for voice.
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
  **No real outbound calls until the owner says so:** `OUTBOUND_CALLS_ENABLED=false` with a
  dry-run mode (Step 3), plus the telecom questions below.
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

### Container host for the api
Needs: always-on HTTPS for Sarvam tool calls and WhatsApp webhooks, low latency to India
(Mumbai region), Docker images, secrets management, cheap at low volume. The voice-agent
container is no longer needed. Not chosen.

### Telephony beyond the pilot
The pilot uses Sarvam telephony (see Decided). Bring-your-own Plivo or Exotel is the
documented fallback if Sarvam numbers, KYC, caller ID or pricing do not work out. Findings on
renting from Sarvam, call forwarding, caller ID and inbound/outbound on one number: Step 3D.

### WhatsApp provider for production
Phase 1 builds on the Meta Cloud API directly through our own adapter (see Decided); Sarvam's
WhatsApp channel is enterprise-only and not part of the plan. Still open for production: stay on
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
visit) are personal data under the DPDP Act 2023. Call audio may be recorded by Sarvam (see
Decided). To decide (legal input needed):
- **Legal review of recording consent and DPDP before real patients.** The registration
  form's consent text must cover call recording; the wording needs sign-off in en, hi and mr.
  Until it is agreed, voice testing is on the owner's team's phones only.
- Retention of call recordings held by Sarvam, and whether we ever copy them to our bucket.
- Retention periods for transcripts, conversation turns, audit log and inactive patients;
  deletion on request (right to erasure) and what must be kept for clinic records.
- Consent: is the intake form's `consent_at` / `consent_source` enough for WhatsApp messages and
  outbound calls, per purpose (appointment management vs anything else)? Wording per language.
- Caregivers: consent when a caregiver's number is used; whose data it is.
- Data processors and location: Supabase (Mumbai), Meta (WhatsApp), Sarvam (voice platform,
  telephony, call recordings and transcripts), Google (optional calendar). Processing terms
  with each.
- Children's data: verifiable parental consent for patients under 18.
- Breach process and the notice owed to patients and the Data Protection Board.
- Legal review of the wording policy: patient-facing text does not mention automation (owner's
  decision, see Decided). Confirm it is compatible with any disclosure rule that applies.

### Telecom rules for outbound calls (TRAI / DLT)
Blocks real outbound calls. To settle with Sarvam (what they handle vs what stays on us is
investigated in Step 3D):
- Are appointment confirmation and reminder calls "transactional/service" calls under TRAI's
  commercial communication rules (TCCCPR 2018 and later amendments), and what registration does
  that need (DLT entity, headers, consent templates)?
- Number declaration: which numbers the clinic calls from, the 140/160-series rules for
  promotional vs service calls, and caller-ID display.
- DND / NCPR scrubbing: needed for service calls to patients who opted in?
- Calling hours and frequency limits; how a patient opts out on a call.
- Automated voice calls: any extra registration or disclosure the carrier requires.
