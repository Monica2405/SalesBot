"""AI disclosure and recording consent, said at the very start of every call.

STUB: keyword matching only. TODO: confirm wording with a lawyer (DPDP Act, see
docs/DECISIONS.md) and let the LLM classify unclear answers. Unclear = no consent (safe default).
"""

from __future__ import annotations

from salesbot_core.packs.schema import Language

DISCLOSURE: dict[Language, str] = {
    "en": (
        "Hello, you are speaking with the AI assistant for {business_name}. "
        "This call may be recorded to help us serve you better. Is that okay?"
    ),
    "hi": (
        "नमस्ते, आप {business_name} की AI सहायक से बात कर रहे हैं। "
        "बेहतर सेवा के लिए यह कॉल रिकॉर्ड की जा सकती है। क्या यह ठीक है?"
    ),
    "mr": (
        "नमस्कार, तुम्ही {business_name} च्या AI सहाय्यकाशी बोलत आहात. "
        "चांगल्या सेवेसाठी हा कॉल रेकॉर्ड केला जाऊ शकतो. चालेल का?"
    ),
}

_YES = {"yes", "yeah", "ok", "okay", "sure", "haan", "ha", "हाँ", "हां", "ठीक", "हो", "चालेल"}
_NO = {"no", "nope", "nahi", "nahin", "नहीं", "नही", "नको", "नाही"}


def disclosure_text(language: Language, business_name: str) -> str:
    return DISCLOSURE.get(language, DISCLOSURE["en"]).format(business_name=business_name)


def parse_consent(answer: str) -> bool | None:
    """True = consented, False = declined, None = unclear."""
    words = {w.strip(".,!?।") for w in answer.casefold().split()}
    if words & _NO:
        return False
    if words & _YES:
        return True
    return None
