-- Appointment management (Anvia Phase 1), written generically:
--   clients        = the people who book (patients in the clinic pack)
--   practitioners  = the people whose calendars are booked (doctors in the clinic pack)
-- All times are timestamptz (stored UTC). Weekly hours are local wall-clock times in the
-- business timezone (businesses.timezone, Asia/Kolkata for Indian clinics).
-- RLS for every new table is in the next migration.

-- btree_gist lets the exclusion constraint mix "=" on uuid with "&&" on time ranges.
create extension if not exists btree_gist with schema extensions;

-- ---------------------------------------------------------------------------
-- Roles and attribution
-- ---------------------------------------------------------------------------
alter table public.business_members drop constraint business_members_role_check;
alter table public.business_members add constraint business_members_role_check
  check (role in ('owner', 'admin', 'staff', 'receptionist', 'practitioner'));

-- registration_form: arrived through the intake adapter. simulation: the dev-only form simulator
-- (excluded from metrics, like test_call). Keep in sync with salesbot_core.events.LeadSource.
alter domain public.lead_source drop constraint lead_source_check;
alter domain public.lead_source add constraint lead_source_check
  check (value in ('unknown', 'google_business', 'website', 'whatsapp', 'referral',
                   'walk_in', 'ads', 'test_call', 'registration_form', 'simulation'));

alter table public.businesses
  add column default_language text not null default 'en'
    check (default_language in ('en', 'hi', 'mr'));

-- ---------------------------------------------------------------------------
-- Practitioners and their calendars
-- ---------------------------------------------------------------------------
create table public.practitioners (
  id                    uuid primary key default gen_random_uuid(),
  business_id           uuid not null references public.businesses (id) on delete cascade,
  name                  text not null,
  display_names         jsonb not null default '{}'::jsonb   -- {"hi": "...", "mr": "..."}
                          check (jsonb_typeof(display_names) = 'object'),
  user_id               uuid references auth.users (id) on delete set null, -- their admin login
  consultation_minutes  integer not null check (consultation_minutes between 5 and 480),
  -- Optional longer first visit; falls back to consultation_minutes.
  first_visit_minutes   integer check (first_visit_minutes is null
                                       or first_visit_minutes between 5 and 480),
  is_active             boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (id, business_id),           -- target of composite FKs (keeps rows in one business)
  unique (business_id, user_id)
);

-- Weekly pattern. Several 'work' rows per weekday are allowed (split shifts); 'break' rows are
-- subtracted from work rows.
create table public.practitioner_hours (
  id               uuid primary key default gen_random_uuid(),
  business_id      uuid not null references public.businesses (id) on delete cascade,
  practitioner_id  uuid not null,
  kind             text not null default 'work' check (kind in ('work', 'break')),
  weekday          smallint not null check (weekday between 1 and 7), -- ISO: 1 = Monday
  start_time       time not null,
  end_time         time not null,
  check (end_time > start_time),
  foreign key (practitioner_id, business_id)
    references public.practitioners (id, business_id) on delete cascade
);
create index practitioner_hours_practitioner_idx on public.practitioner_hours (practitioner_id);

-- Dated exceptions. 'closed' = holiday or leave (practitioner_id null = whole business closed).
-- 'open' = extra working time outside the weekly pattern (always for one practitioner).
create table public.schedule_exceptions (
  id               uuid primary key default gen_random_uuid(),
  business_id      uuid not null references public.businesses (id) on delete cascade,
  practitioner_id  uuid,
  kind             text not null check (kind in ('closed', 'open')),
  starts_at        timestamptz not null,
  ends_at          timestamptz not null,
  reason           text,
  created_at       timestamptz not null default now(),
  check (ends_at > starts_at),
  check (kind = 'closed' or practitioner_id is not null),
  foreign key (practitioner_id, business_id)
    references public.practitioners (id, business_id) on delete cascade
);
create index schedule_exceptions_business_time_idx
  on public.schedule_exceptions (business_id, starts_at);

-- ---------------------------------------------------------------------------
-- Clients (patients). Created by the intake adapter, never by a call or chat.
-- ---------------------------------------------------------------------------
create table public.clients (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid not null references public.businesses (id) on delete cascade,
  external_id        text not null,   -- id in the registration system (external_patient_id)
  name               text not null,
  phone              text not null check (phone ~ '^\+[1-9][0-9]{7,14}$'),  -- E.164
  preferred_language text not null default 'en' check (preferred_language in ('en', 'hi', 'mr')),
  date_of_birth      date,
  age                smallint check (age is null or age between 0 and 130),
  -- A caregiver is a separate person: never merged into the client's own name or phone.
  caregiver_name     text,
  caregiver_phone    text check (caregiver_phone is null
                                 or caregiver_phone ~ '^\+[1-9][0-9]{7,14}$'),
  whatsapp_opt_in    boolean not null default false,
  call_opt_in        boolean not null default false,
  consent_at         timestamptz,
  consent_source     text,
  automation_paused  boolean not null default false,
  source             public.lead_source not null default 'registration_form',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check ((not whatsapp_opt_in and not call_opt_in) or consent_at is not null),
  unique (business_id, external_id),  -- idempotency key of the intake contract
  unique (id, business_id)
);
-- Shared family numbers are normal, so phone is indexed but not unique.
create index clients_business_phone_idx on public.clients (business_id, phone);

