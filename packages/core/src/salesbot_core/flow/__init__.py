"""Channel-agnostic conversation engine for appointment management (WhatsApp, voice, console)."""

from salesbot_core.flow.drafts import DraftTextBlocked, draft_texts, ensure_sendable
from salesbot_core.flow.engine import REQUIRED_MESSAGES, FlowContext, FlowEngine
from salesbot_core.flow.models import (
    ConversationState,
    FlowEvent,
    Inbound,
    Option,
    Reply,
    StaffTask,
    Step,
    Turn,
)

__all__ = [
    "REQUIRED_MESSAGES",
    "ConversationState",
    "DraftTextBlocked",
    "FlowContext",
    "FlowEngine",
    "FlowEvent",
    "Inbound",
    "Option",
    "Reply",
    "StaffTask",
    "Step",
    "Turn",
    "draft_texts",
    "ensure_sendable",
]
