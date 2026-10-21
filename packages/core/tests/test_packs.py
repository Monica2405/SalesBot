import pytest
from pydantic import ValidationError

from salesbot_core.events import FUNNEL, EventType
from salesbot_core.packs import Pack, load_all_packs, load_pack_by_id


def test_all_shipped_packs_validate():
    packs = load_all_packs()
    assert {"dentist", "salon"} <= packs.keys()


def test_dentist_pack_has_emergency_and_salon_does_not():
    assert load_pack_by_id("dentist").emergency is not None
    assert load_pack_by_id("salon").emergency is None


def test_service_lookup():
    pack = load_pack_by_id("dentist")
    assert pack.service("root_canal").duration_minutes == 90
    with pytest.raises(KeyError):
        pack.service("haircut")


def _minimal(**overrides):
    data = {
        "id": "demo",
        "name": "Demo",
        "version": 1,
        "languages": ["en"],
        "greeting": {"en": "Hi"},
        "intake_questions": [{"key": "name", "prompt": {"en": "Name?"}}],
        "services": [{"id": "x", "name": {"en": "X"}, "duration_minutes": 10}],
        "lead_stages": ["new", "won"],
    }
    data.update(overrides)
    return data


def test_minimal_pack_is_valid():
    Pack.model_validate(_minimal())


def test_localized_text_requires_english():
    with pytest.raises(ValidationError, match="'en' fallback"):
        Pack.model_validate(_minimal(greeting={"hi": "नमस्ते"}))


def test_duplicate_service_ids_rejected():
    svc = {"id": "x", "name": {"en": "X"}, "duration_minutes": 10}
    with pytest.raises(ValidationError, match="duplicate service id"):
        Pack.model_validate(_minimal(services=[svc, svc]))


def test_unknown_keys_rejected():
    with pytest.raises(ValidationError):
        Pack.model_validate(_minimal(dentist_only_field=True))


def test_funnel_order():
    assert FUNNEL[0] is EventType.CALL_RECEIVED
    assert FUNNEL[-1] is EventType.PAYMENT_RECORDED
