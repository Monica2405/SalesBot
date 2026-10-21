-- Proves an owner of business A cannot read or write business B's data.
-- Run inside a transaction that is rolled back (supabase/tests/test_rls_isolation.py does this).
-- Any failed check raises an exception, which fails the test.

-- ---------------------------------------------------------------------------
-- 1. Structural: every public table with a business_id column has RLS on and >= 1 policy.
-- ---------------------------------------------------------------------------
do $$
declare
  t record;
begin
  for t in
    select c.relname, c.relrowsecurity,
           (select count(*) from pg_policies p
             where p.schemaname = 'public' and p.tablename = c.relname) as policies
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and (exists (select 1 from information_schema.columns col
                   where col.table_schema = 'public' and col.table_name = c.relname
                     and col.column_name = 'business_id')
           or c.relname = 'businesses')
  loop
    if not t.relrowsecurity then
      raise exception 'RLS is not enabled on public.%', t.relname;
    end if;
    if t.policies = 0 then
      raise exception 'public.% has RLS but no policies', t.relname;
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 2. Fixtures (as postgres, bypassing RLS): two businesses, one owner each.
-- ---------------------------------------------------------------------------
insert into auth.users (id, aud, role, email)
values ('a0000000-0000-0000-0000-00000000000a', 'authenticated', 'authenticated', 'owner-a@rls.test'),
       ('b0000000-0000-0000-0000-00000000000b', 'authenticated', 'authenticated', 'owner-b@rls.test');

insert into public.businesses (id, name, slug, pack_id)
values ('a1000000-0000-0000-0000-0000000000a1', 'Business A', 'rls-test-a', 'dentist'),
       ('b1000000-0000-0000-0000-0000000000b1', 'Business B', 'rls-test-b', 'salon');

insert into public.business_members (business_id, user_id, role)
values ('a1000000-0000-0000-0000-0000000000a1', 'a0000000-0000-0000-0000-00000000000a', 'owner'),
       ('b1000000-0000-0000-0000-0000000000b1', 'b0000000-0000-0000-0000-00000000000b', 'owner');

insert into public.leads (id, business_id, name, phone)
values ('a2000000-0000-0000-0000-0000000000a2', 'a1000000-0000-0000-0000-0000000000a1', 'Lead A', '+911'),
       ('b2000000-0000-0000-0000-0000000000b2', 'b1000000-0000-0000-0000-0000000000b1', 'Lead B', '+912');

insert into public.calls (id, business_id, telephony_provider, provider_call_id)
values ('a3000000-0000-0000-0000-0000000000a3', 'a1000000-0000-0000-0000-0000000000a1', 'mock', 'rls-a'),
       ('b3000000-0000-0000-0000-0000000000b3', 'b1000000-0000-0000-0000-0000000000b1', 'mock', 'rls-b');

insert into public.knowledge_items (business_id, question, answer)
values ('a1000000-0000-0000-0000-0000000000a1', 'qa', 'aa'),
       ('b1000000-0000-0000-0000-0000000000b1', 'qb', 'ab');

insert into public.events (business_id, type)
values ('a1000000-0000-0000-0000-0000000000a1', 'call_received'),
       ('b1000000-0000-0000-0000-0000000000b1', 'call_received');

-- Appointment management. Business A has two practitioners: P1 (linked to the doctor login D)
-- and P2. Each has one client with one appointment.
insert into auth.users (id, aud, role, email)
values ('d0000000-0000-0000-0000-00000000000d', 'authenticated', 'authenticated', 'doctor-a@rls.test');
insert into public.business_members (business_id, user_id, role)
values ('a1000000-0000-0000-0000-0000000000a1', 'd0000000-0000-0000-0000-00000000000d', 'practitioner');

insert into public.scheduling_settings (business_id)
values ('a1000000-0000-0000-0000-0000000000a1'), ('b1000000-0000-0000-0000-0000000000b1');

