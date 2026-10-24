"""Cost estimates and spend caps (docs/COSTS.md)."""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from salesbot_core.costs import (
    SpendCapReachedError,
    call_cost,
    check_spend_caps,
    load_rates,
    max_call_cost,
    pulses,
    whatsapp_cost,
)

COSTS_MD = Path(__file__).parents[3] / "docs" / "COSTS.md"


@pytest.mark.parametrize(
    ("seconds", "minutes", "telephony"),
    [
        (None, 0, 0),
        (0, 0, 0),
        (1, 1, 1),
        (30, 1, 1),
        (31, 1, 2),
        (45, 1, 2),
        (60, 1, 2),
        (61, 2, 3),
        (600, 10, 20),
    ],
)
def test_pulses_round_up(seconds, minutes, telephony):
    assert pulses(seconds, 60) == minutes
    assert pulses(seconds, 30) == telephony


def test_sarvam_worked_example_45_seconds_is_rs_3_90():
    # docs.sarvam.ai/voice-agents/pricing: 1 agent minute + 2 pulses on pay as you go
    cost = call_cost(45)
    assert (cost.agent_minutes, cost.telephony_pulses, cost.inr) == (1, 2, Decimal("3.90"))


def test_61_seconds_is_two_agent_minutes():
    assert call_cost(61).inr == Decimal("7.60")  # 2 x 3.50 + 3 x 0.20


def test_forwarded_leg_is_billed_as_forwarding_pulses_only():
    # Pricing page: hand over after 50 s, forwarded call lasts 2 min -> 1 agent minute and
    # 4 forwarding pulses (Rs 1.60 to a phone number), plus our 2 telephony pulses.
    cost = call_cost(50, forwarded_seconds=120)
    assert (cost.agent_minutes, cost.forwarding_pulses) == (1, 4)
    assert cost.inr == Decimal("3.50") + Decimal("0.40") + Decimal("1.60")


def test_unanswered_call_costs_nothing():
    assert call_cost(0).inr == Decimal("0.00")


def test_bring_your_own_telephony_has_no_sarvam_telephony_charge():
    assert call_cost(45, telephony="byo").inr == Decimal("3.50")


def test_max_call_cost_for_ten_minutes():
    assert max_call_cost(600) == Decimal("39.00")  # 10 x 3.50 + 20 x 0.20


def test_whatsapp_cost_by_category():
    assert whatsapp_cost({"utility": 4, "service": 10}) == Decimal("0.46")
    with pytest.raises(KeyError):
        whatsapp_cost({"unknown": 1})


def test_rates_file_matches_costs_doc():
    rates = load_rates()
    doc = COSTS_MD.read_text(encoding="utf-8")
    assert rates.voice.agent_rate == Decimal("3.50")
    assert f"rates.yaml last_verified: {rates.last_verified.isoformat()}" in doc
    for figure in ("3.50", "3.25", "3.15", "0.20", "0.40", "0.35", "59", "0.115", "0.8631"):
        assert re.search(rf"₹{re.escape(figure)}\b", doc), figure


CAPS = {"session_cap": Decimal(100), "day_cap": Decimal(500)}


def test_caps_allow_spend_up_to_the_cap():
    check_spend_caps(needed=Decimal(39), session_used=Decimal(61), day_used=Decimal(0), **CAPS)


def test_session_cap_blocks_with_a_clear_message():
    with pytest.raises(SpendCapReachedError) as exc:
        check_spend_caps(needed=Decimal(39), session_used=Decimal(62), day_used=Decimal(0), **CAPS)
    assert exc.value.scope == "session"
    assert "SPEND_SESSION_CAP_INR" in str(exc.value) and "Nothing was started" in str(exc.value)


def test_daily_cap_blocks():
    with pytest.raises(SpendCapReachedError) as exc:
        check_spend_caps(needed=Decimal(2), session_used=Decimal(0), day_used=Decimal(499), **CAPS)
    assert exc.value.scope == "day"
    assert "SPEND_DAILY_CAP_INR" in str(exc.value)
