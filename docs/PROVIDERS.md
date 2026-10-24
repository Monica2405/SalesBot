# External providers

Nothing paid is required to run the scaffold: every provider has a mock.

| Service | Used for | Paid? | Credentials (env) | Status |
|---|---|---|---|---|
| **Supabase** | Postgres, Auth (owner login), Storage (recordings) | Free tier exists (pauses after 7 days idle); Pro for pilots | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (server only), `SUPABASE_DB_URL`, `SUPABASE_JWT_SECRET`; admin: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Schema written; no project linked |
| **Vercel** | Hosting the admin SPA | Free hobby tier; paid for teams/commercial use | Set in the Vercel dashboard (not in this repo) | Not linked |
| **Sarvam Voice Agents** | The whole call: speech, language model, voice, telephony (Vobiz numbers rented from Sarvam), recording, analytics | Paid per minute from one org-wide credit wallet (docs/COSTS.md) | `SARVAM_API_KEY` (header `X-API-Key`), `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_APP_ID`, `SARVAM_APP_VERSION`, `SARVAM_CONNECTION_ID`, `SARVAM_AGENT_PHONE_NUMBER`; ours: `VOICE_TOOL_SECRET`, `VOICE_WEBHOOK_SECRET` | Integration built (tools, hooks, webhooks, outbound adapter, analytics); agent not created; outbound off |
| **Plivo** *or* **Exotel** | Bring-your-own telephony into Sarvam, if Sarvam numbers do not work out | Paid by the provider | Entered in Sarvam's dashboard, not here | Documented fallback only |
| **Google Calendar** | Checking free slots, creating bookings | Free API (quota limits) | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` (+ per-business refresh token stored server-side) | Mock + stub |
| **WhatsApp** (Meta Cloud API, own adapter) | Welcome, confirmations, reminders | Paid per message by category (docs/COSTS.md) | `WHATSAPP_PROVIDER`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID` | Stage C; production provider still open |
| **HubSpot** (optional) | Mirror leads/deals into an existing CRM | Free CRM tier; paid hubs | `HUBSPOT_ENABLED=true`, `HUBSPOT_ACCESS_TOKEN` (private app) | Off by default; stub |
| **Container host** (TBD) | Running the api image (always on: Sarvam calls it mid-call) | Paid | Host-specific | **Open decision** |

Cost per call: `calls.agent_minutes` (60-second pulses) and `telephony_pulses` (30-second
pulses), derived from the duration in Sarvam's end-of-call payload, priced from
`packages/core/src/salesbot_core/costs/rates.yaml` (docs/COSTS.md). Spend control:
`SPEND_SESSION_CAP_INR`, `SPEND_DAILY_CAP_INR` and `CALL_MAX_SECONDS` (also set the agent's max
call length in Sarvam to match).
