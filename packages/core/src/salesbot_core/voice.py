"""Voice channel helpers shared by the API tools (apps/api) and the agent generator
(salesbot_core.packs.render_agent). The voice platform is Sarvam Voice Agents; nothing here
calls it.

- Language codes <-> Sarvam language names ("Hindi").
- The API tools the Sarvam agent calls, as data: the generator turns them into cURL commands
  for the agent builder, and apps/api tests check its request models match.
- Spoken lines: every sentence a tool returns as `spoken_text` comes from the pack's
  `voice.messages`. Lines about a time always carry the weekday, date and time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from string import Formatter
from zoneinfo import ZoneInfo

from salesbot_core.packs import Pack
from salesbot_core.packs.schema import Language
from salesbot_core.text.formatting import long_date, time_label

SARVAM_LANGUAGE_NAMES: dict[Language, str] = {"en": "English", "hi": "Hindi", "mr": "Marathi"}
_BY_NAME = {name.casefold(): code for code, name in SARVAM_LANGUAGE_NAMES.items()}


def language_code(value: str | None) -> Language | None:
    """'hi', 'hi-IN', 'Hindi' -> 'hi'. None for anything we do not support."""
    if not value:
        return None
    v = value.strip().casefold()
    if v in _BY_NAME:
        return _BY_NAME[v]
    v = v.split("-")[0]
    return v if v in SARVAM_LANGUAGE_NAMES else None  # type: ignore[return-value]


# Spoken lines the tools need, with the placeholders each must contain. Lines about one time
# must have {date} and {time}; {date} is always "weekday, day month" (long_date).
VOICE_MESSAGES: dict[str, frozenset[str]] = {
    "identified": frozenset({"client_name"}),
    "identified_upcoming": frozenset({"client_name", "doctor", "date", "time"}),
    "choose_patient": frozenset({"names"}),
    "not_registered": frozenset(),
    "options": frozenset({"options"}),
    "option": frozenset({"date", "time", "doctor"}),
    "nothing_then": frozenset(),
    "no_openings": frozenset({"days"}),
    "held": frozenset({"doctor", "date", "time"}),
    "booked": frozenset({"doctor", "date", "time"}),
    "rescheduled": frozenset({"doctor", "date", "time"}),
    "reschedule_pending": frozenset({"date", "time"}),
    "cancel_ask": frozenset({"doctor", "date", "time"}),
    "cancelled": frozenset({"doctor", "date", "time"}),
    "confirmed": frozenset({"doctor", "date", "time"}),
    "no_upcoming": frozenset(),
    "slot_taken": frozenset({"date", "time"}),
    "hold_expired": frozenset(),
    "task_created": frozenset(),
    "task_created_urgent": frozenset({"emergency_numbers", "clinic_phone"}),
    "try_again": frozenset(),
}
TIME_MESSAGES = frozenset(k for k, need in VOICE_MESSAGES.items() if {"date", "time"} <= need)


def check_voice_pack(pack: Pack) -> None:
    """Raise ValueError unless the pack has every voice line with its placeholders, in every
    pack language."""
    if pack.voice is None:
        raise ValueError(f"pack {pack.id!r} has no voice section")
    for key, needed in VOICE_MESSAGES.items():
        localized = pack.voice.messages.get(key)
        if localized is None:
            raise ValueError(f"pack {pack.id!r}: voice.messages.{key} is missing")
        for language in pack.languages:
            text = localized.get(language)
            if text is None:
                raise ValueError(f"pack {pack.id!r}: voice.messages.{key} has no {language!r}")
            names = {n for _, n, _, _ in Formatter().parse(text) if n}
            if not needed <= names:
                raise ValueError(
                    f"pack {pack.id!r}: voice.messages.{key} ({language}) needs "
                    f"{sorted(needed - names)}"
                )


@dataclass(frozen=True)
class Spoken:
    text: str
    language: Language
    # DRAFT (unreviewed) text. Voice tests use the owner's team's phones only until reviewed.
    draft: bool


def say(pack: Pack, key: str, language: Language, **values: object) -> Spoken:
    if pack.voice is None:
        raise ValueError(f"pack {pack.id!r} has no voice section")
    localized = pack.voice.messages[key]
    lang: Language = language if language in localized else "en"
    return Spoken(
        text=localized[lang].format(**values),
        language=lang,
        draft=pack.is_draft(lang, f"voice.{key}"),
    )


def when(starts_at: datetime, tz: str, language: Language) -> dict[str, str]:
    """{date}, {time} for a spoken line, in the clinic's timezone (IST for Indian clinics)."""
    local = starts_at.astimezone(ZoneInfo(tz))
    return {"date": long_date(local.date(), language), "time": time_label(local, language)}


