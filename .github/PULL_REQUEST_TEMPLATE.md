## What

<!-- One or two sentences. -->

## Why / what it lets us measure or convert

<!-- Which funnel stage does this move (calls -> leads -> bookings -> shows -> paid)?
     Which metric will show it worked? -->

## How I tested

- [ ] `make lint`
- [ ] `make test`
- [ ] Manual check (describe):

## Checklist

- [ ] No industry-specific logic in the engine (it belongs in a pack)
- [ ] Schema changes are a new file in `supabase/migrations/` (+ RLS policies for new tables)
- [ ] No secrets, no service role key in `apps/admin` or any `VITE_` variable
- [ ] No open decision made silently (see `docs/DECISIONS.md`)
- [ ] Docs updated if behaviour changed
