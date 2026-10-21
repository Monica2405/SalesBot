# CLAUDE.md

Guidance for Claude (and humans) working in this repo.

## What this is

An inbound AI voice receptionist for small businesses (Hindi, Marathi, English). It books
appointments, captures every lead, and shows the owner what happened. It must be cheap to run and
work well. The admin app is the real product. Voice providers are swappable.

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
- **Every call stores** `script_version_id`, lead `source`, and cost fields
  (`stt_seconds`, `llm_tokens_in`, `llm_tokens_out`, `tts_characters`).
- **Providers behind interfaces** (`salesbot_core.providers`). Each has a working mock. Never guess
  a provider's endpoint or model name: read their docs and leave a TODO if unsure.
- **Supabase migrations are the only schema source.** No Alembic, no ORM models defining tables.
  Python uses psycopg + Pydantic.
- **RLS on every table with business data.** New table = `business_id` + RLS policies + extend
  `supabase/tests/rls_isolation.sql`.
- **Voice is never on Vercel.** Vercel hosts only `apps/admin`.
- Keep it simple. No frameworks beyond the stack below without asking.

## Stack

Python 3.12 + uv workspace (`packages/core`, `apps/api`, `apps/voice-agent`) · FastAPI +
Pydantic Settings · Pipecat · psycopg 3 · React + TypeScript + Vite + react-router +
@supabase/supabase-js · Supabase (Postgres, Auth, Storage) · ruff · eslint · pytest.

## Commands

```bash
make setup        # deps + hooks
make test         # pytest + admin build
make lint         # ruff + eslint + tsc
make format
make dev-api | dev-agent | dev-admin
make db-up | db-reset | db-down   # need Docker + Supabase CLI (local DB currently deferred)
uv run python -m salesbot_agent --demo --pack salon --lang mr
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
- Container host for api and voice-agent
- Telephony provider (Plivo vs Exotel)
- WhatsApp provider
- Human handoff mechanism
- Adding any paid dependency or service
- Linking a Supabase or Vercel project, or changing the Supabase region (Mumbai, ap-south-1)
- Pushing to the remote, merging PRs
- Data retention periods and DPDP compliance choices

Open decisions are tracked in docs/DECISIONS.md.
