"""Voice channel: the API that Sarvam Voice Agents calls (docs/SARVAM_AGENT.md).

Sarvam runs the call (speech, language model, voice, telephony). Every business rule stays
here so the voice vendor can be swapped:
- tools.py     API tools the agent calls mid-call, plus the on-start and on-end hooks
- webhooks.py  Sarvam's call-completion webhooks (duration, transcript, cost)
- outbound.py  outbound calls behind OUTBOUND_CALLS_ENABLED, dry run by default
- spend.py     the spend guard for the shared Sarvam credit wallet
- store.py     database reads and writes for the above
- sarvam.py    Sarvam HTTP clients (outbound calls, Analytics), each with a mock
- security.py  bearer auth for tools, path token for webhooks, optional IP allowlist
"""
