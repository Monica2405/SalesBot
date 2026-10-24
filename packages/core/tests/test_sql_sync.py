"""Python enums and defaults must match the SQL in supabase/migrations (the schema source).

Reads the newest definition of each constraint across all migration files, in file order.
"""

import re
from pathlib import Path

from salesbot_core.events import Channel, EventType, LeadSource
from salesbot_core.scheduling import BLOCKING_STATUSES, AppointmentStatus, SchedulingSettings

MIGRATIONS = sorted((Path(__file__).parents[3] / "supabase" / "migrations").glob("*.sql"))
SQL = "\n".join(p.read_text(encoding="utf-8") for p in MIGRATIONS)


def _last_in_list(pattern: str) -> set[str]:
    matches = re.findall(pattern, SQL, flags=re.S)
    assert matches, f"pattern not found: {pattern}"
    return set(re.findall(r"'([a-z_]+)'", matches[-1]))


def test_event_types_match_sql_check():
    sql = _last_in_list(r"events_type_check check \(type in \((.*?)\)\)")
    assert sql == {e.value for e in EventType}


def test_lead_sources_match_sql_domain():
    sql = _last_in_list(r"lead_source(?:_check)?\s+(?:as text\s+)?check \(value in \((.*?)\)\)")
    assert sql == {s.value for s in LeadSource}


def test_appointment_statuses_match_sql_check():
    sql = _last_in_list(r"appointments_status_check\s+check \(status in \((.*?)\)\)")
    assert sql == {s.value for s in AppointmentStatus}


def test_blocking_statuses_match_exclusion_constraint():
    sql = _last_in_list(
        r"appointments_no_overlap exclude using gist.*?where \(status in \((.*?)\)\)"
    )
    assert sql == {s.value for s in BLOCKING_STATUSES}


def test_channels_match_sql():
    sql = _last_in_list(r"add column channel\s+text check \(channel in \((.*?)\)\)")
    assert sql == {c.value for c in Channel}


def test_scheduling_defaults_match_sql_columns():
    defaults = SchedulingSettings()
    for column in ("hold_minutes", "min_lead_minutes", "lookahead_days", "days_per_list"):
        m = re.search(rf"\b{column}\s+integer not null default (\d+)", SQL)
        assert m, column
        assert int(m.group(1)) == getattr(defaults, column), column
    for column in ("practitioner_selection", "reschedule_approval"):
        m = re.search(rf"\b{column}\s+text not null default '([a-z_]+)'", SQL)
        assert m, column
        assert m.group(1) == getattr(defaults, column).value, column


def test_language_and_emergency_defaults_match_sql():
    defaults = SchedulingSettings()
    for column in ("allowed_languages", "emergency_numbers"):
        m = re.search(rf"\b{column}\s+text\[\] not null default '\{{([^}}]*)\}}'", SQL)
        assert m, column
        assert m.group(1).split(",") == getattr(defaults, column), column
    m = re.search(r"allowed_languages <@ array\[(.*?)\]", SQL)
    assert m
    assert set(re.findall(r"'([a-z]+)'", m.group(1))) == {"en", "hi", "mr"}
