-- Sarvam Voice Agents (Stage B, Step 3). Voice runs on Sarvam's managed platform; our API serves
-- its tools and hooks and stores what happened. Not applied to the hosted project yet.
--
-- - calls: Sarvam ids, cost fields (agent minutes, telephony pulses), summary, language per
--   turn, recording reference (we link to Sarvam's recording, we do not copy audio), outbound
--   purpose and dry runs. The Pipecat-era cost columns (STT seconds, LLM tokens, TTS
--   characters) are dropped: Sarvam bills per minute with the models included.
-- - staff_tasks: what the voice agent (and later WhatsApp) hands to the clinic team.
-- - voice_tool_calls: every tool call, also the idempotency record per
--   (interaction_id, tool, request hash).
-- - spend_ledger: credit spend per call and test run, for the session and daily spend caps.
-- Keep CHECK lists in sync with salesbot_core (packages/core/tests/test_sql_sync.py).

-- ---------------------------------------------------------------------------
-- Calls
-- ---------------------------------------------------------------------------
alter table public.calls drop constraint calls_status_check;

alter table public.calls
  drop column stt_seconds,
  drop column llm_tokens_in,
  drop column llm_tokens_out,
  drop column tts_characters,
  add column client_id          uuid,
  add column appointment_id     uuid references public.appointments (id) on delete set null,
  add column purpose            text not null default 'inbound'
                                  check (purpose in ('inbound', 'confirmation_call',
                                                     'reminder_call')),
  add column attempt_id         text unique,          -- Sarvam outbound attempt_id
  add column dry_run            boolean not null default false,
  add column summary            text,
  add column turn_languages     jsonb,                -- ["Hindi", "English", ...] per turn
  add column agent_variables    jsonb,                -- final agent variables from Sarvam
  add column recording_ref      text,                 -- how to fetch Sarvam's recording
  add column failure_reason     text,
  add column ended_by           text,
  add column agent_minutes      integer not null default 0 check (agent_minutes >= 0),
  add column telephony_pulses   integer not null default 0 check (telephony_pulses >= 0),
  add column forwarding_pulses  integer not null default 0 check (forwarding_pulses >= 0),
  add column cost_inr_estimate  numeric(10, 2),
  add column rates_verified_on  date,                 -- the rate card the estimate used
  add constraint calls_status_check
    check (status in ('queued', 'dry_run', 'in_progress', 'completed', 'no_answer', 'busy',
                      'failed', 'abandoned')),
  add constraint calls_client_fk foreign key (client_id, business_id)
    references public.clients (id, business_id) on delete set null (client_id);

comment on column public.calls.telephony_provider is
  'Voice platform that carried the call: sarvam (mock in tests).';
comment on column public.calls.provider_call_id is
  'Sarvam interaction_id (<YYYYMMDD>/<id>) once the call connects.';

create index calls_client_idx on public.calls (client_id, started_at desc);
create index calls_appointment_purpose_idx on public.calls (appointment_id, purpose);

alter table public.usage_records
  drop column stt_seconds,
  drop column llm_tokens_in,
  drop column llm_tokens_out,
  drop column tts_characters,
  add column agent_minutes    integer not null default 0 check (agent_minutes >= 0),
  add column telephony_pulses integer not null default 0 check (telephony_pulses >= 0);

-- ---------------------------------------------------------------------------
-- Staff tasks: escalations for the clinic team (callback, emergency, question, ...)
-- ---------------------------------------------------------------------------
create table public.staff_tasks (
  id              uuid primary key default gen_random_uuid(),
  business_id     uuid not null references public.businesses (id) on delete cascade,
  client_id       uuid,
  appointment_id  uuid references public.appointments (id) on delete set null,
  call_id         uuid references public.calls (id) on delete set null,
  kind            text not null check (kind in ('callback', 'emergency', 'question',
                                                'reschedule', 'cancel', 'complaint', 'other')),
  urgency         text not null default 'normal' check (urgency in ('normal', 'urgent')),
  summary         text not null check (char_length(summary) between 1 and 1000),
  channel         text check (channel in ('whatsapp', 'voice', 'staff', 'api', 'system')),
  status          text not null default 'open' check (status in ('open', 'done', 'dismissed')),
  created_at      timestamptz not null default now(),
  resolved_at     timestamptz,
  resolved_by     uuid references auth.users (id) on delete set null,
  foreign key (client_id, business_id)
    references public.clients (id, business_id) on delete cascade
);
create index staff_tasks_open_idx on public.staff_tasks (business_id, created_at desc)
  where status = 'open';

-- ---------------------------------------------------------------------------
-- Voice tool calls: log for review in the admin, and idempotency. A retried tool call with
-- the same body returns the stored response instead of acting twice.
-- ---------------------------------------------------------------------------
create table public.voice_tool_calls (
  id              bigint generated always as identity primary key,
  business_id     uuid not null references public.businesses (id) on delete cascade,
  call_id         uuid references public.calls (id) on delete cascade,
  interaction_id  text not null,
  tool            text not null,
  request_hash    text not null,
  request         jsonb not null default '{}'::jsonb,
  response        jsonb,
  status          text not null default 'pending' check (status in ('pending', 'done')),
  ok              boolean,
  duration_ms     integer,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz,
  unique (business_id, interaction_id, tool, request_hash)
);
create index voice_tool_calls_call_idx on public.voice_tool_calls (call_id, created_at);

-- ---------------------------------------------------------------------------
-- Spend ledger. Sarvam credits are one organisation-wide wallet, so a row may have no
-- business. Outbound calls and test runs reserve an estimate first and are blocked when the
-- session or daily cap would be passed; the end-of-call payload settles the actual amount.
-- ---------------------------------------------------------------------------
create table public.spend_ledger (
  id              bigint generated always as identity primary key,
  business_id     uuid references public.businesses (id) on delete set null,
  kind            text not null check (kind in ('outbound_call', 'inbound_call', 'test_run')),
  session_id      text not null,
  spend_day       date not null,                 -- IST calendar day
  estimated_inr   numeric(10, 2) not null default 0 check (estimated_inr >= 0),
  actual_inr      numeric(10, 2) check (actual_inr is null or actual_inr >= 0),
  status          text not null default 'reserved'
                    check (status in ('reserved', 'settled', 'released')),
  call_id         uuid references public.calls (id) on delete set null,
  attempt_id      text,
  interaction_id  text,
  note            text,
  created_at      timestamptz not null default now(),
  settled_at      timestamptz
);
create index spend_ledger_day_idx on public.spend_ledger (spend_day);
create index spend_ledger_session_idx on public.spend_ledger (session_id);
create unique index spend_ledger_interaction_idx on public.spend_ledger (interaction_id)
  where interaction_id is not null;

-- ---------------------------------------------------------------------------
-- Funnel events: voice tool calls, outbound requests (dry runs included) and spend caps.
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
    'reminder_sent', 'no_response', 'handoff_task_created',
    'voice_tool_called', 'outbound_call_requested', 'spend_cap_reached'));

-- ---------------------------------------------------------------------------
-- RLS. Written only by apps/api (service role). Staff read; staff may close tasks.
-- ---------------------------------------------------------------------------
alter table public.staff_tasks       enable row level security;
alter table public.voice_tool_calls  enable row level security;
alter table public.spend_ledger      enable row level security;

revoke all on public.staff_tasks, public.voice_tool_calls, public.spend_ledger from anon;
revoke insert, update, delete on public.staff_tasks, public.voice_tool_calls,
  public.spend_ledger from authenticated;

create policy staff_tasks_select on public.staff_tasks
  for select to authenticated using (public.has_staff_access(business_id));
create policy staff_tasks_resolve on public.staff_tasks
  for update to authenticated
  using (public.has_staff_access(business_id))
  with check (public.has_staff_access(business_id));
grant update (status, resolved_at, resolved_by) on public.staff_tasks to authenticated;

create policy voice_tool_calls_select on public.voice_tool_calls
  for select to authenticated using (public.has_staff_access(business_id));

-- Rows without a business (org-wide spend) are visible to nobody but the service role.
create policy spend_ledger_select on public.spend_ledger
  for select to authenticated using (public.has_staff_access(business_id));
