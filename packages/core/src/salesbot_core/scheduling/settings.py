"""Per-business scheduling settings (table scheduling_settings).

Defaults are the values the owner approved (docs/DECISIONS.md). Column defaults in
supabase/migrations must match the scalar defaults here. The jsonb policy columns are stored
as `{}` by default and filled from these models when read.
"""

from __future__ import annotations

from datetime import time, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from salesbot_core.packs.schema import Language

Channel = Literal["whatsapp", "call"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PractitionerSelection(StrEnum):
    ANY_AVAILABLE = "any_available"
    DEFAULT_PRACTITIONER = "default_practitioner"


class RescheduleApproval(StrEnum):
    AUTO = "auto"
    STAFF = "staff"


class LocalWindow(_Strict):
    """Wall-clock window in the business timezone. start > end wraps past midnight."""

    start: time
    end: time

    def contains(self, t: time) -> bool:
        if self.start <= self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end


class ConfirmationPolicy(_Strict):
    request_channels: list[Channel] = Field(default_factory=lambda: ["whatsapp"], min_length=1)
    nudge_after_hours: int | None = Field(default=6, ge=1, le=72)
    nudge_channels: list[Channel] = Field(default_factory=lambda: ["whatsapp"])
    final_attempt_hours_before: int | None = Field(default=24, ge=1, le=168)
    final_attempt_channels: list[Channel] = Field(default_factory=lambda: ["call"])
    staff_task_when_unconfirmed: bool = True


class Reminder(_Strict):
    hours_before: int = Field(ge=1, le=336)
    channels: list[Channel] = Field(min_length=1)


class ReminderPolicy(_Strict):
    reminders: list[Reminder] = Field(
        default_factory=lambda: [
            Reminder(hours_before=24, channels=["whatsapp"]),
            Reminder(hours_before=2, channels=["whatsapp"]),
        ]
    )
    quiet_hours: LocalWindow | None = Field(
        default_factory=lambda: LocalWindow(start=time(21, 0), end=time(8, 0))
    )


class CallPolicy(_Strict):
    # Outbound calls are blocked until the telephony decision (Stage G).
    outbound_enabled: Literal[False] = False
    window: LocalWindow = Field(
        default_factory=lambda: LocalWindow(start=time(9, 0), end=time(19, 0))
    )
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_spacing_minutes: int = Field(default=60, ge=5, le=1440)


class SchedulingSettings(_Strict):
    hold_minutes: int = Field(default=5, ge=1, le=60)
    min_lead_minutes: int = Field(default=60, ge=0, le=10080)
    lookahead_days: int = Field(default=14, ge=1, le=180)
    days_per_list: int = Field(default=9, ge=1, le=9)
    slot_step_minutes: int | None = Field(default=None, ge=5, le=240)
    practitioner_selection: PractitionerSelection = PractitionerSelection.ANY_AVAILABLE
    default_practitioner_id: UUID | None = None
    reschedule_approval: RescheduleApproval = RescheduleApproval.AUTO
    confirmation_policy: ConfirmationPolicy = Field(default_factory=ConfirmationPolicy)
    reminder_policy: ReminderPolicy = Field(default_factory=ReminderPolicy)
    call_policy: CallPolicy = Field(default_factory=CallPolicy)
    # From businesses.default_language; the fallback when a client's language is unsupported.
    default_language: Language = "en"
    timezone: str = "Asia/Kolkata"

    @field_validator("confirmation_policy", "reminder_policy", "call_policy", mode="before")
    @classmethod
    def _empty_json_is_default(cls, value: Any) -> Any:
        # The DB stores '{}' until a business customises a policy.
        return {} if value is None else value

    @model_validator(mode="after")
    def _default_practitioner(self) -> SchedulingSettings:
        if (
            self.practitioner_selection is PractitionerSelection.DEFAULT_PRACTITIONER
            and self.default_practitioner_id is None
        ):
            raise ValueError("default_practitioner selection needs default_practitioner_id")
        return self

    @property
    def hold(self) -> timedelta:
        return timedelta(minutes=self.hold_minutes)

    @property
    def min_lead(self) -> timedelta:
        return timedelta(minutes=self.min_lead_minutes)
