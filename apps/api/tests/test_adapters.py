from datetime import UTC, datetime
from uuid import uuid4

import pytest

from salesbot_api.adapters.calendar import MockCalendar, TimeSlot
from salesbot_api.adapters.crm import CRMContact, NoopCRM, get_crm
from salesbot_api.adapters.messaging import MockMessaging, OutboundMessage, get_messaging
from salesbot_api.settings import Settings


async def test_mock_calendar_round_trip():
    cal, bid = MockCalendar(), uuid4()
    slot = TimeSlot(
        starts_at=datetime(2026, 1, 1, 10, tzinfo=UTC), ends_at=datetime(2026, 1, 1, 11, tzinfo=UTC)
    )
    event_id = await cal.create_event(bid, slot, "Cleaning")
    assert await cal.busy_slots(bid, slot.starts_at, slot.ends_at) == [slot]
    assert await cal.busy_slots(uuid4(), slot.starts_at, slot.ends_at) == []  # other business
    await cal.cancel_event(bid, event_id)
    assert await cal.busy_slots(bid, slot.starts_at, slot.ends_at) == []


async def test_mock_messaging_records_sends():
    m = get_messaging("mock")
    assert isinstance(m, MockMessaging)
    await m.send(OutboundMessage(to="+919999999999", text="See you tomorrow"))
    assert len(m.sent) == 1


async def test_crm_is_noop_when_hubspot_disabled():
    crm = get_crm(Settings(_env_file=None))
    assert isinstance(crm, NoopCRM)
    contact = CRMContact(lead_id=uuid4(), business_id=uuid4(), stage="new", source="unknown")
    assert await crm.upsert_contact(contact) is None


def test_crm_enabled_without_token_fails_loudly():
    with pytest.raises(ValueError, match="HUBSPOT_ACCESS_TOKEN"):
        get_crm(Settings(_env_file=None, hubspot_enabled=True))
