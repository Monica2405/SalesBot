"""Voice lines, language names and the Sarvam agent generator (render_agent)."""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from salesbot_core.packs import load_all_packs
from salesbot_core.packs.render_agent import BEGIN, END, render
from salesbot_core.text.formatting import _MONTHS, _WEEKDAYS
from salesbot_core.text.wording import forbidden_terms, forbidden_terms_except
from salesbot_core.voice import (
    COMMON_FIELDS,
    TIME_MESSAGES,
    VOICE_MESSAGES,
    VOICE_TOOLS,
    check_voice_pack,
    language_code,
    say,
    when,
)

DOC = Path(__file__).parents[3] / "docs" / "SARVAM_AGENT.md"
PACK = load_all_packs()["clinic"]
IST = ZoneInfo("Asia/Kolkata")
# Monday 26 October 2026, 17:30 IST
MOMENT = datetime(2026, 10, 26, 17, 30, tzinfo=IST)


def test_clinic_pack_has_every_voice_line():
    check_voice_pack(PACK)


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
@pytest.mark.parametrize("key", sorted(TIME_MESSAGES))
def test_time_lines_say_weekday_date_and_time_in_ist(key, language):
    values = {name: "X" for name in VOICE_MESSAGES[key]}
    values.update(when(MOMENT.astimezone(ZoneInfo("UTC")), "Asia/Kolkata", language))
    text = say(PACK, key, language, **values).text
    assert _WEEKDAYS[language][0] in text  # Monday
    assert "26" in text and _MONTHS[language][9] in text  # 26 October
    assert "5:30" in text  # IST, 12-hour clock, not the UTC hour 12:00
    if language == "en":
        assert "5:30 pm" in text


@pytest.mark.parametrize("language", ["hi", "mr"])
def test_hindi_and_marathi_voice_lines_are_draft(language):
    assert say(PACK, "booked", language, doctor="D", date="d", time="t").draft
    assert not say(PACK, "booked", "en", doctor="D", date="d", time="t").draft


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("Hindi", "hi"),
        ("hindi", "hi"),
        ("hi-IN", "hi"),
        ("English", "en"),
        ("mr", "mr"),
        ("Tamil", None),
        ("", None),
        (None, None),
    ],
)
def test_language_codes(value, code):
    assert language_code(value) == code


def test_tool_names_and_fields_are_unique():
    names = [t.name for t in VOICE_TOOLS]
    assert len(names) == len(set(names)) == 8
    for tool in VOICE_TOOLS:
        fields = [f.name for f in (*COMMON_FIELDS, *tool.fields)]
        assert len(fields) == len(set(fields)), tool.name


# ---------------------------------------------------------------------------
# Generated agent setup
# ---------------------------------------------------------------------------

RENDERED = render(PACK)


def test_generated_text_passes_the_word_scan():
    allowed = list(RENDERED.sincere_ask.values())
    for text in RENDERED.texts_to_scan():
        assert forbidden_terms_except(text, allowed) == []


def test_only_the_sincere_ask_lines_are_allowlisted():
    # The sincere-ask answer does mention automation, which is why it is the one exception.
    assert forbidden_terms(RENDERED.sincere_ask["en"])
    assert forbidden_terms(RENDERED.instruction)  # it quotes the sincere-ask line
    # Anything else that slips into the instruction is caught.
    assert forbidden_terms_except(
        RENDERED.instruction + " I am an AI.", list(RENDERED.sincere_ask.values())
    )


def test_instruction_names_every_tool_and_the_emergency_numbers():
    for tool in VOICE_TOOLS:
        assert tool.name in RENDERED.instruction
    assert "{{emergency_numbers}}" in RENDERED.instruction
    assert "{{clinic_phone}}" in RENDERED.instruction


def test_no_unfilled_pack_placeholders():
    for text in [
        RENDERED.instruction,
        *RENDERED.greetings.values(),
        *RENDERED.sincere_ask.values(),
    ]:
        assert not re.search(r"(?<!\{)\{[a-z_]+\}(?!\})", text), text


def test_draft_items_are_listed():
    assert "sincere-ask answer" in RENDERED.draft
    assert any("emergency" in d for d in RENDERED.draft)


def test_sarvam_agent_doc_has_the_current_generated_block():
    doc = DOC.read_text(encoding="utf-8")
    start = doc.index(BEGIN.format(pack="clinic"))
    end = doc.index(END, start) + len(END)
    assert doc[start:end] + "\n" == RENDERED.markdown(), (
        "docs/SARVAM_AGENT.md is out of date: run `make voice-agent PACK=clinic` and paste "
        "the output between the BEGIN/END markers"
    )
