-- Row Level Security: an owner only ever sees their own business.
-- The admin app uses the anon key + the owner's JWT, so these policies are the security boundary.
-- apps/api uses the service role (bypasses RLS) for webhooks and call writes.

-- ---------------------------------------------------------------------------
-- Helpers. SECURITY DEFINER so policies can read business_members without recursing into
-- business_members' own RLS. search_path is pinned to avoid hijacking.
-- ---------------------------------------------------------------------------
create function public.is_business_member(bid uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.business_members m
    where m.business_id = bid and m.user_id = (select auth.uid())
  );
$$;

create function public.has_business_role(bid uuid, roles text[]) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.business_members m
    where m.business_id = bid and m.user_id = (select auth.uid()) and m.role = any (roles)
  );
$$;

revoke all on function public.is_business_member(uuid) from public, anon;
revoke all on function public.has_business_role(uuid, text[]) from public, anon;
grant execute on function public.is_business_member(uuid) to authenticated, service_role;
grant execute on function public.has_business_role(uuid, text[]) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere and shut out anon entirely.
-- ---------------------------------------------------------------------------
alter table public.businesses           enable row level security;
alter table public.business_members     enable row level security;
alter table public.packs_applied        enable row level security;
alter table public.script_versions      enable row level security;
alter table public.leads                enable row level security;
alter table public.calls                enable row level security;
alter table public.lead_events          enable row level security;
alter table public.appointments         enable row level security;
alter table public.events               enable row level security;
alter table public.knowledge_items      enable row level security;
alter table public.unanswered_questions enable row level security;
alter table public.follow_up_sequences  enable row level security;
alter table public.usage_records        enable row level security;

revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;
alter default privileges for role postgres in schema public revoke all on tables from anon;
alter default privileges for role postgres in schema public revoke all on sequences from anon;

-- ---------------------------------------------------------------------------
-- Policies (authenticated role only). No policy = no access for that command.
-- Inserts of new businesses/members happen server-side (onboarding via apps/api).
-- ---------------------------------------------------------------------------

-- businesses: members read, owners/admins edit settings
create policy businesses_select on public.businesses
  for select to authenticated using (public.is_business_member(id));
create policy businesses_update on public.businesses
  for update to authenticated
  using (public.has_business_role(id, array['owner', 'admin']))
  with check (public.has_business_role(id, array['owner', 'admin']));

-- business_members: members can see who else is on their team
create policy business_members_select on public.business_members
  for select to authenticated using (public.is_business_member(business_id));

-- Read-only for owners (written by the server)
create policy packs_applied_select on public.packs_applied
  for select to authenticated using (public.is_business_member(business_id));
create policy calls_select on public.calls
  for select to authenticated using (public.is_business_member(business_id));
create policy usage_records_select on public.usage_records
  for select to authenticated using (public.is_business_member(business_id));
create policy follow_up_sequences_select on public.follow_up_sequences
  for select to authenticated using (public.is_business_member(business_id));

-- script_versions: members read, owners/admins create new versions
create policy script_versions_select on public.script_versions
  for select to authenticated using (public.is_business_member(business_id));
create policy script_versions_insert on public.script_versions
  for insert to authenticated
  with check (public.has_business_role(business_id, array['owner', 'admin']));

-- leads: members read and move through stages; creation is by the agent (server) or members
create policy leads_select on public.leads
  for select to authenticated using (public.is_business_member(business_id));
create policy leads_insert on public.leads
  for insert to authenticated with check (public.is_business_member(business_id));
create policy leads_update on public.leads
  for update to authenticated
  using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));

-- lead_events: append from the admin (stage changes); no edits
create policy lead_events_select on public.lead_events
  for select to authenticated using (public.is_business_member(business_id));
create policy lead_events_insert on public.lead_events
  for insert to authenticated with check (public.is_business_member(business_id));

-- appointments: members read and mark showed / no-show
create policy appointments_select on public.appointments
  for select to authenticated using (public.is_business_member(business_id));
create policy appointments_update on public.appointments
  for update to authenticated
  using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));

-- events: members read; members may append (e.g. payment_recorded from the admin)
create policy events_select on public.events
  for select to authenticated using (public.is_business_member(business_id));
create policy events_insert on public.events
  for insert to authenticated with check (public.is_business_member(business_id));

-- knowledge base: full CRUD for members
create policy knowledge_items_all on public.knowledge_items
  for all to authenticated
  using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));

-- unanswered questions: members read and resolve
create policy unanswered_questions_select on public.unanswered_questions
  for select to authenticated using (public.is_business_member(business_id));
create policy unanswered_questions_update on public.unanswered_questions
  for update to authenticated
  using (public.is_business_member(business_id))
  with check (public.is_business_member(business_id));
