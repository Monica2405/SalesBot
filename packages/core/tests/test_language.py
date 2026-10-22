import pytest

from salesbot_core.text.language import (
    Detected,
    detect,
    recorded_language,
    reply_language,
    requested_language,
)

SUPPORTED = ["en", "hi", "mr"]


@pytest.mark.parametrize(
    ("text", "language", "script"),
    [
        # Devanagari: Hindi and Marathi told apart by common words.
        ("मुझे कल अपॉइंटमेंट चाहिए", "hi", "devanagari"),
        ("क्या शाम को समय है?", "hi", "devanagari"),
        ("मला उद्या अपॉइंटमेंट हवी आहे", "mr", "devanagari"),
        ("संध्याकाळी वेळ आहे का?", "mr", "devanagari"),
        # Romanized Hindi and Marathi.
        ("mujhe kal appointment chahiye", "hi", "latin"),
        ("kya shaam ko time hai", "hi", "latin"),
        ("mala udya appointment havi aahe", "mr", "latin"),
        ("udya sakali 11 vajta", "mr", "latin"),
        # English needs a phrase.
        ("I want to book an appointment", "en", "latin"),
        ("can I come tomorrow morning", "en", "latin"),
    ],
)
def test_detect(text, language, script):
    assert detect(text) == Detected(language, script)


@pytest.mark.parametrize(
    "text", ["ok", "2", "yes", "monday", "cancel", "reschedule", "👍", "11:30"]
)
def test_neutral_replies_do_not_pick_a_language(text):
    assert detect(text).language is None


@pytest.mark.parametrize("text", ["હું કાલે આવીશ", "நாளை வருகிறேன்", "میں کل آؤں گا"])
def test_unsupported_scripts(text):
    detected = detect(text)
    assert detected.unsupported
    assert recorded_language(detected) == "other"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        # Marathi words outnumber shared ones once the Hindi-only words are gone.
        ("udya sakali 11 baje", "mr"),
        # Plain romanized Hindi.
        ("kal subah 11 baje", "hi"),
        # Hinglish: English words plus a Hindi marker reads as Hindi.
        ("kal morning 11 baje chalega", "hi"),
    ],
)
def test_romanized_time_requests(text, language):
    assert detect(text).language == language


@pytest.mark.xfail(
    strict=True,
    reason="known bug (Step 2): kal and baje count as Hindi and outvote Marathi sakali",
)
def test_romanized_marathi_with_shared_words():
    assert detect("kal sakali 11 baje").language == "mr"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Marathi please", "mr"),
        ("marathi", "mr"),
        ("हिंदी में बोलिए", "hi"),
        ("english", "en"),
        ("मराठीत बोला", None),  # inflected form: not recognised, the engine keeps going
        ("my hindi teacher booked here last year", None),
    ],
)
def test_requested_language(text, language):
    assert requested_language(text) == language


def test_reply_follows_a_clear_language():
    assert reply_language(Detected("mr", "latin"), "en", supported=SUPPORTED, fallback="en") == "mr"


def test_reply_is_sticky_when_unclear():
    unclear = Detected(None, "latin")
    assert reply_language(unclear, "mr", supported=SUPPORTED, fallback="en") == "mr"
    assert reply_language(Detected(None, "none"), "hi", supported=SUPPORTED, fallback="en") == "hi"


def test_unsupported_script_gets_the_clinic_language():
    other = Detected(None, "other")
    assert reply_language(other, "hi", supported=SUPPORTED, fallback="mr") == "mr"
    # A clinic default the pack does not offer falls back to the pack's first language.
    assert reply_language(other, "hi", supported=["en", "hi"], fallback="mr") == "en"


def test_unclear_devanagari_from_english_prefers_the_clinic_language():
    unclear = Detected(None, "devanagari")
    assert reply_language(unclear, "en", supported=SUPPORTED, fallback="mr") == "mr"
    assert reply_language(unclear, "en", supported=SUPPORTED, fallback="en") == "hi"
    # Already in Hindi or Marathi: stay.
    assert reply_language(unclear, "mr", supported=SUPPORTED, fallback="en") == "mr"


def test_language_the_pack_does_not_offer():
    hindi = Detected("hi", "devanagari")
    assert reply_language(hindi, "en", supported=["en", "mr"], fallback="mr") == "mr"
    assert reply_language(hindi, "en", supported=["en"], fallback="hi") == "en"


@pytest.mark.xfail(
    strict=True,
    reason="known gap (Step 2): Marathi verb forms like दुखतंय are not in the word list",
)
def test_marathi_without_listed_words():
    assert detect("छातीत दुखतंय").language == "mr"
