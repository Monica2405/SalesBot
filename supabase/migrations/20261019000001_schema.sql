-- Core schema. Supabase migrations are the ONLY source of schema (no Alembic).
-- Every table holding business data has business_id; RLS is enabled in the next migration.

-- ---------------------------------------------------------------------------
-- Tenancy
-- ---------------------------------------------------------------------------
create table public.businesses (
  id                 uuid primary key default gen_random_uuid(),
  name               text not null,
  slug               text not null unique check (slug ~ '^[a-z0-9-]+$'),
  pack_id            text not null,                     -- e.g. 'dentist', 'salon' (packs/*.yaml)
  timezone           text not null default 'Asia/Kolkata',
  phone_number       text,                              -- inbound number routed to this business
  languages          text[] not null default array['en','hi','mr'],
  settings           jsonb not null default '{}'::jsonb, -- hours, address, handoff number, ...
  usage_cap_minutes  integer check (usage_cap_minutes is null or usage_cap_minutes >= 0),
  created_at         timestamptz not null default now()
);

create table public.business_members (
  business_id  uuid not null references public.businesses (id) on delete cascade,
  user_id      uuid not null references auth.users (id) on delete cascade,
  role         text not null default 'owner' check (role in ('owner', 'admin', 'staff')),
  created_at   timestamptz not null default now(),
  primary key (business_id, user_id)
);
create index business_members_user_idx on public.business_members (user_id);

create table public.packs_applied (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses (id) on delete cascade,
  pack_id       text not null,
  pack_version  integer not null,
  overrides     jsonb not null default '{}'::jsonb,     -- business-specific tweaks to the pack
  applied_by    uuid references auth.users (id),
  applied_at    timestamptz not null default now()
);
create index packs_applied_business_idx on public.packs_applied (business_id, applied_at desc);

-- What the agent says. Every call records which version it ran, so conversion can be
-- compared across script versions (A/B by version).
create table public.script_versions (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses (id) on delete cascade,
  version      integer not null,
  pack_id      text not null,
  content      jsonb not null default '{}'::jsonb,
  notes        text,
  is_active    boolean not null default false,
  created_by   uuid references auth.users (id),
  created_at   timestamptz not null default now(),
  unique (business_id, version)
);
create unique index script_versions_one_active
  on public.script_versions (business_id) where is_active;

-- ---------------------------------------------------------------------------
-- Leads and calls
-- ---------------------------------------------------------------------------
-- Attribution sources. Keep in sync with salesbot_core.events.LeadSource.
create domain public.lead_source as text
  check (value in ('unknown', 'google_business', 'website', 'whatsapp', 'referral',
                   'walk_in', 'ads', 'test_call'));

create table public.leads (
  id                   uuid primary key default gen_random_uuid(),
  business_id          uuid not null references public.businesses (id) on delete cascade,
  name                 text,
  phone                text,
  source               public.lead_source not null default 'unknown',
  stage                text not null default 'new',     -- one of the pack's lead_stages
  service_id           text,                            -- pack service id
  intake               jsonb not null default '{}'::jsonb, -- answers to pack intake questions
  estimated_value_inr  integer check (estimated_value_inr is null or estimated_value_inr >= 0),
  score                integer check (score is null or score between 0 and 100),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index leads_business_stage_idx on public.leads (business_id, stage);
create index leads_business_phone_idx on public.leads (business_id, phone);

create table public.calls (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid not null references public.businesses (id) on delete cascade,
  lead_id            uuid references public.leads (id) on delete set null,
  script_version_id  uuid references public.script_versions (id),
  source             public.lead_source not null default 'unknown',
  telephony_provider text not null,                     -- mock | plivo | exotel
  provider_call_id   text,
  direction          text not null default 'inbound' check (direction in ('inbound', 'outbound')),
  from_number        text,
  to_number          text,
  language           text,
  status             text not null default 'in_progress'
                       check (status in ('in_progress', 'completed', 'failed', 'abandoned')),
  outcome            text,                              -- booked | lead_only | faq | handoff | callback | spam
  consent_recording  boolean not null default false,
  recording_path     text,                              -- storage path in the recordings bucket
  transcript         jsonb,
  started_at         timestamptz not null default now(),
  ended_at           timestamptz,
  duration_seconds   integer,
  -- Cost tracking (per call)
  stt_seconds        numeric(10, 2) not null default 0,
  llm_tokens_in      integer not null default 0,
  llm_tokens_out     integer not null default 0,
  tts_characters     integer not null default 0,
  created_at         timestamptz not null default now(),
  unique (telephony_provider, provider_call_id)
);
create index calls_business_started_idx on public.calls (business_id, started_at desc);

create table public.lead_events (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses (id) on delete cascade,
  lead_id      uuid not null references public.leads (id) on delete cascade,
  from_stage   text,
  to_stage     text not null,
  note         text,
  actor_id     uuid references auth.users (id),         -- null = system/agent
  created_at   timestamptz not null default now()
);
create index lead_events_lead_idx on public.lead_events (lead_id, created_at);

create table public.appointments (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid not null references public.businesses (id) on delete cascade,
  lead_id            uuid references public.leads (id) on delete set null,
  call_id            uuid references public.calls (id) on delete set null,
  service_id         text not null,
  starts_at          timestamptz not null,
  ends_at            timestamptz not null,
  status             text not null default 'scheduled'
                       check (status in ('scheduled', 'cancelled', 'showed', 'no_show', 'completed')),
  calendar_event_id  text,                              -- Google Calendar event id
  value_inr          integer check (value_inr is null or value_inr >= 0),
  created_at         timestamptz not null default now(),
  check (ends_at > starts_at)
);
create index appointments_business_start_idx on public.appointments (business_id, starts_at);

-- ---------------------------------------------------------------------------
-- Funnel events (append-only). Metrics are computed from here.
-- Keep the type list in sync with salesbot_core.events.EventType.
-- ---------------------------------------------------------------------------
create table public.events (
  id              bigint generated always as identity primary key,
  business_id     uuid not null references public.businesses (id) on delete cascade,
  type            text not null check (type in (
                    'call_received', 'call_answered', 'consent_given', 'consent_declined',
                    'lead_captured', 'question_unanswered', 'emergency_detected',
                    'handoff_requested', 'callback_requested', 'booking_created',
                    'booking_cancelled', 'appointment_showed', 'appointment_no_show',
                    'payment_recorded', 'call_ended')),
  occurred_at     timestamptz not null default now(),
  call_id         uuid references public.calls (id) on delete set null,
  lead_id         uuid references public.leads (id) on delete set null,
  appointment_id  uuid references public.appointments (id) on delete set null,
  source          public.lead_source not null default 'unknown',
  value_inr       integer,
  properties      jsonb not null default '{}'::jsonb
);
create index events_business_type_time_idx on public.events (business_id, type, occurred_at);

create function public.events_append_only() returns trigger
language plpgsql as $$
begin
  raise exception 'events is append-only (% not allowed)', tg_op;
end;
$$;

-- Blocks direct UPDATE/DELETE for everyone, including service_role. Changes made by foreign-key
-- actions (deleting a business, or SET NULL when a call is deleted) run inside the FK trigger,
-- so pg_trigger_depth() > 0 and they are allowed.
create trigger events_no_update
  before update on public.events
  for each row when (pg_trigger_depth() = 0)
  execute function public.events_append_only();
create trigger events_no_delete
  before delete on public.events
  for each row when (pg_trigger_depth() = 0)
  execute function public.events_append_only();

-- ---------------------------------------------------------------------------
-- Knowledge
-- ---------------------------------------------------------------------------
create table public.knowledge_items (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid not null references public.businesses (id) on delete cascade,
  question     text not null,
  answer       text not null,
  language     text not null default 'en',
  keywords     text[] not null default '{}',
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index knowledge_items_business_idx on public.knowledge_items (business_id) where is_active;

-- Questions the agent could not answer. Owners turn these into knowledge_items.
create table public.unanswered_questions (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid not null references public.businesses (id) on delete cascade,
  call_id            uuid references public.calls (id) on delete set null,
  question           text not null,
  language           text,
  status             text not null default 'open' check (status in ('open', 'answered', 'dismissed')),
  knowledge_item_id  uuid references public.knowledge_items (id) on delete set null,
  created_at         timestamptz not null default now()
);
create index unanswered_questions_open_idx
  on public.unanswered_questions (business_id) where status = 'open';

-- ---------------------------------------------------------------------------
-- Follow-ups (schema only; feature disabled until built)
-- ---------------------------------------------------------------------------
create table public.follow_up_sequences (
  id             uuid primary key default gen_random_uuid(),
  business_id    uuid not null references public.businesses (id) on delete cascade,
  name           text not null,
  trigger_event  text not null,                         -- an events.type, e.g. 'appointment_no_show'
  steps          jsonb not null default '[]'::jsonb,    -- [{delay_hours, channel, template}]
  enabled        boolean not null default false check (enabled = false), -- lift when built
  created_at     timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Usage (billing and caps). One row per call, aggregated by month for caps.
-- ---------------------------------------------------------------------------
create table public.usage_records (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid not null references public.businesses (id) on delete cascade,
  call_id            uuid references public.calls (id) on delete set null,
  period_month       date not null,                     -- first day of the month
  call_seconds       integer not null default 0,
  stt_seconds        numeric(10, 2) not null default 0,
  llm_tokens_in      integer not null default 0,
  llm_tokens_out     integer not null default 0,
  tts_characters     integer not null default 0,
  cost_inr_estimate  numeric(10, 2),
  created_at         timestamptz not null default now()
);
create index usage_records_business_month_idx on public.usage_records (business_id, period_month);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------
create function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger leads_updated_at before update on public.leads
  for each row execute function public.set_updated_at();
create trigger knowledge_items_updated_at before update on public.knowledge_items
  for each row execute function public.set_updated_at();
