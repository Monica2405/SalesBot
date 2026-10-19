"""Emergency detection, driven entirely by the pack's `emergency.triggers`.

Packs without an emergency section (e.g. salon) never trigger.
"""

from __future__ import annotations

from salesbot_core.packs import Pack


def detect_emergency(pack: Pack, utterance: str) -> str | None:
    """Return the matched trigger phrase, or None."""
    if pack.emergency is None:
        return None
    text = utterance.casefold()
    for trigger in pack.emergency.triggers:
        if trigger.casefold() in text:
            return trigger
    return None
