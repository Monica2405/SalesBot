"""The wording scan: patient-facing text must not mention AI, bots, virtual or automated
assistants, or claim to be a person (owner's policy, docs/DECISIONS.md).

`forbidden_terms(text)` returns what it found. Tests run it over every pack's patient-facing
text, the voice agent's fixed lines, and every reply the flow engine produces in scripted
conversations. The only text exempt is the sincere-ask answer (`conversation.sincere_ask`).
Inputs (intent phrases, triggers) are never shown to patients and are not scanned.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from salesbot_core.packs import Pack
from salesbot_core.packs.schema import Language
from salesbot_core.text.matching import normalize

# Latin script, matched as whole words, case-insensitive.
_LATIN = [
    r"a\.?i\.?",
    r"artificial intelligence",
    r"bots?",
    r"chat ?bots?",
    r"robots?",
    r"virtual",
    r"automat\w*",
    r"machines?",
    r"computers?",
    r"algorithms?",
    r"language models?",
    r"llms?",
    r"gpt",
    r"software",
    r"human",
    r"real person",
    r"i am a person",
    r"i'?m a person",
    r"staff member",
    r"receptionist",
]
_LATIN_RE = re.compile(r"(?<![\w.])(?:" + "|".join(_LATIN) + r")(?![\w])", re.IGNORECASE)

# Devanagari (Hindi and Marathi), matched as substrings after normalization.
_DEVANAGARI = [
    "एआई", "ए.आई", "एआय", "ए.आय", "बॉट", "रोबोट", "चैटबॉट", "चॅटबॉट", "वर्चुअल",
    "व्हर्च्युअल", "आभासी", "स्वचालित", "स्वयंचलित", "ऑटोमेटेड", "ऑटोमैटिक", "ऑटोमॅटिक",
    "कृत्रिम", "मशीन", "यंत्र", "कंप्यूटर", "कम्प्यूटर", "संगणक", "सॉफ्टवेयर", "सॉफ्टवेअर",
    "इंसान", "मनुष्य", "माणूस", "असली व्यक्ति", "खरी व्यक्ती", "स्टाफ सदस्य",
]  # fmt: skip
_DEVANAGARI_NORMALIZED = [normalize(t) for t in _DEVANAGARI]


def forbidden_terms(text: str) -> list[str]:
    found = [m.group(0) for m in _LATIN_RE.finditer(text)]
    norm = normalize(text)
    found += [t for t in _DEVANAGARI_NORMALIZED if t in norm]
    return found


def patient_texts(pack: Pack) -> Iterator[tuple[str, Language, str]]:
    """Every patient-facing text in a pack as (where, language, text), except the sincere-ask
    answer, which is the one place automation may be mentioned."""
    for language, text in pack.greeting.items():
        yield "greeting", language, text
    for q in pack.intake_questions:
        for language, text in q.prompt.items():
            yield f"intake_questions.{q.key}", language, text
    for s in pack.services:
        for language, text in s.name.items():
            yield f"services.{s.id}", language, text
    for i, faq in enumerate(pack.faqs):
        for field, localized in (("question", faq.question), ("answer", faq.answer)):
            for language, text in localized.items():
                yield f"faqs[{i}].{field}", language, text
    if pack.emergency is not None:
        for language, text in pack.emergency.message.items():
            yield "emergency.message", language, text
    if pack.conversation is not None:
        for key, localized in pack.conversation.messages.items():
            for language, text in localized.items():
                yield f"conversation.messages.{key}", language, text