insert into public.practitioners (id, business_id, name, user_id, consultation_minutes)
values ('a4000000-0000-0000-0000-0000000000a4', 'a1000000-0000-0000-0000-0000000000a1', 'P1',
        'd0000000-0000-0000-0000-00000000000d', 20),
       ('a4000000-0000-0000-0000-0000000000a5', 'a1000000-0000-0000-0000-0000000000a1', 'P2', null, 20),
       ('b4000000-0000-0000-0000-0000000000b4', 'b1000000-0000-0000-0000-0000000000b1', 'PB', null, 20);

insert into public.practitioner_hours (business_id, practitioner_id, weekday, start_time, end_time)
values ('a1000000-0000-0000-0000-0000000000a1', 'a4000000-0000-0000-0000-0000000000a4', 1, '10:00', '12:00'),
       ('b1000000-0000-0000-0000-0000000000b1', 'b4000000-0000-0000-0000-0000000000b4', 1, '10:00', '12:00');

insert into public.schedule_exceptions (business_id, kind, starts_at, ends_at)
values ('a1000000-0000-0000-0000-0000000000a1', 'closed', '2030-01-01', '2030-01-02'),
       ('b1000000-0000-0000-0000-0000000000b1', 'closed', '2030-01-01', '2030-01-02');

insert into public.clients (id, business_id, external_id, name, phone)
values ('a5000000-0000-0000-0000-0000000000a5', 'a1000000-0000-0000-0000-0000000000a1', 'c1', 'Client A1', '+919000000011'),
       ('a5000000-0000-0000-0000-0000000000a6', 'a1000000-0000-0000-0000-0000000000a1', 'c2', 'Client A2', '+919000000012'),
       ('b5000000-0000-0000-0000-0000000000b5', 'b1000000-0000-0000-0000-0000000000b1', 'c1', 'Client B', '+919000000013');

insert into public.appointments (id, business_id, practitioner_id, client_id, starts_at, ends_at)
values ('a6000000-0000-0000-0000-0000000000a6', 'a1000000-0000-0000-0000-0000000000a1',
        'a4000000-0000-0000-0000-0000000000a4', 'a5000000-0000-0000-0000-0000000000a5',
        '2030-01-07 05:00+00', '2030-01-07 05:20+00'),
       ('a6000000-0000-0000-0000-0000000000a7', 'a1000000-0000-0000-0000-0000000000a1',
        'a4000000-0000-0000-0000-0000000000a5', 'a5000000-0000-0000-0000-0000000000a6',
        '2030-01-07 05:00+00', '2030-01-07 05:20+00'),
       ('b6000000-0000-0000-0000-0000000000b6', 'b1000000-0000-0000-0000-0000000000b1',
        'b4000000-0000-0000-0000-0000000000b4', 'b5000000-0000-0000-0000-0000000000b5',
        '2030-01-07 05:00+00', '2030-01-07 05:20+00');

insert into public.audit_log (business_id, entity_type, entity_id, action, actor_type)
values ('a1000000-0000-0000-0000-0000000000a1', 'appointment', 'a6000000-0000-0000-0000-0000000000a6', 'booked', 'system'),
       ('b1000000-0000-0000-0000-0000000000b1', 'appointment', 'b6000000-0000-0000-0000-0000000000b6', 'booked', 'system');

insert into public.jobs (business_id, kind, appointment_id)
values ('a1000000-0000-0000-0000-0000000000a1', 'reminder', 'a6000000-0000-0000-0000-0000000000a6'),
       ('b1000000-0000-0000-0000-0000000000b1', 'reminder', 'b6000000-0000-0000-0000-0000000000b6');

insert into storage.objects (bucket_id, name)
values ('recordings', 'a1000000-0000-0000-0000-0000000000a1/a3000000-0000-0000-0000-0000000000a3.wav'),
       ('recordings', 'b1000000-0000-0000-0000-0000000000b1/b3000000-0000-0000-0000-0000000000b3.wav');

