"""Which supported language a patient's message is written in, per turn.

Patients switch languages mid-conversation and the reply follows them (docs/DECISIONS.md).
Hindi and Marathi share the Devanagari script, so they are told apart by common words.
Romanized Hindi and Marathi ("kal 11 baje", "udya sakali") are recognised the same way and
answered in Devanagari. Short neutral replies ("ok", "2", "yes", a weekday) and single English
words ("cancel", "reschedule") never switch.

Word lists are heuristics, not a language model: when unsure, keep the current language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from salesbot_core.packs.schema import Language
from salesbot_core.text.matching import tokens

Script = Literal["latin", "devanagari", "other", "none"]


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Words that are common in one language and rare in the other. Shared words (आज, नाही/nahi,
# का, हो) are left out on purpose.
_HI_DEVANAGARI = _words(
    "है हैं हूँ हूं नहीं मुझे मेरा मेरी मेरे आप आपका आपकी कल परसों करना करनी करो कीजिए "
    "चाहिए चाहता चाहती और क्या कब सुबह दोपहर शाम रात हाँ हां जी बदलना मैं में की के को से "
    "बजे ठीक अभी दीजिए बताइए कैसे कितने वाला वाली"
)
_MR_DEVANAGARI = _words(
    "आहे आहेत आहात आहोत नाहीत मला माझा माझी माझे तुम्ही तुमचा तुमची तुमचे उद्या परवा "
    "करायची करायचा करायचं करायचे हवी हवा हवं हवे आणि काय कधी सकाळी दुपारी संध्याकाळी "
    "रात्री होय नको पाहिजे चालेल बदलायची बदलायचा मध्ये वाजता वाजे द्या करा ठेवा येऊ येतो "
    "येते झालं झाले सांगा"
)
_HI_LATIN = _words(
    "hai hain hoon hun mujhe mera meri mere aap aapka aapki kal parso parson karna karni karo "
    "kijiye kijie chahiye chahta chahti aur kya kab subah dopahar shaam sham raat haan han ji "
    "badalna mein baje theek thik abhi accha acha achha dijiye batao bataiye kaise kitne"
)
_MR_LATIN = _words(
    "aahe ahe aahet ahet mala maza majha mazi majhi tumhi tumcha tumchi udya uddya parva "
    "karaycha karaychi karaycha karaych havi hava hav ani aani kay kadhi sakali dupari "
    "sandhyakali ratri hoy nako pahije chalel badlaychi madhe madhye vajta vajata dya kara "
    "theva yeu yeto yete zala jhala sanga"
)
# English words that show a message is English rather than a neutral reply. Neutral replies
# ("ok", "yes", "no", "thanks", "hi", numbers, weekday names) are deliberately absent.
_EN_WORDS = _words(
    "i im want need book booking appointment appt tomorrow today please cancel change "
    "reschedule time date morning afternoon evening night can could would the is are my me "
    "you to for at on with doctor next week available slot what when how not help talk speak "
    "call later earlier another other day which there this that do does have has will and or "
    "but sorry sure fine good free open"
)

_LANGUAGE_NAMES: dict[Language, frozenset[str]] = {
    "en": frozenset({"english", "angrezi", "angreji", "इंग्लिश", "अंग्रेजी", "इंग्रजी"}),
    "hi": frozenset({"hindi", "हिंदी", "हिन्दी"}),
    "mr": frozenset({"marathi", "मराठी"}),
}
_SWITCH_CUES = _words(
    "in me mein madhe madhye मध्ये में please pls bola बोला बोलिए बोलो language bhasha भाषा "
    "speak talk reply chalega chalel चलेगा चालेल"
)


@dataclass(frozen=True)
class Detected:
    # None = no clear evidence; keep the current language.
    language: Language | None
    script: Script

    @property
    def unsupported(self) -> bool:
        """Written in a script we do not support (Gujarati, Tamil, Urdu...)."""
        return self.script == "other"


def _is_devanagari(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def detect(text: str) -> Detected:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return Detected(None, "none")
    deva = sum(_is_devanagari(c) for c in letters)
    latin = sum(c.isascii() for c in letters)
    other = len(letters) - deva - latin
    if other > deva and other > latin:
        return Detected(None, "other")

    toks = set(tokens(text))
    if deva >= latin:
        hi, mr = len(toks & _HI_DEVANAGARI), len(toks & _MR_DEVANAGARI)
        script: Script = "devanagari"
    else:
        hi, mr = len(toks & _HI_LATIN), len(toks & _MR_LATIN)
        script = "latin"
    if hi > mr:
        return Detected("hi", script)
    if mr > hi:
        return Detected("mr", script)
    # English needs a phrase, not one word: Hindi and Marathi speakers type "cancel" too.
    if script == "latin" and hi == 0 and len(toks) >= 2 and toks & _EN_WORDS:
        return Detected("en", script)
    return Detected(None, script)


def requested_language(text: str) -> Language | None:
    """An explicit request to switch: "Marathi please", "हिंदी में बोलिए", "english"."""
    toks = tokens(text)
    for language, names in _LANGUAGE_NAMES.items():
        if names & set(toks) and (len(toks) <= 2 or _SWITCH_CUES & set(toks)):
            return language
    return None


def reply_language(
    detected: Detected,
    current: Language,
    *,
    supported: list[Language],
    fallback: Language,
) -> Language:
    """The language to answer this message in.

    `fallback` is the clinic's default language (English if unset), used for unsupported
    scripts and for languages the pack does not offer.
    """
    if detected.unsupported:
        return fallback if fallback in supported else supported[0]
    language = detected.language
    if language is None and detected.script == "devanagari" and current not in ("hi", "mr"):
        # Devanagari without clear Hindi/Marathi words: prefer the clinic's language.
        language = fallback if fallback in ("hi", "mr") else "hi"
    if language is None:
        return current
    if language not in supported:
        return fallback if fallback in supported else current
    return language


def recorded_language(detected: Detected) -> str | None:
    """Value for events.language: the detected language, "other", or None if unclear."""
    return "other" if detected.unsupported else detected.language
