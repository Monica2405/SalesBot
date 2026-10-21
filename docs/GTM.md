# GTM: how this product makes and measures revenue

## Why this project exists

SalesBot is preparation for a **GTM engineer** role. That role builds revenue systems: CRM
integration, workflow automation, funnel analytics, lead scoring, source attribution, follow-up
automation, and AI agents judged on conversion. So every feature here is built to be measured in
revenue terms, and the design question is always: **what does this let us measure or convert?**

## The funnel

| Stage | Event (`events.type`) | Question it answers |
|---|---|---|
| Call | `call_received` | How much demand reaches the business? Which sources drive it? |
| Lead | `lead_captured` | Did we capture name, number and need, even when we could not book? |
| Booking | `booking_created` | Did the call turn into a slot on the calendar? |
| Show | `appointment_showed` / `appointment_no_show` | Did the booking turn into a visit? |
| Paid | `payment_recorded` (`value_inr`) | How much revenue did the agent produce? |

Supporting events: `call_answered`, `consent_given/declined`, `question_unanswered`,
`emergency_detected`, `handoff_requested`, `callback_requested`, `booking_cancelled`, `call_ended`.

## Core metrics

- **Answer rate**: answered / received (the agent should be ~100%: that is the pitch vs missed calls)
- **Lead capture rate**: leads / answered calls
- **Booking rate**: bookings / leads, split by service
- **Show rate**: shows / bookings (what reminders should move)
- **Revenue per call**: paid `value_inr` / calls, and estimated pipeline from `services.price_inr`
- **Cost per call / per booking**: STT seconds + LLM tokens + TTS characters + telephony minutes
- **ROI for the owner**: revenue attributed / subscription + usage cost
- Every metric is sliceable by **source** (attribution), **script version** (A/B), **language** and
  **time of day** (after-hours calls are the clearest win).

## How each feature feeds the funnel

| Feature | Stage it moves | What we measure |
|---|---|---|
| Answer every call, 24/7, in 3 languages | Call → Lead | answer rate, after-hours leads, leads by language |
| Pack intake questions | Lead | completeness of lead data, lead capture rate |
| Booking against Google Calendar | Lead → Booking | booking rate, time-to-book |
| Emergency triggers + handoff/callback | Lead (no loss) | callbacks requested vs completed |
| Unanswered questions → knowledge base | Lead → Booking | unanswered rate trending down, booking rate on FAQ calls |
| WhatsApp confirmations and reminders | Booking → Show | show rate with vs without reminders |
| Lead stages in the admin | Show → Paid | stage conversion, time in stage |
| Script versions | All | conversion by `script_version_id` (A/B) |
| Source on every call and lead | All | conversion and revenue by channel (Google Business, ads, referral…) |
| Usage records and caps | Margin | cost per call/booking, gross margin per business |
| Follow-up sequences (schema only) | Lead → Booking, No-show → Booking | recovered leads |
| Lead score (column ready) | Prioritisation | conversion by score band |
| HubSpot sync (optional) | Ops | for businesses that already live in a CRM |

## Data principles

- Funnel numbers come only from the append-only `events` table, so history never changes under you.
- Test calls are tagged `source = test_call` and excluded from metrics.
- Every metric must be reproducible with a SQL query over `events` + `calls` + `appointments`.
