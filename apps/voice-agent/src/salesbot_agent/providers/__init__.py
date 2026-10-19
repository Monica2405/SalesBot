"""Provider implementations per layer. Interfaces live in salesbot_core.providers.

Each module has a working mock and a Sarvam stub. Pick with STT_PROVIDER / LLM_PROVIDER /
TTS_PROVIDER / TELEPHONY_PROVIDER.
"""

# Sarvam's API reference. Read it before filling any Sarvam TODO. Do not guess endpoints or
# model names: copy them from the docs and note the docs date in the commit.
SARVAM_DOCS = "https://docs.sarvam.ai"
