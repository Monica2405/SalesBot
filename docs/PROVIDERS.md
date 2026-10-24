# External providers

Nothing paid is required to run the scaffold: every provider has a mock.

| Service | Used for | Paid? | Credentials (env) | Status |
|---|---|---|---|---|
| **Supabase** | Postgres, Auth (owner login), Storage (recordings) | Free tier exists (pauses after 7 days idle); Pro for pilots | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (server only), `SUPABASE_DB_URL`, `SUPABASE_JWT_SECRET`; admin: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | Schema written; no project linked |
| **Vercel** | Hosting the admin SPA | Free hobby tier; paid for teams/commercial use | Set in the Vercel dashboard (not in this repo) | Not linked |
| **Sarvam AI** – Saaras | Speech-to-text (hi, mr, en, code-mixed) | Paid (usage) | `SARVAM_API_KEY`, `STT_PROVIDER=sarvam` | Stub with TODO; read https://docs.sarvam.ai |
| **Sarvam AI** – Sarvam-30B | LLM for conversation | Paid (usage) | `SARVAM_API_KEY`, `LLM_PROVIDER=sarvam` | Stub with TODO |
| **Sarvam AI** – Bulbul | Text-to-speech | Paid (usage) | `SARVAM_API_KEY`, `TTS_PROVIDER=sarvam` | Stub with TODO |
| **Plivo** *or* **Exotel** | Phone numbers, inbound calls, media streaming, transfer, recording | Paid (number rental + per minute); KYC for Indian numbers | Plivo: `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`. Exotel: `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_SID` | **Open decision**; mock only |
| **Google Calendar** | Checking free slots, creating bookings | Free API (quota limits) | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` (+ per-business refresh token stored server-side) | Mock + stub |
| **WhatsApp** (provider TBD) | Confirmations, reminders, owner alerts | Paid per conversation | `WHATSAPP_PROVIDER`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID` | **Open decision**; mock only |
| **HubSpot** (optional) | Mirror leads/deals into an existing CRM | Free CRM tier; paid hubs | `HUBSPOT_ENABLED=true`, `HUBSPOT_ACCESS_TOKEN` (private app) | Off by default; stub |
| **Container host** (TBD) | Running api and voice-agent images | Paid | Host-specific | **Open decision** |

Cost per call is tracked from provider usage: `calls.stt_seconds`, `llm_tokens_in`,
`llm_tokens_out`, `tts_characters` (+ telephony minutes from `duration_seconds`).
Usage caps: `DEFAULT_BUSINESS_USAGE_CAP_MINUTES`, per-business `businesses.usage_cap_minutes`,
and `CALL_MAX_SECONDS` per call.
