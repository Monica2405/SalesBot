"""The DRAFT guard: unreviewed text never reaches a real patient.

DRAFT text (docs/DECISIONS.md): the sincere-ask answer lines in every language, and every Hindi
and Marathi line until a native speaker reviews it. Packs mark it with `draft_languages`,
`draft_messages` and `conversation.sincere_ask.draft`; the engine copies that onto each Reply.

Every live channel adapter must pass outgoing replies through `ensure_sendable` with
`live=True`. It fails closed: a DRAFT reply raises instead of being sent, and the adapter falls
back to a staff task. The one exception is a DRAFT reply with a `fallback` (emergencies): the
numbers-only fallback is sent instead, so a possible emergency is never left unanswered. Only
the dev console and simulations pass `live=False`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from salesbot_core.flow.models import Reply
from salesbot_core.packs import Pack
from salesbot_core.packs.schema import Language


class DraftTextBlocked(Exception):
    def __init__(self, reply: Reply) -> None:
        super().__init__(
            f"DRAFT text {reply.key!r} ({reply.language}) is not approved for patients"
        )
        self.reply = reply


def ensure_sendable(replies: Iterable[Reply], *, live: bool) -> list[Reply]:
    """The replies to send. When live, a DRAFT reply is replaced by its fallback (identical
    fallbacks are sent once), or raises DraftTextBlocked if it has none.

    All-or-nothing: a turn is never sent half."""
    replies = list(replies)
    if not live:
        return replies
    out: list[Reply] = []
    for reply in replies:
        if not reply.draft:
            out.append(reply)
            continue
        if reply.fallback is None:
            raise DraftTextBlocked(reply)
        if any(sent.text == reply.fallback for sent in out):
            continue
        out.append(Reply(key=f"{reply.key}_fallback", text=reply.fallback, language=reply.language))
    return out


def draft_texts(pack: Pack) -> Iterator[tuple[str, Language, str]]:
    """Every DRAFT conversation text in a pack as (key, language, text), for reviewers."""
    if pack.conversation is None:
        return
    for key, localized in pack.conversation.messages.items():
        for language, text in localized.items():
            if pack.is_draft(language, key):
                yield key, language, text
    sincere = pack.conversation.sincere_ask
    for language, text in sincere.answer.items():
        if sincere.draft or pack.is_draft(language):
            yield "sincere_ask", language, text