# ---------------------------------------------------------------------------
# The API tools, as data (docs/SARVAM_AGENT.md)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolField:
    name: str
    # Where the value comes from in the Sarvam tool builder:
    #   "context:<name>"  a call-context variable (User Identifier, Interaction ID, ...)
    #   "sarvam:<name>"   a Sarvam variable (language_name, ...)
    #   "var:<name>"      an agent variable (set by the on-start hook or a previous tool)
    #   "model"           chosen by the agent from the conversation
    source: str
    description: str
    required: bool = False
    example: object = None


COMMON_FIELDS: tuple[ToolField, ...] = (
    ToolField("clinic", "var:clinic_slug", "The clinic's id (set per agent).", True, "demo"),
    ToolField(
        "interaction_id",
        "context:Interaction ID",
        "Sarvam's id for this call.",
        True,
        "20261024/abc123",
    ),
    ToolField(
        "caller_phone",
        "context:User Identifier",
        "Caller's number (inbound).",
        example="+919000000001",
    ),
    ToolField("language", "sarvam:language_name", "Language of the call.", example="Hindi"),
)

_PATIENT = ToolField("patient_id", "var:patient_id", "Patient chosen for this call.", True)
_APPOINTMENT = ToolField(
    "appointment_id", "var:appointment_id", "The appointment being changed.", True
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    fields: tuple[ToolField, ...]
    # Agent variables to fill from the response ("Save reply into variables").
    saves: tuple[str, ...] = ()


VOICE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "identify_patient",
        "Find the registered patient for the caller's number. If several patients share the "
        "number, the reply lists them so you can ask which one the call is about.",
        (ToolField("patient_id", "model", "Set only to pick one of several candidates."),),
        saves=("patient_id", "patient_name", "appointment_id"),
    ),
    ToolSpec(
        "get_availability",
        "Free appointment times: on a date, in a part of the day, or the next available. "
        "Returns at most 3 options.",
        (
            _PATIENT,
            ToolField("date", "model", "Wanted date, YYYY-MM-DD.", example="2026-10-27"),
            ToolField("part_of_day", "model", "morning, afternoon or evening.", example="morning"),
            ToolField("next_available", "model", "true for the earliest times.", example=False),
            ToolField("for_reschedule", "model", "true when moving an appointment.", example=False),
        ),
    ),
    ToolSpec(
        "hold_slot",
        "Keep one offered time for a few minutes while the caller decides.",
        (
            _PATIENT,
            ToolField("starts_at", "model", "starts_at of the chosen option.", True),
            ToolField("practitioner_id", "model", "practitioner_id of the chosen option.", True),
        ),
        saves=("hold_id",),
    ),
    ToolSpec(
        "book",
        "Book the held time after the caller says yes. Only say it is booked when ok is true.",
        (_PATIENT, ToolField("hold_id", "var:hold_id", "From hold_slot.", True)),
        saves=("appointment_id",),
    ),
    ToolSpec(
        "reschedule",
        "Move the caller's appointment to a chosen option, after the caller agrees.",
        (
            _PATIENT,
            _APPOINTMENT,
            ToolField("starts_at", "model", "starts_at of the chosen option.", True),
            ToolField("practitioner_id", "model", "practitioner_id of the chosen option."),
        ),
        saves=("appointment_id",),
    ),
    ToolSpec(
        "cancel",
        "Cancel an appointment. First read it back and get a clear yes; then call with "
        "confirmed=true.",
        (
            _PATIENT,
            _APPOINTMENT,
            ToolField("confirmed", "model", "true only after the caller said yes.", True, True),
        ),
    ),
    ToolSpec(
        "confirm_attendance",
        "Record that the caller will come to their appointment.",
        (_PATIENT, _APPOINTMENT),
    ),
    ToolSpec(
        "create_staff_task",
        "Ask the clinic team to follow up: a callback, a question you cannot answer, a "
        "complaint, or an emergency (urgency=urgent).",
        (
            ToolField("patient_id", "var:patient_id", "If known."),
            ToolField(
                "reason",
                "model",
                "callback, emergency, question, reschedule, cancel, complaint or other.",
                True,
                "callback",
            ),
            ToolField("summary", "model", "One or two sentences for the clinic team.", True),
            ToolField("urgency", "model", "normal or urgent.", example="normal"),
        ),
    ),
)
