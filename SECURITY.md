# Security

## Secrets

- Real values live only in `.env` (repo root) and `apps/admin/.env`, both gitignored.
  `.env.example` files list the keys with empty values.
- Deployed services get secrets from the host's secret manager (Vercel env vars, container host
  secrets), never from files in the image. `.dockerignore` excludes `.env*`.
- `gitleaks` runs as a pre-commit hook and in CI. If a secret is committed, rotate it first,
  then clean history.
- Google OAuth credential/token JSON files are gitignored. Per-business refresh tokens are stored
  server-side only.

## The Supabase service role key

`SUPABASE_SERVICE_ROLE_KEY` bypasses Row Level Security: it can read and write every business.

- It is used **only** by `apps/api` (and server-side jobs).
- It must **never** appear in `apps/admin`, in any `VITE_` variable, in browser code or in logs.
- The admin build fails if a `VITE_` variable contains a service role key or a Supabase secret key
  (`apps/admin/vite.config.ts`).
- The admin app uses the anon key plus the owner's JWT. Access control is enforced by RLS
  policies in `supabase/migrations`, tested by `supabase/tests/rls_isolation.sql` in CI.

## Voice platform (Sarvam) credentials

- `SARVAM_VOICE_API_KEY` is server-only and spends credits from the organisation's shared wallet. It is
  never printed, logged or put in the agent definition.
- `VOICE_TOOL_SECRET` authenticates Sarvam's calls to our tools and hooks (bearer token). It is
  stored in Sarvam's Settings -> Secrets, never typed into a tool config.
- `VOICE_WEBHOOK_SECRET` is the path token on Sarvam's call-completion webhooks, which cannot send
  headers and carry no documented signature. Treat the full webhook URL as a secret; rotate it if
  it leaks. `VOICE_IP_ALLOWLIST` can restrict callers to Sarvam's documented IPs.
- Wrong or missing credentials get a bare 401. Validation errors name fields only and never echo
  values; tool failures return a safe spoken line and log only the error type and location.

## Call recordings and personal data

Call recordings, transcripts, phone numbers and intake answers (which can include health
information for clinics) are **personal data** under India's DPDP Act.

- Sarvam records every connected call (stereo WAV) and keeps recordings and transcripts until a
  workspace retention period is set (docs/DECISIONS.md). Consent to recording is captured on the
  registration form (`call_opt_in`, docs/INTAKE_CONTRACT.md) and copied to
  `calls.consent_recording`; the call itself has no recording notice.
- We store only `calls.recording_ref` (how to fetch the recording from Sarvam), not the audio. The
  private `recordings` bucket stays for optional copies later, read only through signed URLs.
- Sarvam's Analytics API returns the caller's full, unmasked number: treat its responses as
  personal data and keep them out of logs. Our logs mask phone numbers (`+91******3210`).
- Until the consent wording is legally agreed, voice tests use the owner's team's phones only.
- Never put recordings, transcripts or real phone numbers in logs, test fixtures, issues, PRs or
  commits. Audio files are gitignored.
- Retention period and deletion process are open decisions (docs/DECISIONS.md).

## Reporting

Report suspected vulnerabilities privately to the repository owner, not in a public issue.
