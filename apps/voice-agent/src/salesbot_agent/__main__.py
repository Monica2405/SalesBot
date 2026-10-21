"""Text simulator: talk to the agent in the terminal using mock providers.

make dev-agent                      # interactive, dentist pack
uv run python -m salesbot_agent --pack salon --lang hi
uv run python -m salesbot_agent --demo
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from salesbot_agent.engine import CallContext, Receptionist
from salesbot_agent.handoff import StubHandoff
from salesbot_agent.providers.llm import get_llm
from salesbot_agent.settings import AgentSettings
from salesbot_core.events import LeadSource
from salesbot_core.packs import load_pack_by_id

DEMO_LINES = ["yes", "Asha", "this number", "cleaning", "no", "tomorrow 11am"]


async def run(pack_id: str, language: str, demo: bool) -> None:
    settings = AgentSettings()
    key = settings.sarvam_api_key.get_secret_value() if settings.sarvam_api_key else None
    engine = Receptionist(
        pack=load_pack_by_id(pack_id),
        llm=get_llm(settings.llm_provider, key),
        handoff=StubHandoff(),
        ctx=CallContext(
            call_id="sim-1",
            business_name="Demo Business",
            language=language,  # type: ignore[arg-type]
            source=LeadSource.TEST_CALL,
            business_values={"business_hours": "10am-8pm", "business_address": "Demo Road"},
        ),
    )
    turn = engine.opening()
    print(f"AGENT: {turn.say}   {[e.value for e in turn.events]}")
    lines = iter(DEMO_LINES)
    while not turn.end_call:
        if demo:
            text = next(lines)
            print(f"CALLER: {text}")
        else:
            text = await asyncio.to_thread(input, "CALLER: ")
        turn = await engine.on_user_utterance(text)
        print(f"AGENT: {turn.say}   {[e.value for e in turn.events]}")
    print(f"\nanswers={engine.answers} consent={engine.consent_recording} usage={engine.usage}")


def main() -> None:
    # Hindi/Marathi output on Windows consoles (default cp1252)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="SalesBot voice agent text simulator")
    parser.add_argument("--pack", default="dentist")
    parser.add_argument("--lang", default="en", choices=["en", "hi", "mr"])
    parser.add_argument("--demo", action="store_true", help="run a scripted conversation")
    args = parser.parse_args()
    asyncio.run(run(args.pack, args.lang, args.demo))


if __name__ == "__main__":
    main()
