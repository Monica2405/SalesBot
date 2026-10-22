# CLAUDE.md

Guidance for Claude (and humans) working in this repo.

## What this is

An inbound AI voice receptionist for small businesses (Hindi, Marathi, English). It books
appointments, captures every lead, and shows the owner what happened. It must be cheap to run and
work well. The admin app is the real product. Calls run on Sarvam Voice Agents (managed); all
business logic stays in our API so the voice vendor can be swapped.

## Why this project exists

It is preparation for a **GTM (go-to-market) engineer** role: building revenue systems (CRM
integration, workflow automation, funnel analytics, lead scoring, source attribution, follow-up
automation, AI agents judged on conversion). Every feature must be measurable in revenue terms:

**calls → leads → bookings → shows → paid**

When designing anything, ask: *what does this let us measure or convert?* See docs/GTM.md.

## Principles

- **One generic engine + industry packs.** Industry behaviour is YAML in `packs/`, validated by
  `salesbot_core.packs.schema.Pack`. Never hardcode dentist (or any industry) logic in the engine.
  If you need an `if industry == ...`, the pack schema is missing a field.
- **Events are the source of truth for metrics.** Every funnel step writes an append-only row to
  `events` (`salesbot_core.events.EventType` must match the SQL CHECK list).
- **Every call stores** `script_version_id`, lead `source`, and cost fields: `agent_minutes`
  (60-second pulses, rounded up) and `telephony_pulses` (30-second pulses, rounded up), read
  from Sarvam's end-of-call payload. WhatsApp messages are counted by pricing category. Rates
  live in a config file with a "last verified" date; docs/COSTS.md is the source.
- **Business logic stays on our side.** Booking, availability, patients, reminders, calendar
  push and the audit log live in `apps/api` + Postgres. Sarvam's agent only calls our API tools
  and on-start / on-end hooks. Nothing that would stop us swapping voice vendors.
- **Providers behind interfaces.** Voice platform, outbound calls, WhatsApp, calendar, CRM: each
  has a working mock. Never guess a provider's endpoint, field name or limit: read their docs
  and leave a TODO (or ask) if unsure.
- **Supabase migrations are the only schema source.** No Alembic, no ORM models defining tables.
  Python uses psycopg + Pydantic.
- **RLS on every table with business data.** New table = `business_id` + RLS policies + extend
  `supabase/tests/rls_isolation.sql`.
- **Wording rule (patient-facing text, en/hi/mr, including the generated agent instruction).**
  Never say or imply unprompted that the person is talking to an AI, bot, virtual or automated
  assistant; never claim to be human or clinic staff; no fake human cues. A sincere "am I
  talking to a machine?" gets one short truthful line (pack text, DRAFT until reviewed). A
  word-scan test enforces it; only the sincere-ask lines are allowlisted. Admin and docs may
  say AI.
- **Recording.** Call audio may be recorded via Sarvam; consent is captured at registration.
  Store the interaction id and Sarvam's retrieval reference, not the audio. Until the consent
  wording is legally agreed, voice tests use the owner's team's phones only.
- **Vercel hosts only `apps/admin`.** `apps/api` runs on a long-running container host. We run
  no voice pipeline ourselves.
- Keep it simple. No frameworks beyond the stack below without asking.

## Stack

Python 3.12 + uv workspace (`packages/core`, `apps/api`) · FastAPI + Pydantic Settings ·
psycopg 3 · React + TypeScript + Vite + react-router + @supabase/supabase-js · Supabase
(Postgres, Auth, Storage) · Sarvam Voice Agents (managed voice + telephony) · Meta WhatsApp
Cloud API (own adapter) · ruff · eslint · pytest. No Pipecat. (`apps/voice-agent` is being
removed in Stage B Step 3.)

## Commands

```bash
make setup        # deps + hooks
make test         # pytest + admin build
make lint         # ruff + eslint + tsc
make format
make dev-api | dev-admin
make console ARGS='--lang mr'     # chat with the appointment flow in the terminal (no DB)
make db-up | db-reset | db-down   # need Docker + Supabase CLI (local DB currently deferred)
```

On Windows run `make` from Git Bash.

## Conventions

- Git: never commit to `main`. Work on a branch, open a PR. Small logical commits. Ask before pushing.
- Python: ruff (line length 100), type hints, async for I/O, `StrEnum` for enumerations stored in DB.
- New migration: `supabase/migrations/<YYYYMMDDHHMMSS>_<name>.sql`; never edit an applied migration.
- Secrets only in `.env` (gitignored). `.env.example` lists every key with empty values.
- The service role key is server-only. Never in `apps/admin`, never in a `VITE_` variable.
- Recordings and transcripts are personal data: never in logs, issues, fixtures or commits.

## Do not decide without asking

- LICENSE (none for now)
- Container host for the api
- Telephony beyond the pilot (pilot = Sarvam telephony; bring-your-own Plivo/Exotel is the fallback)
- Renting a number or starting KYC; enabling real outbound calls
- Spending Sarvam credits (simulated test runs cost money)
- WhatsApp provider for production
- Human handoff mechanism
- Adding any paid dependency or service
- Linking a Supabase or Vercel project, or changing the Supabase region (Mumbai, ap-south-1)
- Pushing to the remote, merging PRs
- Data retention periods and DPDP compliance choices

Open decisions are tracked in docs/DECISIONS.md.
