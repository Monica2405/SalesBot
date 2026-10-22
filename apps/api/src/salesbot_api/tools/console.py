"""Text console: chat with the appointment flow as a patient, in the terminal. No database,
no WhatsApp, no network. The clinic comes from a clinic YAML (same format as load_clinic).

    make console
    uv run --package salesbot-api python -m salesbot_api.tools.console --lang mr
    uv run --package salesbot-api python -m salesbot_api.tools.console --demo
    uv run --package salesbot-api python -m salesbot_api.tools.console --list-drafts

Type a reply, or a number to pick an option. Commands:
    /wait <minutes>   move the clock (holds expire after the clinic's hold time)
    /welcome          send the welcome message (as after intake)
    /confirm          send a confirmation request for the next appointment
    /remind           send a reminder for the next appointment
    /state            show the saved conversation state
    /quit

DRAFT replies are shown tagged [DRAFT]; a live channel would refuse to send them.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import yaml

from salesbot_api.tools.load_clinic import DAYS, ClinicIn, parse_ranges
from salesbot_core.flow import ConversationState, FlowContext, FlowEngine, Inbound, Turn
from salesbot_core.flow.drafts import draft_texts, ensure_sendable
from salesbot_core.flow.memory import InMemoryScheduling
from salesbot_core.flow.render import plain_text
from salesbot_core.packs import load_pack_by_id
from salesbot_core.scheduling import (
    Interval,
    PractitionerCalendar,
    SchedulingSettings,
    WeeklyWindow,
)

REPO = Path(__file__).resolve().parents[5]
DEFAULT_CLINIC = REPO / "docs" / "examples" / "clinic.example.yaml"
DEMO_LINES = [
    "/welcome",
    "1",
    "kal sakali 11 baje",
    "हो",
    "/confirm",
    "are you a bot?",
    "1",
    "reschedule",
    "next monday evening",
    "1",
    "yes",
    "thank you",
]


def build_scheduling(clinic: ClinicIn) -> InMemoryScheduling:
    tz = ZoneInfo(clinic.timezone)
    ids = {p.name: uuid4() for p in clinic.practitioners}

    def weekly(table: dict[str, list[str]]) -> list[WeeklyWindow]:
        return [
            WeeklyWindow(weekday=DAYS[day], start=start, end=end)
            for day, ranges in table.items()
            for start, end in parse_ranges(ranges)
        ]

    def closed_for(name: str) -> list[Interval]:
        return [
            Interval(
                start=datetime.combine(c.date, time(), tz),
                end=datetime.combine((c.to or c.date) + timedelta(days=1), time(), tz),
            )
            for c in clinic.closures
            if c.practitioner in (None, name)
        ]

    calendars = [
        PractitionerCalendar(
            practitioner_id=ids[p.name],
            consultation_minutes=p.consultation_minutes,
            first_visit_minutes=p.first_visit_minutes,
            work=weekly(p.hours),
            breaks=weekly(p.breaks),
            closed=closed_for(p.name),
        )
        for p in clinic.practitioners
    ]
    values = dict(clinic.settings)
    default_name = values.pop("default_practitioner", None)
    if default_name is not None:
        values["default_practitioner_id"] = ids[default_name]
    settings = SchedulingSettings.model_validate(
        {**values, "timezone": clinic.timezone, "default_language": clinic.default_language}
    )
    names = {ids[p.name]: {"en": p.name, **p.display_names} for p in clinic.practitioners}
    return InMemoryScheduling(settings=settings, calendars=calendars, names=names)


class Console:
    def __init__(self, clinic: ClinicIn, language: str, patient: str, now: datetime) -> None:
        self.port = build_scheduling(clinic)
        self.engine = FlowEngine(
            load_pack_by_id(clinic.pack),
            self.port,
            FlowContext(
                business_name=clinic.name,
                client_name=patient,
                default_language=clinic.default_language,
                values={"clinic_phone": "+910000000000"},
            ),
        )
        self.state: ConversationState = self.engine.new_state(language)  # type: ignore[arg-type]
        self.now = now
        self._log_seen = 0

    def show(self, turn: Turn) -> None:
        self.state = turn.state
        for reply in ensure_sendable(turn.replies, live=False):
            tag = " [DRAFT]" if reply.draft else ""
            print(f"\nCLINIC ({reply.language}){tag}:\n{plain_text(reply)}")
        notes = [e.type.value for e in turn.events]
        notes += [f"TASK {t.kind}{' (urgent)' if t.urgent else ''}" for t in turn.tasks]
        notes += self.port.log[self._log_seen :]
        self._log_seen = len(self.port.log)
        if turn.opt_out:
            notes.append("OPT-OUT")
        if notes:
            print(f"   · {', '.join(notes)}")

    def next_appointment(self) -> UUID | None:
        appt = self.port.upcoming(now=self.now)
        if appt is None:
            print("   · no upcoming appointment")
        return appt.id if appt else None

    def command(self, line: str) -> bool:
        """Handle a /command. Returns False to quit."""
        name, _, arg = line[1:].partition(" ")
        if name == "quit":
            return False
        if name == "wait":
            self.now += timedelta(minutes=int(arg or "1"))
            print(f"   · clock: {self.now.astimezone(self.engine.tz):%a %d %b %H:%M} IST")
        elif name == "welcome":
            self.show(self.engine.welcome(self.state, self.now))
        elif name in ("confirm", "remind"):
            appt = self.next_appointment()
            if appt is not None:
                send = (
                    self.engine.confirmation_request if name == "confirm" else self.engine.reminder
                )
                self.show(send(self.state, appt, self.now))
        elif name == "state":
            print(self.state.model_dump_json(indent=2, exclude_defaults=True))
        else:
            print(__doc__)
        return True

    def say(self, text: str) -> None:
        self.now += timedelta(seconds=30)
        self.show(self.engine.handle(self.state, Inbound(text=text, received_at=self.now)))


def main(argv: list[str] | None = None) -> int:
    # Hindi/Marathi output on Windows consoles (default cp1252)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Chat with the appointment flow")
    parser.add_argument("--clinic", type=Path, default=DEFAULT_CLINIC)
    parser.add_argument("--lang", default="en", choices=["en", "hi", "mr"])
    parser.add_argument("--name", default="Test Patient", help="patient name (use a fake one)")
    parser.add_argument("--now", help="start time, ISO 8601 with timezone (default: now)")
    parser.add_argument("--demo", action="store_true", help="run a scripted conversation")
    parser.add_argument("--list-drafts", action="store_true", help="print DRAFT text for review")
    args = parser.parse_args(argv)

    clinic = ClinicIn.model_validate(yaml.safe_load(args.clinic.read_text(encoding="utf-8")))
    if args.list_drafts:
        for key, language, text in draft_texts(load_pack_by_id(clinic.pack)):
            print(f"{key} [{language}]: {text}")
        return 0

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.tzinfo is None:
        parser.error("--now needs a timezone, e.g. 2026-10-21T10:00:00+05:30")
    console = Console(clinic, args.lang, args.name, now)
    print(
        f"{clinic.name}: type a reply, a number for an option, or /help. "
        f"Clock: {now:%Y-%m-%d %H:%M %Z}"
    )

    lines = iter(DEMO_LINES) if args.demo else None
    while True:
        if lines is not None:
            line = next(lines, "/quit")
            print(f"\nPATIENT: {line}")
        else:
            try:
                line = input("\nPATIENT: ").strip()
            except EOFError:
                return 0
        if not line:
            continue
        if line.startswith("/"):
            if not console.command(line):
                return 0
            continue
        console.say(line)


if __name__ == "__main__":
    raise SystemExit(main())
