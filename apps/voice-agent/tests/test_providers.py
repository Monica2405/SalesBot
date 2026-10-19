import pytest

from salesbot_agent.providers.llm import MockLLM, get_llm
from salesbot_agent.providers.stt import MockSTT, SarvamSTT, get_stt
from salesbot_agent.providers.telephony import get_telephony
from salesbot_agent.providers.tts import MockTTS, get_tts
from salesbot_core.providers import ChatMessage


async def test_mock_stt_reports_audio_seconds():
    t = await MockSTT().transcribe(b"x" * 32000)
    assert t.audio_seconds == 1.0


async def test_mock_llm_reports_tokens():
    r = await MockLLM().complete([ChatMessage(role="user", content="book a cleaning")])
    assert r.tokens_in == 3 and r.tokens_out > 0


async def test_mock_tts_counts_characters():
    assert (await MockTTS().synthesize("hello", "en")).characters == 5


def test_factories_default_to_mocks():
    assert get_stt("mock").name == get_llm("mock").name == get_tts("mock").name == "mock"


def test_sarvam_requires_key():
    with pytest.raises(ValueError, match="SARVAM_API_KEY"):
        get_stt("sarvam")


async def test_sarvam_stub_is_not_silently_used():
    with pytest.raises(NotImplementedError, match=r"docs\.sarvam\.ai"):
        await SarvamSTT("fake").transcribe(b"")


def test_undecided_telephony_providers_are_not_built():
    assert get_telephony("mock").name == "mock"
    assert get_telephony("browser").name == "browser"
    for provider in ("plivo", "exotel"):
        with pytest.raises(NotImplementedError, match="open decision"):
            get_telephony(provider)
