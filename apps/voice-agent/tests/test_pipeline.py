from pipecat.frames.frames import EndWorkerFrame, TranscriptionFrame, TTSSpeakFrame
from pipecat.tests.utils import run_test

from salesbot_agent.engine import CallContext, Receptionist
from salesbot_agent.handoff import StubHandoff
from salesbot_agent.pipeline import ReceptionistProcessor
from salesbot_agent.providers.llm import MockLLM
from salesbot_core.events import EventType
from salesbot_core.packs import load_pack_by_id


def _transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="0")


async def test_transcription_becomes_speech():
    engine = Receptionist(
        load_pack_by_id("dentist"), MockLLM(), StubHandoff(), CallContext("p-1", "Test Clinic")
    )
    processor = ReceptionistProcessor(engine)
    await run_test(
        processor,
        frames_to_send=[_transcription("yes")],
        expected_down_frames=[TTSSpeakFrame],
    )
    assert processor.events == [EventType.CONSENT_GIVEN]


async def test_emergency_ends_the_call_through_pipecat():
    engine = Receptionist(
        load_pack_by_id("dentist"), MockLLM(), StubHandoff(), CallContext("p-2", "Test Clinic")
    )
    processor = ReceptionistProcessor(engine)
    await run_test(
        processor,
        frames_to_send=[_transcription("yes"), _transcription("my tooth is bleeding")],
        expected_down_frames=[TTSSpeakFrame, TTSSpeakFrame],
        expected_up_frames=[EndWorkerFrame],
    )
