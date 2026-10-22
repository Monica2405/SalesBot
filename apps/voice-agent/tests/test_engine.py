import pytest

from salesbot_agent.consent import parse_consent
from salesbot_agent.emergency import detect_emergency
from salesbot_agent.engine import CallContext, Receptionist, Stage
from salesbot_agent.handoff import StubHandoff
from salesbot_agent.providers.llm import MockLLM
from salesbot_core.events import EventType
from salesbot_core.packs import load_pack_by_id


def make_engine(pack_id: str = "dentist", language: str = "en") -> Receptionist:
    return Receptionist(
        pack=load_pack_by_id(pack_id),
        llm=MockLLM(),
        handoff=StubHandoff(),
        ctx=CallContext(call_id="t-1", business_name="Test Clinic", language=language),
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("yes", True),
        ("Okay.", True),
        ("हाँ", True),
        ("चालेल", True),
        ("no", False),
        ("नहीं", False),
        ("नको", False),
        ("what?", None),
    ],
)
def test_parse_consent(answer, expected):
    assert parse_consent(answer) is expected


def test_opening_names_the_business_and_asks_consent():
    turn = make_engine().opening()
    assert "recorded" in turn.say
    assert "Test Clinic" in turn.say
    assert turn.events == [EventType.CALL_RECEIVED, EventType.CALL_ANSWERED]


async def test_unclear_consent_means_no_recording():
    engine = make_engine()
    turn = await engine.on_user_utterance("hmm")
    assert engine.consent_recording is False
    assert turn.events == [EventType.CONSENT_DECLINED]
    assert engine.stage is Stage.INTAKE


async def test_full_intake_captures_lead_for_any_pack():
    for pack_id in ("dentist", "salon"):
        engine = make_engine(pack_id)
        await engine.on_user_utterance("yes")
        turn = None
        for _ in engine.pack.intake_questions:
            turn = await engine.on_user_utterance("answer")
        assert turn.end_call
        assert EventType.LEAD_CAPTURED in turn.events
        assert set(engine.answers) == {q.key for q in engine.pack.intake_questions}
        assert engine.usage.llm_tokens_in > 0


async def test_greeting_in_marathi():
    engine = make_engine(language="mr")
    turn = await engine.on_user_utterance("हो")
    assert "Test Clinic" in turn.say and "नमस्कार" in turn.say


def test_emergency_triggers_come_from_pack():
    assert detect_emergency(load_pack_by_id("dentist"), "I have SEVERE PAIN") == "severe pain"
    assert detect_emergency(load_pack_by_id("dentist"), "खूप दुखतंय हो") is not None
    assert detect_emergency(load_pack_by_id("salon"), "severe pain") is None


async def test_emergency_falls_back_to_callback_when_handoff_unavailable():
    engine = make_engine()
    await engine.on_user_utterance("yes")
    turn = await engine.on_user_utterance("there is a lot of bleeding")
    assert turn.end_call
    assert turn.events == [
        EventType.EMERGENCY_DETECTED,
        EventType.HANDOFF_REQUESTED,
        EventType.CALLBACK_REQUESTED,
    ]
    assert engine.handoff.requests  # handoff was attempted


def test_fixed_voice_lines_pass_the_wording_scan():
    from salesbot_agent.consent import OPENING
    from salesbot_agent.handoff import CALLBACK_MESSAGE
    from salesbot_core.text.wording import forbidden_terms

    for table in (OPENING, CALLBACK_MESSAGE):
        for language, text in table.items():
            assert forbidden_terms(text) == [], (language, text)
