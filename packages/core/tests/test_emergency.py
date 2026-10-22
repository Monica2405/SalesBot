"""Emergency safeguard: a possible emergency never gets a wrong-language or generic reply.

- Checked before anything else, including the language update: the conversation language
  does not change during an emergency.
- The reply is in the patient's last known language. If the message is clearly in another
  allowed language, a second line in that language follows.
- Every emergency reply contains the clinic phone and every emergency number.
- Live channels never send DRAFT text: they send the language-neutral fallback (numbers
  only) instead of blocking the turn.
"""

import pytest
from pydantic import ValidationError

from salesbot_core.events import EventType
from salesbot_core.flow import FlowContext, FlowEngine, ensure_sendable
from salesbot_core.flow.memory import InMemoryScheduling
from salesbot_core.packs import load_pack_by_id
from salesbot_core.packs.schema import Conversation
from salesbot_core.scheduling import SchedulingSettings

CLINIC_PHONE = "+910000000000"
ALL_LANGUAGES = SchedulingSettings(allowed_languages=["en", "hi", "mr"])

ENGLISH = [
    "my father has chest pain",
    "she can't breathe",
    "he cant breathe",
    "difficulty breathing",
    "bleeding a lot after the extraction",
    "it won't stop bleeding",
    "he fainted",
    "she passed out",
    "severe pain in my jaw",
    "unbearable pain",
    "this is an emergency",
]
HINDI = [
    "सीने में दर्द हो रहा है",
    "छाती में दर्द",
    "सांस नहीं आ रही",
    "सांस लेने में तकलीफ",
    "बहुत खून बह रहा है",
    "वो बेहोश हो गए",
    "बहुत तेज़ दर्द है",
    "असहनीय दर्द",
]
HINGLISH = [
    "seene mein dard ho raha hai",
    "chhati me dard",
    "saans nahi aa rahi",
    "sans lene me takleef",
    "khoon beh raha hai",
    "bahut khoon nikal raha",
    "papa behosh ho gaye",
    "bahut tez dard hai",
]
# Bonus coverage: Marathi is lower-tested (docs/DECISIONS.md).
MARATHI = [
    "मला छातीत दुखतंय",
    "श्वास घेता येत नाही",
    "खूप रक्त येतंय",
    "ते बेशुद्ध झाले",
    "chhatit dukhtay",
]


def keys(turn):
    return [r.key for r in turn.replies]


@pytest.mark.parametrize("text", ENGLISH + HINDI + HINGLISH + MARATHI)
def test_emergency_phrases(make_chat, text):
    chat = make_chat(settings=ALL_LANGUAGES)
    chat.send("book")
    turn = chat.send(text)
    assert set(keys(turn)) == {"emergency"}
    assert all(r.options == [] for r in turn.replies)
    assert [(t.kind, t.urgent) for t in turn.tasks] == [("emergency", True)]
    assert EventType.EMERGENCY_DETECTED in [e.type for e in turn.events]


@pytest.mark.parametrize(
    "text",
    [
        "dard thoda kam hai",
        "no pain now, can I book a check-up",
        "is there bleeding after cleaning usually",
        "my breathing is fine",
        "khoon ki report laani hai kya",
    ],
)
def test_everyday_text_is_not_an_emergency(make_chat, text):
    chat = make_chat()
    turn = chat.send(text)
    assert "emergency" not in keys(turn)
    assert all(t.kind != "emergency" for t in turn.tasks)


def test_language_does_not_switch_during_an_emergency(make_chat):
    chat = make_chat("hi")
    turn = chat.send("I have chest pain")
    # Last known language first, then the language the patient just wrote in.
    assert [r.language for r in turn.replies] == ["hi", "en"]
    assert chat.state.language == "hi"


def test_second_line_only_when_the_language_is_clear(make_chat):
    chat = make_chat("en")
    turn = chat.send("सीने में दर्द")  # clear Hindi
    assert [r.language for r in turn.replies] == ["en", "hi"]
    assert chat.state.language == "en"
    chat = make_chat("hi")
    turn = chat.send("chest pain")  # no clear language
    assert [r.language for r in turn.replies] == ["hi"]


def test_second_line_only_for_allowed_languages(make_chat):
    chat = make_chat("en", settings=SchedulingSettings())  # default: en and hi only
    turn = chat.send("मला छातीत दुखतंय")
    assert [r.language for r in turn.replies] == ["en"]


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_every_emergency_reply_has_the_clinic_phone_and_numbers(make_chat, language):
    settings = SchedulingSettings(
        allowed_languages=["en", "hi", "mr"], emergency_numbers=["112", "108", "102"]
    )
    chat = make_chat(language, settings=settings)
    for text in ("chest pain", "I have chest pain", "सीने में दर्द"):
        turn = chat.send(text)
        assert turn.replies
        for reply in turn.replies:
            for out in (reply.text, reply.fallback):
                assert out and CLINIC_PHONE in out, (reply.language, out)
                for number in ("112", "108", "102"):
                    assert number in out, (reply.language, number, out)


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_live_channel_sends_the_fallback_instead_of_blocking(make_chat, language):
    chat = make_chat(language, settings=ALL_LANGUAGES)
    turn = chat.send("chest pain")
    # The full emergency wording is DRAFT until clinically reviewed.
    assert all(r.draft for r in turn.replies)
    sent = ensure_sendable(turn.replies, live=True)
    assert [r.key for r in sent] == ["emergency_fallback"]
    assert not sent[0].draft
    assert sent[0].language == language
    for number in (CLINIC_PHONE, "112", "108"):
        assert number in sent[0].text


def test_two_emergency_lines_send_one_fallback(make_chat):
    chat = make_chat("hi")
    turn = chat.send("I have chest pain")
    sent = ensure_sendable(turn.replies, live=True)
    assert [(r.key, r.language) for r in sent] == [("emergency_fallback", "hi")]


def test_fallback_must_have_no_wording():
    pack = load_pack_by_id("clinic")
    data = pack.conversation.model_dump()
    with pytest.raises(ValidationError, match="emergency_fallback"):
        Conversation.model_validate(
            {**data, "emergency_fallback": "Call {emergency_numbers} now · {clinic_phone}"}
        )
    with pytest.raises(ValidationError, match="emergency_fallback"):
        Conversation.model_validate({**data, "emergency_fallback": "🚑 {emergency_numbers}"})


def _engine(pack, values=None):
    port = InMemoryScheduling(settings=SchedulingSettings(), calendars=[], names={})
    ctx = FlowContext("C", "P", values={"clinic_phone": CLINIC_PHONE} if values is None else values)
    return FlowEngine(pack, port, ctx)


def test_engine_needs_the_clinic_phone():
    with pytest.raises(ValueError, match="clinic_phone"):
        _engine(load_pack_by_id("clinic"), values={})


def test_engine_rejects_an_emergency_message_without_the_numbers():
    pack = load_pack_by_id("clinic")
    messages = dict(pack.conversation.messages)
    messages["emergency"] = {**messages["emergency"], "hi": "कृपया क्लिनिक को कॉल करें।"}
    conversation = pack.conversation.model_copy(update={"messages": messages})
    with pytest.raises(ValueError, match="emergency"):
        _engine(pack.model_copy(update={"conversation": conversation}))
