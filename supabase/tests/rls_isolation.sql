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