-- ---------------------------------------------------------------------------
-- Per-business scheduling settings. Defaults approved by the owner (docs/DECISIONS.md).
-- The jsonb policies are validated by salesbot_core.scheduling.settings.
-- ---------------------------------------------------------------------------
create table public.scheduling_settings (
  business_id              uuid primary key references public.businesses (id) on delete cascade,
  hold_minutes             integer not null default 5 check (hold_minutes between 1 and 60),
  min_lead_minutes         integer not null default 60 check (min_lead_minutes between 0 and 10080),
  lookahead_days           integer not null default 14 check (lookahead_days between 1 and 180),
  -- 9 + one "show other options" row fits a 10-row WhatsApp list (limit re-checked in Stage C).
  days_per_list            integer not null default 9 check (days_per_list between 1 and 9),
  -- Grid for offered start times. Null = the visit's own duration.
  slot_step_minutes        integer check (slot_step_minutes is null
                                          or slot_step_minutes between 5 and 240),
  practitioner_selection   text not null default 'any_available'
                             check (practitioner_selection in ('any_available',
                                                               'default_practitioner')),
  default_practitioner_id  uuid,
  reschedule_approval      text not null default 'auto'
                             check (reschedule_approval in ('auto', 'staff')),
  confirmation_policy      jsonb not null default '{}'::jsonb
                             check (jsonb_typeof(confirmation_policy) = 'object'),
  reminder_policy          jsonb not null default '{}'::jsonb
                             check (jsonb_typeof(reminder_policy) = 'object'),
  call_policy              jsonb not null default '{}'::jsonb
                             check (jsonb_typeof(call_policy) = 'object'),
  updated_at               timestamptz not null default now(),
  check (practitioner_selection = 'any_available' or default_practitioner_id is not null),
  foreign key (default_practitioner_id, business_id)
    references public.practitioners (id, business_id) on delete set null (default_practitioner_id)
);

-- ---------------------------------------------------------------------------
-- Appointments: extend the scaffold table.
-- A slot hold is an appointment row with status 'held' and hold_expires_at, so ONE exclusion
-- constraint covers holds and bookings. Expired holds are deleted before a new hold is placed
-- on the same practitioner and time, and swept by the worker.
-- ---------------------------------------------------------------------------
alter table public.appointments drop constraint appointments_status_check;
update public.appointments set status = 'booked' where status = 'scheduled';

alter table public.appointments
  alter column status set default 'booked',
  alter column service_id drop not null,
  add column practitioner_id      uuid not null,
  add column client_id            uuid not null,
  add column visit_type           text not null default 'consultation'
                                    check (visit_type in ('first_visit', 'consultation')),
  add column hold_expires_at      timestamptz,
  add column rescheduled_from_id  uuid references public.appointments (id),
  add column rescheduled_to_id    uuid references public.appointments (id),
  add column booked_at            timestamptz,
  add column confirmed_at         timestamptz,
  add column cancelled_at         timestamptz,
  add column booked_via           text check (booked_via in ('whatsapp', 'voice', 'staff',
                                                             'api', 'system')),
  add column language             text check (language in ('en', 'hi', 'mr')),
  add column automation_paused    boolean not null default false,
  add column updated_at           timestamptz not null default now(),
  add constraint appointments_status_check
    check (status in ('held', 'pending_approval', 'booked', 'confirmed', 'unconfirmed',
                      'rescheduled', 'cancelled', 'showed', 'no_show', 'completed')),
  add constraint appointments_hold_has_expiry
    check (status <> 'held' or hold_expires_at is not null),
  -- NO ACTION (checked at end of statement), not RESTRICT, so deleting a whole business can
  -- cascade; deleting a practitioner who still has appointments fails. Deactivate instead.
  add constraint appointments_practitioner_fk foreign key (practitioner_id, business_id)
    references public.practitioners (id, business_id),
  add constraint appointments_client_fk foreign key (client_id, business_id)
    references public.clients (id, business_id) on delete cascade,
  -- No double-booking, enforced by the database. Statuses that occupy the calendar:
  add constraint appointments_no_overlap exclude using gist (
    practitioner_id with =,
    tstzrange(starts_at, ends_at, '[)') with &&
  ) where (status in ('held', 'pending_approval', 'booked', 'confirmed', 'unconfirmed'));

