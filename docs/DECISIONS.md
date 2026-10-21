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
Closest Supabase region to India for latency to the voice agent and owners. Recorded here only;
**no project is linked yet**. Linking needs explicit approval.

### Schema source of truth
`supabase/migrations/*.sql` only. No Alembic.

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
   to un-pause it. Never put real customer data in it. Needs approval to create/link.
2. **Start Docker** and run `make db-up && make db-reset`.

## Open

### Container host for api and voice-agent
Needs: long-running processes, WebSockets, low latency to India (Mumbai region), Docker images,
secrets management, cheap at low volume. Not chosen. Candidates to evaluate later.

### Telephony provider: Plivo vs Exotel
Both behind `TelephonyAdapter`; only the mock exists. Compare: Indian number availability and
KYC, media streaming over WebSocket (needed for Pipecat), per-minute cost, transfer support (for
handoff), recording, webhook signatures.

### WhatsApp provider
Used for booking confirmations, reminders and owner alerts. Options include Meta Cloud API
directly or a BSP. Compare: template approval, per-conversation cost, India support.
`WHATSAPP_PROVIDER=mock` until decided.

### Human handoff
How an emergency or "talk to a human" request reaches a person: live transfer through telephony,
an urgent WhatsApp/SMS to the owner, or both; business-hours rules. Today: `StubHandoff` never
connects, so the **callback request** fallback is always used.

### Supabase plan
Free plan pauses projects after 7 days idle and has small limits. **Move to Pro before any real
pilot** (no pausing, daily backups, more storage for recordings).

### Data retention and DPDP compliance
Recordings, transcripts and intake answers are personal data (sometimes health data). To decide:
retention periods (recordings vs transcripts vs leads), deletion on request, consent wording in
each language (legal review), data processing terms with providers, where data is processed
(Sarvam, telephony), and a breach process.
