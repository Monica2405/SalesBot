"""The generic receptionist engine. One engine for every industry: all behaviour that differs
between a dentist and a salon comes from the Pack.

Turn flow: disclosure + consent -> greeting -> intake questions (from the pack) -> lead captured.
An emergency trigger at any point after consent jumps to handoff (callback fallback).
Every step emits a funnel EventType so the call can be measured.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from salesbot_agent.consent import disclosure_text, parse_consent
from salesbot_agent.emergency import detect_emergency
from salesbot_agent.handoff import CALLBACK_MESSAGE, HandoffHandler
from salesbot_core.events import EventType, LeadSource
from salesbot_core.packs import Pack
from salesbot_core.packs.schema import Language
from salesbot_core.providers import ChatMessage, LLMProvider


class Stage(StrEnum):
    CONSENT = "consent"
    INTAKE = "intake"
    DONE = "done"


@dataclass
class CallContext:
    call_id: str
    business_name: str
    language: Language = "en"
    source: LeadSource = LeadSource.UNKNOWN
    script_version_id: str | None = None
    # Business values substituted into pack text, e.g. {business_hours}
    business_values: dict[str, str] = field(default_factory=dict)


@dataclass
class Usage:
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0


@dataclass
class AgentTurn:
    say: str
    events: list[EventType] = field(default_factory=list)
    end_call: bool = False


class Receptionist:
    def __init__(
        self, pack: Pack, llm: LLMProvider, handoff: HandoffHandler, ctx: CallContext
    ) -> None:
        self.pack = pack
        self.llm = llm
        self.handoff = handoff
        self.ctx = ctx
        self.stage = Stage.CONSENT
        self.consent_recording = False
        self.answers: dict[str, str] = {}
        self.usage = Usage()
        self._question_index = 0

    def _t(self, localized: dict[Language, str]) -> str:
        text = localized.get(self.ctx.language) or localized["en"]
        values = defaultdict(str, business_name=self.ctx.business_name, **self.ctx.business_values)
        return text.format_map(values)

    def opening(self) -> AgentTurn:
        return AgentTurn(
            say=disclosure_text(self.ctx.language, self.ctx.business_name),
            events=[EventType.CALL_RECEIVED, EventType.CALL_ANSWERED],
        )

    async def on_user_utterance(self, text: str) -> AgentTurn:
        if self.stage is Stage.CONSENT:
            return self._handle_consent(text)
        if self.stage is Stage.DONE:
            return AgentTurn(say="", end_call=True)

        if self.pack.emergency is not None and detect_emergency(self.pack, text):
            return await self._handle_emergency(text, self.pack.emergency.message)
        return await self._handle_intake(text)

    def _handle_consent(self, text: str) -> AgentTurn:
        self.consent_recording = parse_consent(text) is True
        event = EventType.CONSENT_GIVEN if self.consent_recording else EventType.CONSENT_DECLINED
        self.stage = Stage.INTAKE
        say = f"{self._t(self.pack.greeting)} {self._t(self._current_question().prompt)}"
        return AgentTurn(say=say, events=[event])

    async def _handle_emergency(self, text: str, message: dict[Language, str]) -> AgentTurn:
        events = [EventType.EMERGENCY_DETECTED, EventType.HANDOFF_REQUESTED]
        result = await self.handoff.request(self.ctx.call_id, reason=f"emergency: {text}")
        say = self._t(message)
        if not result.connected:
            events.append(EventType.CALLBACK_REQUESTED)
            say = f"{say} {self._t(CALLBACK_MESSAGE)}"
        self.stage = Stage.DONE
        return AgentTurn(say=say, events=events, end_call=True)

    async def _handle_intake(self, text: str) -> AgentTurn:
        self.answers[self._current_question().key] = text.strip()
        self._question_index += 1
        if self._question_index < len(self.pack.intake_questions):
            return AgentTurn(say=self._t(self._current_question().prompt))

        self.stage = Stage.DONE
        closing = await self.llm.complete(
            [
                ChatMessage(role="system", content=self._system_prompt()),
                ChatMessage(role="user", content=", ".join(self.answers.values())),
            ]
        )
        self.usage.llm_tokens_in += closing.tokens_in
        self.usage.llm_tokens_out += closing.tokens_out
        return AgentTurn(say=closing.text, events=[EventType.LEAD_CAPTURED], end_call=True)

    def _current_question(self):
        return self.pack.intake_questions[self._question_index]

    def _system_prompt(self) -> str:
        # TODO: versioned prompt from script_versions; include pack FAQs and knowledge_items.
        return (
            f"You are the receptionist for {self.ctx.business_name} ({self.pack.name}). "
            f"Reply in language '{self.ctx.language}'. Confirm the caller's details briefly."
        )
