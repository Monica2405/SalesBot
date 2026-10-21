"""Load or update a clinic's setup (practitioners, weekly hours, breaks, holidays, settings)
from a YAML file into the database in SUPABASE_DB_URL. Dev tool; the admin app replaces it later.

    uv run --package salesbot-api python -m salesbot_api.tools.load_clinic my-clinic.yaml

(Start from docs/examples/clinic.example.yaml.)

Idempotent by business slug: practitioners are matched by name; their hours and the clinic's
future exceptions are replaced. Prints the business id (the intake contract's clinic_id).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from salesbot_api import db
from salesbot_api.settings import Settings
from salesbot_core.packs.schema import Language
from salesbot_core.scheduling import SchedulingSettings

DAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _parse_ranges(value: list[str]) -> list[tuple[time, time]]:
    out = []
    for r in value:
        start, end = (time.fromisoformat(x.strip()) for x in r.split("-"))
        if end <= start:
            raise ValueError(f"range {r!r} ends before it starts")
        out.append((start, end))
    return out


class PractitionerIn(_Strict):
    name: str
    display_names: dict[Language, str] = Field(default_factory=dict)
    consultation_minutes: int = Field(ge=5, le=480)
    first_visit_minutes: int | None = Field(default=None, ge=5, le=480)
    # {"mon": ["10:00-13:00", "17:00-20:00"], ...}
    hours: dict[str, list[str]]
    breaks: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("hours", "breaks")
    @classmethod
    def _days(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        unknown = set(v) - set(DAYS)
        if unknown:
            raise ValueError(f"unknown weekday keys {sorted(unknown)}; use {list(DAYS)}")
        for ranges in v.values():
            _parse_ranges(ranges)
        return v


class Closure(_Strict):
    date: date
    to: date | None = None  # inclusive; default = same day
    practitioner: str | None = None  # None = whole clinic
    reason: str | None = None


class ClinicIn(_Strict):
    name: str
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    pack: str = "clinic"
    timezone: str = "Asia/Kolkata"
    default_language: Language = "en"
    settings: dict[str, Any] = Field(default_factory=dict)
    practitioners: list[PractitionerIn] = Field(min_length=1)
    closures: list[Closure] = Field(default_factory=list)


def load(conn: Any, clinic: ClinicIn) -> Any:
    tz = ZoneInfo(clinic.timezone)
    with conn.transaction():
        bid = conn.execute(
            """
            insert into public.businesses (name, slug, pack_id, timezone, default_language)
            values (%s, %s, %s, %s, %s)
            on conflict (slug) do update set name = excluded.name, pack_id = excluded.pack_id,
              timezone = excluded.timezone, default_language = excluded.default_language
            returning id
            """,
            (clinic.name, clinic.slug, clinic.pack, clinic.timezone, clinic.default_language),
        ).fetchone()["id"]

        ids: dict[str, Any] = {}
        for p in clinic.practitioners:
            existing = conn.execute(
                "select id from public.practitioners where business_id = %s and name = %s",
                (bid, p.name),
            ).fetchone()
            if existing:
                pid = existing["id"]
                conn.execute(
                    "update public.practitioners set display_names = %s, "
                    "consultation_minutes = %s, first_visit_minutes = %s, is_active = true "
                    "where id = %s",
                    (Jsonb(p.display_names), p.consultation_minutes, p.first_visit_minutes, pid),
                )
            else:
                pid = conn.execute(
                    "insert into public.practitioners (business_id, name, display_names, "
                    "consultation_minutes, first_visit_minutes) values (%s, %s, %s, %s, %s) "
                    "returning id",
                    (
                        bid,
                        p.name,
                        Jsonb(p.display_names),
                        p.consultation_minutes,
                        p.first_visit_minutes,
                    ),
                ).fetchone()["id"]
            ids[p.name] = pid
            conn.execute("delete from public.practitioner_hours where practitioner_id = %s", (pid,))
            for kind, table in (("work", p.hours), ("break", p.breaks)):
                for day, ranges in table.items():
                    for start, end in _parse_ranges(ranges):
                        conn.execute(
                            "insert into public.practitioner_hours (business_id, "
                            "practitioner_id, kind, weekday, start_time, end_time) "
                            "values (%s, %s, %s, %s, %s, %s)",
                            (bid, pid, kind, DAYS[day], start, end),
                        )

        today = datetime.now(tz).date()
        conn.execute(
            "delete from public.schedule_exceptions where business_id = %s and ends_at > %s",
            (bid, datetime.combine(today, time(), tz)),
        )
        for c in clinic.closures:
            if c.practitioner is not None and c.practitioner not in ids:
                raise ValueError(f"closure names unknown practitioner {c.practitioner!r}")
            start = datetime.combine(c.date, time(), tz)
            end = datetime.combine((c.to or c.date) + timedelta(days=1), time(), tz)
            conn.execute(
                "insert into public.schedule_exceptions (business_id, practitioner_id, kind, "
                "starts_at, ends_at, reason) values (%s, %s, 'closed', %s, %s, %s)",
                (bid, ids.get(c.practitioner) if c.practitioner else None, start, end, c.reason),
            )

        settings = dict(clinic.settings)
        default_name = settings.pop("default_practitioner", None)
        if default_name is not None:
            settings["default_practitioner_id"] = ids[default_name]
        columns = ["business_id", *settings]
        values = [bid, *(Jsonb(v) if isinstance(v, dict) else v for v in settings.values())]
        updates = (
            ", ".join(f"{c} = excluded.{c}" for c in settings)
            or "business_id = excluded.business_id"
        )
        conn.execute(
            f"insert into public.scheduling_settings ({', '.join(columns)}) "  # noqa: S608 (keys validated below)
            f"values ({', '.join(['%s'] * len(columns))}) "
            f"on conflict (business_id) do update set {updates}",
            values,
        )
    return bid


ALLOWED_SETTINGS = {
    "hold_minutes",
    "min_lead_minutes",
    "lookahead_days",
    "days_per_list",
    "slot_step_minutes",
    "practitioner_selection",
    "default_practitioner",
    "reschedule_approval",
    "confirmation_policy",
    "reminder_policy",
    "call_policy",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a clinic setup from YAML")
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    clinic = ClinicIn.model_validate(yaml.safe_load(args.file.read_text(encoding="utf-8")))
    unknown = set(clinic.settings) - ALLOWED_SETTINGS
    if unknown:
        print(f"unknown settings keys: {sorted(unknown)}", file=sys.stderr)
        return 2
    # Validate values with the same model the booking engine reads them with
    values = {k: v for k, v in clinic.settings.items() if k != "default_practitioner"}
    if "default_practitioner" in clinic.settings:
        values["default_practitioner_id"] = "00000000-0000-0000-0000-000000000000"
    SchedulingSettings.model_validate(values)
    settings = Settings()
    if settings.app_env == "production":
        print("refusing to run with APP_ENV=production", file=sys.stderr)
        return 2
    with db.connect(settings, autocommit=True) as conn:
        bid = load(conn, clinic)
    print(f"clinic_id: {bid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
