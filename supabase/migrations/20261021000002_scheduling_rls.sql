-- RLS for appointment management.
-- Roles (business_members.role):
--   owner, admin        manage settings, practitioners and schedules; see everything
--   receptionist, staff see everything operational; manage schedule exceptions (leave, holidays)
--   practitioner        sees only their own appointments and the clients booked with them
-- Bookings, holds, cancels and reschedules are written by apps/api (service role) through the one
-- booking engine, so staff and the AI follow the same rules. The admin app only gets narrow
-- column updates (pausing automation).

-- ---------------------------------------------------------------------------
-- Helpers (SECURITY DEFINER, pinned search_path, same pattern as is_business_member)
-- ---------------------------------------------------------------------------
create function public.has_staff_access(bid uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.business_members m
    where m.business_id = bid and m.user_id = (select auth.uid())
      and m.role in ('owner', 'admin', 'receptionist', 'staff')
  );
$$;

create function public.is_own_practitioner(pid uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.practitioners p
    where p.id = pid and p.user_id = (select auth.uid())
  );
$$;

create function public.can_see_client(bid uuid, cid uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select public.has_staff_access(bid) or exists (
    select 1
    from public.appointments a
    join public.practitioners p on p.id = a.practitioner_id
    where a.client_id = cid and a.business_id = bid and p.user_id = (select auth.uid())
  );
$$;

revoke all on function public.has_staff_access(uuid) from public, anon;
revoke all on function public.is_own_practitioner(uuid) from public, anon;
revoke all on function public.can_see_client(uuid, uuid) from public, anon;
grant execute on function public.has_staff_access(uuid) to authenticated, service_role;
grant execute on function public.is_own_practitioner(uuid) to authenticated, service_role;
grant execute on function public.can_see_client(uuid, uuid) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Enable RLS on the new tables
-- ---------------------------------------------------------------------------
alter table public.practitioners        enable row level security;
alter table public.practitioner_hours   enable row level security;
alter table public.schedule_exceptions  enable row level security;
alter table public.clients              enable row level security;
alter table public.scheduling_settings  enable row level security;
alter table public.audit_log            enable row level security;
alter table public.jobs                 enable row level security;

revoke all on public.practitioners, public.practitioner_hours, public.schedule_exceptions,
  public.clients, public.scheduling_settings, public.audit_log, public.jobs from anon;

-- ---------------------------------------------------------------------------
-- Clinic setup: members read; owners/admins write. Exceptions also by front-desk staff.
-- ---------------------------------------------------------------------------
create policy practitioners_select on public.practitioners
  for select to authenticated using (public.is_business_member(business_id));
create policy practitioners_write on public.practitioners
  for all to authenticated
  using (public.has_business_role(business_id, array['owner', 'admin']))
  with check (public.has_business_role(business_id, array['owner', 'admin']));

create policy practitioner_hours_select on public.practitioner_hours
  for select to authenticated using (public.is_business_member(business_id));
create policy practitioner_hours_write on public.practitioner_hours
  for all to authenticated
  using (public.has_business_role(business_id, array['owner', 'admin']))
  with check (public.has_business_role(business_id, array['owner', 'admin']));

create policy schedule_exceptions_select on public.schedule_exceptions
  for select to authenticated using (public.is_business_member(business_id));
create policy schedule_exceptions_write on public.schedule_exceptions
  for all to authenticated
  using (public.has_business_role(business_id, array['owner', 'admin', 'receptionist', 'staff']))
  with check (public.has_business_role(business_id,
                                       array['owner', 'admin', 'receptionist', 'staff']));

create policy scheduling_settings_select on public.scheduling_settings
  for select to authenticated using (public.is_business_member(business_id));
create policy scheduling_settings_write on public.scheduling_settings
  for all to authenticated
  using (public.has_business_role(business_id, array['owner', 'admin']))
  with check (public.has_business_role(business_id, array['owner', 'admin']));

-- ---------------------------------------------------------------------------
-- Clients: staff see all; a practitioner sees only clients booked with them.
-- Created by the intake adapter (server). The admin may only pause automation.
-- ---------------------------------------------------------------------------
create policy clients_select on public.clients
  for select to authenticated using (public.can_see_client(business_id, id));
create policy clients_pause on public.clients
  for update to authenticated
  using (public.has_staff_access(business_id))
  with check (public.has_staff_access(business_id));
revoke insert, update, delete on public.clients from authenticated;
grant update (automation_paused) on public.clients to authenticated;

-- ---------------------------------------------------------------------------
-- Appointments: replace the scaffold policies.
-- ---------------------------------------------------------------------------
drop policy appointments_select on public.appointments;
drop policy appointments_update on public.appointments;

create policy appointments_select on public.appointments
  for select to authenticated
  using (public.has_staff_access(business_id)
         or (public.is_business_member(business_id)
             and public.is_own_practitioner(practitioner_id)));
create policy appointments_pause on public.appointments
  for update to authenticated
  using (public.has_staff_access(business_id))
  with check (public.has_staff_access(business_id));
revoke insert, update, delete on public.appointments from authenticated;
grant update (automation_paused) on public.appointments to authenticated;

-- ---------------------------------------------------------------------------
-- Operational data with client details: staff only (not practitioners).
-- ---------------------------------------------------------------------------
create policy audit_log_select on public.audit_log
  for select to authenticated using (public.has_staff_access(business_id));
create policy jobs_select on public.jobs
  for select to authenticated using (public.has_staff_access(business_id));

drop policy events_select on public.events;
drop policy events_insert on public.events;
create policy events_select on public.events
  for select to authenticated using (public.has_staff_access(business_id));
create policy events_insert on public.events
  for insert to authenticated with check (public.has_staff_access(business_id));

drop policy calls_select on public.calls;
create policy calls_select on public.calls
  for select to authenticated using (public.has_staff_access(business_id));

drop policy leads_select on public.leads;
drop policy leads_insert on public.leads;
drop policy leads_update on public.leads;
create policy leads_select on public.leads
  for select to authenticated using (public.has_staff_access(business_id));
create policy leads_insert on public.leads
  for insert to authenticated with check (public.has_staff_access(business_id));
create policy leads_update on public.leads
  for update to authenticated
  using (public.has_staff_access(business_id))
  with check (public.has_staff_access(business_id));
