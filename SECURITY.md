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
- It must **never** appear in `apps/admin`, in any `VITE_` variable, in browser code, in logs, or
  in the voice agent's client-facing paths.
- The admin build fails if a `VITE_` variable contains a service role key or a Supabase secret key
  (`apps/admin/vite.config.ts`).
- The admin app uses the anon key plus the owner's JWT. Access control is enforced by RLS
  policies in `supabase/migrations`, tested by `supabase/tests/rls_isolation.sql` in CI.

## Call recordings and personal data

Call recordings, transcripts, phone numbers and intake answers (which can include health
information for clinics) are **personal data** under India's DPDP Act.

- Recording starts only after the caller consents (disclosure step at the start of every call).
  Declined or unclear consent = no recording.
- Recordings go to the private `recordings` bucket at `{business_id}/{call_id}.*`. Owners read them
  only through short-lived signed URLs, which Storage issues only if the RLS policy allows it.
- Never put recordings, transcripts or real phone numbers in logs, test fixtures, issues, PRs or
  commits. Audio files are gitignored.
- Retention period and deletion process are open decisions (docs/DECISIONS.md).

## Reporting

Report suspected vulnerabilities privately to the repository owner, not in a public issue.
