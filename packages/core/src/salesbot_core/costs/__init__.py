"""Cost estimates in rupees, from the rate card in rates.yaml (docs/COSTS.md is the source).

Sarvam bills a voice call as agent minutes (60-second pulses, rounded up) plus telephony
pulses (30-second pulses, rounded up). Its end-of-call payloads report only the duration in
seconds, so both counts are derived from it here. Calls that never connect cost nothing.

The spend caps (`check_spend_caps`) protect the shared Sarvam credit wallet: anything we start
that spends credits (outbound calls, simulated test runs) must fit the session and daily caps.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

RATES_FILE = Path(__file__).with_name("rates.yaml")
PAISE = Decimal("0.01")

Plan = Literal["pay_as_you_go", "pro", "growth", "business"]
Telephony = Literal["sarvam", "byo"]
Forwarding = Literal["pstn", "sip"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VoiceRates(_Strict):
    plan: Plan
    agent_rate_per_minute: dict[Plan, Decimal]
    agent_pulse_seconds: int
    telephony_pulse_seconds: int
    telephony_rate_per_pulse: dict[Telephony, Decimal]
    forwarding_rate_per_pulse: dict[Forwarding, Decimal]
    number_rental_per_30_days: Decimal
    simulated_test_run: Decimal

    @property
    def agent_rate(self) -> Decimal:
        return self.agent_rate_per_minute[self.plan]


class WhatsAppRates(_Strict):
    per_message: dict[str, Decimal]


class Rates(_Strict):
    last_verified: date
    sources: list[str]
    voice: VoiceRates
    whatsapp: WhatsAppRates


@lru_cache
def load_rates(path: Path = RATES_FILE) -> Rates:
    return Rates.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def pulses(seconds: float | None, pulse_seconds: int) -> int:
    """Whole pulses, rounded up. 0 for a call that never connected."""
    if not seconds or seconds <= 0:
        return 0
    return math.ceil(seconds / pulse_seconds)


class CallCost(_Strict):
    agent_minutes: int
    telephony_pulses: int
    forwarding_pulses: int
    inr: Decimal
    rates_verified_on: date


def call_cost(
    duration_seconds: float | None,
    *,
    telephony: Telephony = "sarvam",
    forwarded_seconds: float | None = None,
    forwarding: Forwarding = "pstn",
    rates: Rates | None = None,
) -> CallCost:
    """Estimated cost of one call. `duration_seconds` is the agent's part of the call; a
    forwarded leg is billed as forwarding pulses only (docs.sarvam.ai/voice-agents/pricing)."""
    r = (rates or load_rates()).voice
    minutes = pulses(duration_seconds, r.agent_pulse_seconds)
    tel = pulses(duration_seconds, r.telephony_pulse_seconds)
    fwd = pulses(forwarded_seconds, r.telephony_pulse_seconds)
    inr = (
        minutes * r.agent_rate
        + tel * r.telephony_rate_per_pulse[telephony]
        + fwd * r.forwarding_rate_per_pulse[forwarding]
    )
    return CallCost(
        agent_minutes=minutes,
        telephony_pulses=tel,
        forwarding_pulses=fwd,
        inr=inr.quantize(PAISE, ROUND_HALF_UP),
        rates_verified_on=(rates or load_rates()).last_verified,
    )


def max_call_cost(max_seconds: int, *, rates: Rates | None = None) -> Decimal:
    """What one call can cost at most (it is cut off at the max call length). Reserved
    against the spend caps before an outbound call is placed."""
    return call_cost(max_seconds, rates=rates).inr


def whatsapp_cost(counts: dict[str, int], *, rates: Rates | None = None) -> Decimal:
    """Messages by Meta pricing category, e.g. {"utility": 3}. Unknown categories raise."""
    per = (rates or load_rates()).whatsapp.per_message
    total = sum((per[category] * n for category, n in counts.items()), Decimal(0))
    return total.quantize(PAISE, ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Spend caps
# ---------------------------------------------------------------------------


class SpendKind(StrEnum):
    """Matches spend_ledger.kind."""

    OUTBOUND_CALL = "outbound_call"
    INBOUND_CALL = "inbound_call"
    TEST_RUN = "test_run"


class SpendCapReachedError(Exception):
    """Raised before an action that would pass a spend cap. The message is safe to show."""

    def __init__(
        self, scope: Literal["session", "day"], used: Decimal, cap: Decimal, needed: Decimal
    ) -> None:
        self.scope, self.used, self.cap, self.needed = scope, used, cap, needed
        setting = "SPEND_SESSION_CAP_INR" if scope == "session" else "SPEND_DAILY_CAP_INR"
        window = "this session" if scope == "session" else "today (IST)"
        super().__init__(
            f"Spend cap reached: Rs {used} of Rs {cap} already used {window}, and this needs "
            f"up to Rs {needed}. Nothing was started. Raise {setting} or wait for "
            f"{'a new session' if scope == 'session' else 'tomorrow'}."
        )


def check_spend_caps(
    *,
    needed: Decimal,
    session_used: Decimal,
    day_used: Decimal,
    session_cap: Decimal,
    day_cap: Decimal,
) -> None:
    """Raise SpendCapReachedError if `needed` more would pass either cap."""
    if session_used + needed > session_cap:
        raise SpendCapReachedError("session", session_used, session_cap, needed)
    if day_used + needed > day_cap:
        raise SpendCapReachedError("day", day_used, day_cap, needed)
