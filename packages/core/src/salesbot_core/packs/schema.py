"""Industry pack schema.

A pack is pure configuration (YAML in packs/). The engine reads it and never contains
industry-specific logic. Adding a new industry should mean adding a YAML file, not code.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

Language = Literal["en", "hi", "mr"]


def _require_english(value: dict[Language, str]) -> dict[Language, str]:
    if "en" not in value:
        raise ValueError("localized text must include an 'en' fallback")
    return value


# Text in one or more languages. English is required as the fallback.
LocalizedText = Annotated[dict[Language, str], AfterValidator(_require_english)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntakeQuestion(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    prompt: LocalizedText
    type: Literal["text", "phone", "date", "choice", "service"] = "text"
    required: bool = True
    choices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _choices_for_choice(self) -> IntakeQuestion:
        if self.type == "choice" and not self.choices:
            raise ValueError(f"intake question '{self.key}' is type 'choice' but has no choices")
        return self


class Service(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: LocalizedText
    duration_minutes: int = Field(gt=0, le=480)
    # Indicative price for revenue estimates in the funnel (INR). Optional.
    price_inr: int | None = Field(default=None, ge=0)


class FAQ(_Strict):
    question: LocalizedText
    answer: LocalizedText
    keywords: list[str] = Field(default_factory=list)


class EmergencyConfig(_Strict):
    # Lower-cased phrases in any supported language. Matching is done by the engine.
    triggers: list[str] = Field(default_factory=list)
    action: Literal["handoff", "callback", "advise"] = "handoff"
    message: LocalizedText


class Pack(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    version: int = Field(ge=1)
    languages: list[Language] = Field(min_length=1)
    greeting: LocalizedText
    intake_questions: list[IntakeQuestion] = Field(min_length=1)
    services: list[Service] = Field(min_length=1)
    faqs: list[FAQ] = Field(default_factory=list)
    emergency: EmergencyConfig | None = None
    # Pack-specific CRM stages, in order. The generic funnel events live in salesbot_core.events.
    lead_stages: list[str] = Field(min_length=2)

    @model_validator(mode="after")
    def _unique_ids(self) -> Pack:
        for label, items in (
            ("intake question key", [q.key for q in self.intake_questions]),
            ("service id", [s.id for s in self.services]),
            ("lead stage", self.lead_stages),
        ):
            dupes = {x for x in items if items.count(x) > 1}
            if dupes:
                raise ValueError(f"duplicate {label}: {sorted(dupes)}")
        return self

    def service(self, service_id: str) -> Service:
        for s in self.services:
            if s.id == service_id:
                return s
        raise KeyError(service_id)