create index appointments_practitioner_start_idx
  on public.appointments (business_id, practitioner_id, starts_at);
create index appointments_client_idx on public.appointments (client_id, starts_at);

-- ---------------------------------------------------------------------------
-- Funnel events: new types, plus client, channel and language for slicing.
-- Keep the type list in sync with salesbot_core.events.EventType.
-- ---------------------------------------------------------------------------
alter table public.events drop constraint events_type_check;
alter table public.events
  add constraint events_type_check check (type in (
    'call_received', 'call_answered', 'consent_given', 'consent_declined',
    'lead_captured', 'question_unanswered', 'emergency_detected',
    'handoff_requested', 'callback_requested', 'booking_created',
    'booking_cancelled', 'appointment_showed', 'appointment_no_show',
    'payment_recorded', 'call_ended',
    'client_registered', 'welcome_sent', 'booking_started', 'confirmation_sent',
    'appointment_confirmed', 'reschedule_requested', 'appointment_rescheduled',
    'reminder_sent', 'no_response', 'handoff_task_created')),
  add column client_id uuid references public.clients (id) on delete set null,
  add column channel   text check (channel in ('whatsapp', 'voice', 'staff', 'api', 'system')),
  add column language  text check (language in ('en', 'hi', 'mr', 'other'));
create index events_client_idx on public.events (client_id, occurred_at);

-- ---------------------------------------------------------------------------
-- Audit log (append-only): what changed, who or what changed it, what the client was told.
-- ---------------------------------------------------------------------------
create table public.audit_log (
  id              bigint generated always as identity primary key,
  business_id     uuid not null references public.businesses (id) on delete cascade,
  entity_type     text not null,           -- appointment | client | scheduling_settings | ...
  entity_id       uuid not null,
  action          text not null,           -- held | booked | rescheduled | cancelled | ...
  actor_type      text not null check (actor_type in ('client', 'staff', 'system', 'integration')),
  actor_user_id   uuid references auth.users (id) on delete set null,
  channel         text check (channel in ('whatsapp', 'voice', 'staff', 'api', 'system')),
  changes         jsonb not null default '{}'::jsonb,  -- {"field": [old, new]}
  client_message  text,                    -- exactly what the client was told, if anything
  created_at      timestamptz not null default now()
);
create index audit_log_entity_idx on public.audit_log (entity_type, entity_id, created_at);
create index audit_log_business_time_idx on public.audit_log (business_id, created_at desc);

create function public.append_only() returns trigger
language plpgsql as $$
begin
  raise exception '% is append-only (% not allowed)', tg_table_name, tg_op;
end;
$$;

-- Same pattern as events: FK actions (pg_trigger_depth() > 0) may still cascade.
create trigger audit_log_no_update
  before update on public.audit_log
  for each row when (pg_trigger_depth() = 0)
  execute function public.append_only();
create trigger audit_log_no_delete
  before delete on public.audit_log
  for each row when (pg_trigger_depth() = 0)
  execute function public.append_only();

-- ---------------------------------------------------------------------------
-- Jobs: a Postgres-backed queue for the worker in apps/api (claimed with FOR UPDATE SKIP LOCKED).
-- Never put personal data in last_error.
-- ---------------------------------------------------------------------------
create table public.jobs (
  id              bigint generated always as identity primary key,
  business_id     uuid not null references public.businesses (id) on delete cascade,
  kind            text not null,           -- welcome | confirmation_request | reminder | ...
  payload         jsonb not null default '{}'::jsonb,
  run_at          timestamptz not null default now(),
  status          text not null default 'queued'
                    check (status in ('queued', 'running', 'done', 'failed', 'cancelled')),
  attempts        integer not null default 0,
  max_attempts    integer not null default 5 check (max_attempts >= 1),
  last_error      text,
  locked_at       timestamptz,
  locked_by       text,
  dedupe_key      text,
  appointment_id  uuid references public.appointments (id) on delete cascade,
  client_id       uuid references public.clients (id) on delete cascade,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (business_id, dedupe_key)
);
create index jobs_due_idx on public.jobs (run_at) where status = 'queued';
create index jobs_appointment_idx on public.jobs (appointment_id) where status = 'queued';

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------
create trigger practitioners_updated_at before update on public.practitioners
  for each row execute function public.set_updated_at();
create trigger clients_updated_at before update on public.clients
  for each row execute function public.set_updated_at();
create trigger scheduling_settings_updated_at before update on public.scheduling_settings
  for each row execute function public.set_updated_at();
create trigger appointments_updated_at before update on public.appointments
  for each row execute function public.set_updated_at();
create trigger jobs_updated_at before update on public.jobs
  for each row execute function public.set_updated_at();
