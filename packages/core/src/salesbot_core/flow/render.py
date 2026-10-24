"""Plain-text rendering of a reply: the text, then numbered options.

Used by the dev console, and by any channel that cannot show buttons. Patients answer with the
number, which the engine maps back to the option.
"""

from __future__ import annotations

from salesbot_core.flow.models import Reply


def plain_text(reply: Reply) -> str:
    lines = [reply.text]
    lines += [f"{i}. {option.label}" for i, option in enumerate(reply.options, start=1)]
    return "\n".join(lines)
