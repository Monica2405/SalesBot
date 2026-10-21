"""Pipecat wiring.

Target pipeline for a live call:
    transport.input() -> STT -> ReceptionistProcessor -> TTS -> transport.output()

Today only the ReceptionistProcessor is real. TODO once providers are decided:
- transport: telephony provider's media stream (Plivo/Exotel, open decision) or browser WebRTC
- STT/TTS: wrap our STTProvider/TTSProvider as Pipecat services (or use Pipecat's own
  Sarvam services if they match docs.sarvam.ai), keeping usage numbers for cost tracking
- enforce CALL_MAX_SECONDS and the business usage cap
"""

from __future__ import annotations

from pipecat.frames.frames import EndWorkerFrame, Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from salesbot_agent.engine import AgentTurn, Receptionist
from salesbot_core.events import EventType


class ReceptionistProcessor(FrameProcessor):
    """Turns final user transcriptions into agent speech using the generic engine."""

    def __init__(self, engine: Receptionist) -> None:
        super().__init__()
        self.engine = engine
        self.events: list[EventType] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            await self._speak(await self.engine.on_user_utterance(frame.text))
        else:
            await self.push_frame(frame, direction)

    async def say_opening(self) -> None:
        await self._speak(self.engine.opening())

    async def _speak(self, turn: AgentTurn) -> None:
        # TODO: persist turn.events to the `events` table (via apps/api or a DB writer).
        self.events.extend(turn.events)
        if turn.say:
            await self.push_frame(TTSSpeakFrame(turn.say))
        if turn.end_call:
            await self.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)


def build_pipeline(engine: Receptionist) -> tuple[Pipeline, ReceptionistProcessor]:
    receptionist = ReceptionistProcessor(engine)
    return Pipeline([receptionist]), receptionist
