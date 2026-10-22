-- Per-clinic languages and emergency contacts (Stage B, Step 2).
-- allowed_languages: the languages a clinic offers patients. Marathi is opt-in per clinic.
-- emergency_numbers: digits only, given in every emergency reply together with contact_phone.
-- contact_phone: the clinic's number for patients (not phone_number, the inbound line).
-- Keep defaults in sync with salesbot_core.scheduling.SchedulingSettings (test_sql_sync.py).

alter table public.businesses
  add column allowed_languages text[] not null default '{en,hi}',
  add column emergency_numbers text[] not null default '{112,108}',
  add column contact_phone text;

alter table public.businesses
  add constraint businesses_allowed_languages_check
    check (cardinality(allowed_languages) >= 1
           and allowed_languages <@ array['en', 'hi', 'mr']::text[]
           and default_language = any (allowed_languages)),
  add constraint businesses_emergency_numbers_check
    check (cardinality(emergency_numbers) >= 1
           and array_to_string(emergency_numbers, ',') ~ '^[0-9]{3,15}(,[0-9]{3,15})*$'),
  add constraint businesses_contact_phone_check
    check (contact_phone is null or contact_phone ~ '^\+?[0-9]{6,15}$');