-- ---------------------------------------------------------------------------
-- 3. Act as owner A through the same role the admin app uses.
-- ---------------------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"a0000000-0000-0000-0000-00000000000a","role":"authenticated"}', true);

do $$
declare
  n int;
  b uuid := 'b1000000-0000-0000-0000-0000000000b1';
begin
  -- Positive control: A sees its own rows (otherwise the negative checks prove nothing)
  select count(*) into n from public.leads;
  if n <> 1 then raise exception 'owner A should see exactly 1 lead, saw %', n; end if;
  select count(*) into n from public.businesses;
  if n <> 1 then raise exception 'owner A should see exactly 1 business, saw %', n; end if;
  select count(*) into n from storage.objects where bucket_id = 'recordings';
  if n <> 1 then raise exception 'owner A should see exactly 1 recording, saw %', n; end if;

  -- Reads of B are empty
  select count(*) into n from public.businesses where id = b;
  if n <> 0 then raise exception 'cross-business read: businesses'; end if;
  select count(*) into n from public.leads where business_id = b;
  if n <> 0 then raise exception 'cross-business read: leads'; end if;
  select count(*) into n from public.calls where business_id = b;
  if n <> 0 then raise exception 'cross-business read: calls'; end if;
  select count(*) into n from public.knowledge_items where business_id = b;
  if n <> 0 then raise exception 'cross-business read: knowledge_items'; end if;
  select count(*) into n from public.events where business_id = b;
  if n <> 0 then raise exception 'cross-business read: events'; end if;
  select count(*) into n from public.business_members where business_id = b;
  if n <> 0 then raise exception 'cross-business read: business_members'; end if;
  select count(*) into n from storage.objects where name like b::text || '/%';
  if n <> 0 then raise exception 'cross-business read: recordings'; end if;

  -- Appointment management tables
  select count(*) into n from public.appointments;
  if n <> 2 then raise exception 'owner A should see 2 appointments, saw %', n; end if;
  select count(*) into n from public.practitioners where business_id = b;
  if n <> 0 then raise exception 'cross-business read: practitioners'; end if;
  select count(*) into n from public.practitioner_hours where business_id = b;
  if n <> 0 then raise exception 'cross-business read: practitioner_hours'; end if;
  select count(*) into n from public.schedule_exceptions where business_id = b;
  if n <> 0 then raise exception 'cross-business read: schedule_exceptions'; end if;
  select count(*) into n from public.clients where business_id = b;
  if n <> 0 then raise exception 'cross-business read: clients'; end if;
  select count(*) into n from public.appointments where business_id = b;
  if n <> 0 then raise exception 'cross-business read: appointments'; end if;
  select count(*) into n from public.scheduling_settings where business_id = b;
  if n <> 0 then raise exception 'cross-business read: scheduling_settings'; end if;
  select count(*) into n from public.audit_log where business_id = b;
  if n <> 0 then raise exception 'cross-business read: audit_log'; end if;
  select count(*) into n from public.jobs where business_id = b;
  if n <> 0 then raise exception 'cross-business read: jobs'; end if;

  update public.clients set automation_paused = true where business_id = b;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'cross-business update: clients'; end if;
  update public.appointments set automation_paused = true where business_id = b;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'cross-business update: appointments'; end if;
  delete from public.practitioners where business_id = b;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'cross-business delete: practitioners'; end if;
  begin
    insert into public.practitioners (business_id, name, consultation_minutes)
    values (b, 'injected', 20);
    raise exception 'cross-business insert: practitioners was allowed';
  exception when insufficient_privilege then null;
  end;

  -- Staff may pause automation on their own rows...
  update public.appointments set automation_paused = true
  where id = 'a6000000-0000-0000-0000-0000000000a6';
  get diagnostics n = row_count;
  if n <> 1 then raise exception 'owner A could not pause own appointment'; end if;
  -- ...but bookings change only through the API's booking engine
  begin
    update public.appointments set status = 'cancelled'
    where id = 'a6000000-0000-0000-0000-0000000000a6';
    raise exception 'direct status change on appointments was allowed';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.appointments (business_id, practitioner_id, client_id, starts_at, ends_at)
    values ('a1000000-0000-0000-0000-0000000000a1', 'a4000000-0000-0000-0000-0000000000a4',
            'a5000000-0000-0000-0000-0000000000a5', '2030-01-08 05:00+00', '2030-01-08 05:20+00');
    raise exception 'direct insert into appointments was allowed';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.clients (business_id, external_id, name, phone)
    values ('a1000000-0000-0000-0000-0000000000a1', 'x', 'x', '+919000000099');
    raise exception 'direct insert into clients was allowed';
  exception when insufficient_privilege then null;
  end;

  -- Updates/deletes of B touch nothing
  update public.leads set name = 'pwned' where business_id = b;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'cross-business update: leads'; end if;
  delete from public.knowledge_items where business_id = b;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'cross-business delete: knowledge_items'; end if;

  -- Inserts into B are rejected
  begin
    insert into public.leads (business_id, name) values (b, 'injected');
    raise exception 'cross-business insert: leads was allowed';
  exception when insufficient_privilege then null;  -- RLS violation (42501) is expected
  end;
  begin
    insert into public.events (business_id, type) values (b, 'payment_recorded');
    raise exception 'cross-business insert: events was allowed';
  exception when insufficient_privilege then null;
  end;

  -- Moving A's own lead into B is rejected (WITH CHECK)
  begin
    update public.leads set business_id = b where id = 'a2000000-0000-0000-0000-0000000000a2';
    raise exception 'cross-business move: leads was allowed';
  exception when insufficient_privilege then null;
  end;
