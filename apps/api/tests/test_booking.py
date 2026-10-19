from datetime import UTC, datetime

import pytest

from salesbot_api.booking import overlaps, slot_for_service
from salesbot_core.packs import load_pack_by_id


def test_slot_uses_pack_service_duration():
    service = load_pack_by_id("dentist").service("root_canal")
    slot = slot_for_service(datetime(2026, 1, 1, 10, tzinfo=UTC), service.duration_minutes)
    assert (slot.ends_at - slot.starts_at).total_seconds() == 90 * 60


def test_overlap():
    a = slot_for_service(datetime(2026, 1, 1, 10, tzinfo=UTC), 60)
    b = slot_for_service(datetime(2026, 1, 1, 10, 30, tzinfo=UTC), 60)
    c = slot_for_service(datetime(2026, 1, 1, 11, tzinfo=UTC), 60)
    assert overlaps(a, b)
    assert not overlaps(a, c)  # back-to-back is fine


@pytest.mark.skip(reason="TODO: booking logic not built yet (business hours + calendar + DB)")
def test_find_free_slots_respects_hours_calendar_and_existing_appointments():
    raise NotImplementedError
