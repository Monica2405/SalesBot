# Costs

Prices **as of 22 Oct 2026**, in Indian rupees, **excluding GST**. USD converted at ₹87.

> **Next editor: re-verify every price against the sources before any quote to a client**, then
> update the date here and `last_verified` in `packages/core/src/salesbot_core/costs/rates.yaml`
> (the app's cost estimates read that file; a test keeps the two in step).
> Currently: rates.yaml last_verified: 2026-10-22

Sources: [docs.sarvam.ai/voice-agents/pricing](https://docs.sarvam.ai/voice-agents/pricing),
[docs.sarvam.ai/api/platform/billing](https://docs.sarvam.ai/api/platform/billing), Meta's
WhatsApp Business Platform pricing pages (the WhatsApp figures below are third-party; check Meta).

## Credits (as of 24 Oct 2026)

- **Credits Left: 1,00,100** on Sarvam's Settings -> Billing (owner, 24 Oct 2026): about ₹1,00,000
  of YC credit plus the ₹100 sign-up credit. 1 credit = ₹1.
- **About 25,000 managed minutes** at ₹3.90 per minute including Sarvam telephony
  (a call billed as whole minutes: ₹3.50 agent + 2 pulses x ₹0.20). 1,00,100 / 3.90 ≈ 25,667.
- **Why the YC credit covers Voice Agents** (Sarvam billing docs, read 23 Oct 2026): "There is one
  credit balance per organisation, and every workspace, every API key, and every Sarvam product
  draws from it", and "Model APIs, Voice Agents, Doc Agents, Content Agents and the rest all spend
  from the same pool". Rented numbers are deducted from the same wallet ("The cost of the number
  is deducted from your Sarvam wallet", Rent from Sarvam FAQ).
- **Expiry: unknown.** Sarvam's billing page says "Credits do not expire", but that describes the
  wallet in general; a promotional grant may carry its own terms. The owner is checking the YC
  redemption email. **Open item:** record the YC credit's expiry here and in DECISIONS.md once
  known.
- Running out: API calls fail with `402`, and a rented number whose renewal cannot be paid is
  **released with no grace period** (its deployments and campaigns are cancelled).

## Sarvam Voice Agents (speech, language and voice models included)

| Plan | Rate | Monthly minimum (returns as credits) | For |
|---|---:|---:|---|
| Pay as you go | ₹3.50/min | none | under 3,000 min/month |
| Pro | ₹3.25/min | ₹9,999 | 3,000 to 16,000 min |
| Growth | ₹3.15/min | ₹49,999 | 16,000 to 65,000 min |
| Business | ₹3.00/min | ₹1,99,999 | 65,000 to 2 lakh min |
| Enterprise | custom | committed volume | 2 lakh min and above |

- A minute is a **60-second pulse, rounded up** (45 s = 1 minute, 61 s = 2 minutes).
- A paid plan's monthly fee comes back in full as credits (one credit per rupee).
- The brief listed Business as "coming soon"; Sarvam's pricing page now lists it at ₹3.00 with a
  ₹1,99,999 minimum (and 200 concurrent / 800 calls per minute).

## Telephony and numbers (billed separately, same on every plan)

| Item | Price | Per |
|---|---:|---|
| Bring your own telephony (Plivo, Exotel, ...) | free on Sarvam | the provider bills you |
| Sarvam telephony (Vobiz) | ₹0.20 | 30-second pulse, rounded up |
| Call forwarding to a phone number (PSTN) | ₹0.40 | 30-second pulse |
| Call forwarding to a SIP destination | ₹0.35 | 30-second pulse |
| Number rental (11, 79 or 80 series) | ₹59 | number per 30 days |

- A rented number renews every 30 days from credits; **no grace period** if credits run short.
- Once the agent forwards a call it is off the call: the forwarded part is billed as forwarding
  pulses only, not agent minutes.
- **Unanswered, busy and failed calls cost nothing.** A voicemail-answered call has connected
  and is billed like any call.
- **Simulated test run: ₹2** per run.

**Example:** a 45-second call on Sarvam telephony = 1 agent minute + 2 pulses = ₹3.50 + ₹0.40 =
**₹3.90**.

## Rate limits (organisation-wide)

| Plan | Concurrent calls | Calls started per minute |
|---|---:|---:|
| Pay as you go | 4 | 20 |
| Pro | 10 | 50 |
| Growth | 30 | 150 |
| Business | 200 | 800 |

Every campaign, instant outbound and inbound call counts; a call past a limit is rejected.

## WhatsApp (Meta Cloud API, India)

- Utility template about ₹0.115, marketing about ₹0.8631 (third-party figures, check Meta).
- Since 1 Oct 2026, utility templates inside an open customer-service window are billed too, and
  service messages are free only for the first 1,000 per business number per month.
- Estimate **₹0.35 to ₹0.46 per appointment** (welcome, confirmation request, reminders).
- Messages are counted by pricing category; `salesbot_core.costs.whatsapp_cost` prices them
  (message storage arrives with the WhatsApp adapter, Stage C).

## Example monthly spend (estimate; calls average whole minutes)

| Minutes | Plan | Voice | Telephony | Number | Total |
|---:|---|---:|---:|---:|---:|
| 1,000 | Pay as you go | ₹3,500 | ₹400 | ₹59 | about ₹3,960 |
| 3,000 | Pro | ₹9,999 (minimum) | ₹1,200 | ₹59 | about ₹11,260 |
| 10,000 | Pro | ₹32,500 | ₹4,000 | ₹59 | about ₹36,600 |

**Other recurring:** Supabase Pro $25 per organisation per month (about ₹2,175), needed before any
pilot. Container host: not yet priced. Vercel for the admin: not researched.

**A 1,000-minute pilot month is roughly ₹6,300 all-in**, excluding GST and hosting.

## How the app tracks cost

- Sarvam's end-of-call payloads report the call's **duration in seconds** and no billed amounts,
  so `calls.agent_minutes` (60-second pulses) and `calls.telephony_pulses` (30-second pulses) are
  derived from it, and `calls.cost_inr_estimate` is priced from `rates.yaml` (with
  `calls.rates_verified_on`). Each finished call's spend is logged and written to `spend_ledger`.
- Known gaps: Sarvam's dashboard (Settings -> Usage) is the billing truth. Our estimate assumes
  the pay-as-you-go rate and Sarvam telephony, and counts telephony pulses on the agent's part of
  the call; check against the dashboard after the first real calls.
- Cost per confirmed appointment = voice cost / `appointment_confirmed` events in the month.

## Spend guard

The YC credit is one shared wallet, so anything **we** start that spends it goes through a guard
(`salesbot_api.voice.spend`):

- **Per test session cap: ₹100** (`SPEND_SESSION_CAP_INR`). A session is one API process, or
  whatever `SPEND_SESSION_ID` names.
- **Per day cap: ₹500** (`SPEND_DAILY_CAP_INR`), per IST calendar day, across sessions.
- Before an outbound call, its worst case (the max call length, `CALL_MAX_SECONDS`, default 600 s
  = ₹39) is reserved. Before simulated test runs, run `make voice-ops ARGS='test-runs N'` (₹2
  each). If a cap would be passed, nothing starts and the error says which cap, how much is used,
  and which setting to raise. A `spend_cap_reached` event is recorded.
- The end-of-call payload settles the actual amount; inbound calls are recorded too and count
  toward the daily cap (we cannot refuse an inbound call).
- `make voice-ops ARGS='spend'` shows usage against both caps.
- Limits of the guard: it cannot stop test runs clicked in Sarvam's dashboard without the
  `test-runs` reservation, or calls placed from Sarvam's dashboard. Set the agent's max call
  length in Sarvam to match `CALL_MAX_SECONDS`.
- **The owner is asked, with an estimated cost, before any action that spends credits.**

## Actuals

Filled from real calls with `make voice-ops ARGS='actuals'` (paste the output here). Replace the
estimates above with these after the pilot.

| Month | Connected calls | Agent minutes | Telephony pulses | Voice cost (Rs) | Rs per call | Confirmed appointments | Rs per confirmed appointment |
|---|---:|---:|---:|---:|---:|---:|---:|
| (no calls yet) | | | | | | | |
