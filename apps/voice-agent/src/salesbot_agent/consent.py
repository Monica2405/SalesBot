"""Opening line and recording consent, said at the very start of every call.

Wording policy (docs/DECISIONS.md): patient-facing text never mentions AI, bots or automation
and never claims to be a person, so the opening names the business only. The recording-consent
question stays (owner's decision, 2026-10-21) even though no call audio is stored today.
Hindi and Marathi lines are DRAFT until a native speaker reviews them.

STUB: keyword matching only. TODO: confirm wording with a lawyer (DPDP Act, see
docs/DECISIONS.md) and let the LLM classify unclear answers. Unclear = no consent (safe default).
"""

from __future__ import annotations

from salesbot_core.packs.schema import Language

OPENING: dict[Language, str] = {
    "en": (
        "Hello, thank you for calling {business_name}. "
        "This call may be recorded to help us serve you better. Is that okay?"
    ),
    "hi": (
        "नमस्ते, {business_name} में कॉल करने के लिए धन्यवाद। "
        "बेहतर सेवा के लिए यह कॉल रिकॉर्ड की जा सकती है। क्या यह ठीक है?"
    ),
    "mr": (
        "नमस्कार, {business_name} मध्ये फोन केल्याबद्दल धन्यवाद. "
        "चांगल्या सेवेसाठी हा कॉल रेकॉर्ड केला जाऊ शकतो. चालेल का?"
    ),
}

_YES = {"yes", "yeah", "ok", "okay", "sure", "haan", "ha", "हाँ", "हां", "ठीक", "हो", "चालेल"}
_NO = {"no", "nope", "nahi", "nahin", "नहीं", "नही", "नको", "नाही"}


def opening_text(language: Language, business_name: str) -> str:
    return OPENING.get(language, OPENING["en"]).format(business_name=business_name)


def parse_consent(answer: str) -> bool | None:
    """True = consented, False = declined, None = unclear."""
    words = {w.strip(".,!?।") for w in answer.casefold().split()}
    if words & _NO:
        return False
    if words & _YES:
        return True
    return None