end $$;

-- ---------------------------------------------------------------------------
-- 3b. A practitioner (doctor login D in business A) sees only their own appointments and the
--     clients booked with them, and no operational data (audit log, jobs, events, calls, leads).
-- ---------------------------------------------------------------------------
reset role;
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"d0000000-0000-0000-0000-00000000000d","role":"authenticated"}', true);

do $$
declare
  n int;
begin
  select count(*) into n from public.appointments;
  if n <> 1 then raise exception 'doctor should see 1 appointment, saw %', n; end if;
  select count(*) into n from public.appointments
  where id = 'a6000000-0000-0000-0000-0000000000a6';
  if n <> 1 then raise exception 'doctor cannot see own appointment'; end if;
  select count(*) into n from public.clients;
  if n <> 1 then raise exception 'doctor should see 1 client, saw %', n; end if;
  select count(*) into n from public.practitioners;
  if n <> 2 then raise exception 'doctor should see the 2 practitioners of A, saw %', n; end if;
  select count(*) into n from public.audit_log;
  if n <> 0 then raise exception 'doctor can read audit_log'; end if;
  select count(*) into n from public.jobs;
  if n <> 0 then raise exception 'doctor can read jobs'; end if;
  select count(*) into n from public.events;
  if n <> 0 then raise exception 'doctor can read events'; end if;
  select count(*) into n from public.leads;
  if n <> 0 then raise exception 'doctor can read leads'; end if;
  select count(*) into n from public.calls;
  if n <> 0 then raise exception 'doctor can read calls'; end if;

  update public.appointments set automation_paused = true;
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'doctor could update appointments'; end if;
  update public.practitioners set name = 'renamed';
  get diagnostics n = row_count;
  if n <> 0 then raise exception 'doctor could edit practitioners'; end if;
end $$;

-- ---------------------------------------------------------------------------
-- 4. anon (no login) sees nothing at all.
-- ---------------------------------------------------------------------------
reset role;
set local role anon;
do $$
begin
  perform 1 from public.leads limit 1;
  raise exception 'anon can read public.leads';
exception when insufficient_privilege then null;
end $$;

reset role;
