from datetime import time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from salesbot_core.scheduling import SchedulingSettings
from salesbot_core.scheduling.settings import LocalWindow


def test_defaults_are_the_approved_values():
    s = SchedulingSettings()
    assert (s.hold_minutes, s.min_lead_minutes, s.lookahead_days, s.days_per_list) == (5, 60, 14, 9)
    assert s.practitioner_selection == "any_available"
    assert s.reschedule_approval == "auto"
    assert [r.hours_before for r in s.reminder_policy.reminders] == [24, 2]
    assert s.reminder_policy.quiet_hours == LocalWindow(start=time(21), end=time(8))
    assert s.call_policy.window == LocalWindow(start=time(9), end=time(19))
    assert (s.call_policy.max_attempts, s.call_policy.retry_spacing_minutes) == (3, 60)
    assert s.confirmation_policy.nudge_after_hours == 6
    assert s.confirmation_policy.final_attempt_hours_before == 24


def test_empty_db_json_means_defaults():
    s = SchedulingSettings.model_validate(
        {"confirmation_policy": {}, "reminder_policy": {}, "call_policy": None}
    )
    assert s.reminder_policy == SchedulingSettings().reminder_policy


def test_policies_are_per_business():
    s = SchedulingSettings.model_validate(
        {
            "reminder_policy": {
                "reminders": [{"hours_before": 48, "channels": ["whatsapp", "call"]}],
                "quiet_hours": None,
            }
        }
    )
    assert s.reminder_policy.reminders[0].channels == ["whatsapp", "call"]
    assert s.reminder_policy.quiet_hours is None


def test_outbound_calls_cannot_be_enabled_before_stage_g():
    with pytest.raises(ValidationError):
        SchedulingSettings.model_validate({"call_policy": {"outbound_enabled": True}})


def test_default_practitioner_needs_an_id():
    with pytest.raises(ValidationError):
        SchedulingSettings(practitioner_selection="default_practitioner")
    SchedulingSettings(
        practitioner_selection="default_practitioner", default_practitioner_id=uuid4()
    )


def test_quiet_hours_wrap_past_midnight():
    quiet = LocalWindow(start=time(21), end=time(8))
    assert quiet.contains(time(22)) and quiet.contains(time(7, 59)) and quiet.contains(time(21))
    assert not quiet.contains(time(8)) and not quiet.contains(time(12))


def test_unknown_policy_keys_are_rejected():
    with pytest.raises(ValidationError):
        SchedulingSettings.model_validate({"call_policy": {"max_attempt": 3}})
