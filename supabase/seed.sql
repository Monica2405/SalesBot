-- Local/dev seed only (`supabase db reset`). Never run against production.
-- Demo login for the admin app: owner@demo.local / demo-password-local-only

-- Demo owner user (Supabase Auth). Fixed ids so tests and docs can reference them.
insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, recovery_token, email_change, email_change_token_new
) values (
  '00000000-0000-0000-0000-000000000000',
  '11111111-1111-1111-1111-111111111111',
  'authenticated', 'authenticated', 'owner@demo.local',
  extensions.crypt('demo-password-local-only', extensions.gen_salt('bf')),
  now(), '{"provider":"email","providers":["email"]}', '{}', now(), now(),
  '', '', '', ''
);

insert into auth.identities (
  id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at
) values (
  gen_random_uuid(),
  '11111111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  '{"sub":"11111111-1111-1111-1111-111111111111","email":"owner@demo.local"}',
  'email', now(), now(), now()
);

-- Demo business on the dentist pack
insert into public.businesses (id, name, slug, pack_id, phone_number, settings, usage_cap_minutes)
values (
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'Smile Dental Clinic (demo)', 'smile-dental-demo', 'dentist', '+910000000000',
  '{"business_hours": "Mon-Sat 10am-8pm", "business_address": "Demo Road, Pune",
    "handoff_number": null}',
  500
);

insert into public.business_members (business_id, user_id, role)
values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'owner');

insert into public.packs_applied (business_id, pack_id, pack_version, applied_by)
values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'dentist', 1, '11111111-1111-1111-1111-111111111111');

insert into public.script_versions (id, business_id, version, pack_id, is_active, notes)
values ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        1, 'dentist', true, 'Initial script from dentist pack v1');

insert into public.knowledge_items (business_id, question, answer, keywords) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Do you accept cards?',
   'Yes, we accept cards and UPI.', array['card', 'upi', 'payment']),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Is parking available?',
   'Yes, there is free parking in front of the clinic.', array['parking']);

-- One demo call that became a lead and a booking, with funnel events
insert into public.leads (id, business_id, name, phone, source, stage, service_id, estimated_value_inr)
values ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'Demo Patient', '+919999999999', 'google_business', 'booked', 'cleaning', 1200);

insert into public.calls (
  id, business_id, lead_id, script_version_id, source, telephony_provider, provider_call_id,
  from_number, to_number, language, status, outcome, consent_recording,
  started_at, ended_at, duration_seconds, agent_minutes, telephony_pulses, cost_inr_estimate
) values (
  'dddddddd-dddd-dddd-dddd-dddddddddddd', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'cccccccc-cccc-cccc-cccc-cccccccccccc', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  'google_business', 'mock', 'mock-call-1', '+919999999999', '+910000000000', 'hi',
  'completed', 'booked', true,
  now() - interval '1 day', now() - interval '1 day' + interval '3 minutes', 180,
  3, 6, 11.70
);

-- Scheduling: one practitioner (Mon-Sat 10:00-13:00 and 17:00-20:00 IST), default settings,
-- one registered client (fake number) with a booking.
insert into public.scheduling_settings (business_id) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');

insert into public.practitioners (id, business_id, name, display_names, consultation_minutes, first_visit_minutes)
values ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Dr. Demo',
        '{"hi": "डॉ. डेमो", "mr": "डॉ. डेमो"}', 20, 30);

insert into public.practitioner_hours (business_id, practitioner_id, kind, weekday, start_time, end_time)
select 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'work', d, t.s, t.e
from generate_series(1, 6) d, (values (time '10:00', time '13:00'), (time '17:00', time '20:00')) t(s, e);

insert into public.clients (id, business_id, external_id, name, phone, preferred_language,
                            whatsapp_opt_in, call_opt_in, consent_at, consent_source, source)
values ('ffffffff-ffff-ffff-ffff-ffffffffffff', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'demo-1',
        'Demo Patient', '+919999999999', 'hi', true, false, now() - interval '2 days',
        'seed', 'simulation');

insert into public.appointments (business_id, lead_id, call_id, practitioner_id, client_id,
                                 visit_type, starts_at, ends_at, status, booked_at, booked_via,
                                 language, value_inr)
values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'cccccccc-cccc-cccc-cccc-cccccccccccc',
        'dddddddd-dddd-dddd-dddd-dddddddddddd', 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
        'ffffffff-ffff-ffff-ffff-ffffffffffff', 'first_visit',
        date_trunc('day', now()) + interval '2 days 5 hours 30 minutes',   -- 11:00 IST
        date_trunc('day', now()) + interval '2 days 6 hours',
        'booked', now() - interval '1 day', 'whatsapp', 'hi', 1200);

insert into public.events (business_id, type, call_id, lead_id, source, occurred_at) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'call_received', 'dddddddd-dddd-dddd-dddd-dddddddddddd', null, 'google_business', now() - interval '1 day'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'lead_captured', 'dddddddd-dddd-dddd-dddd-dddddddddddd', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'google_business', now() - interval '1 day'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'booking_created', 'dddddddd-dddd-dddd-dddd-dddddddddddd', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'google_business', now() - interval '1 day');

insert into public.usage_records (business_id, call_id, period_month, call_seconds, agent_minutes, telephony_pulses)
values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'dddddddd-dddd-dddd-dddd-dddddddddddd',
        date_trunc('month', now())::date, 180, 3, 6);
