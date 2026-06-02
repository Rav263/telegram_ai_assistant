from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class ItemType(StrEnum):
    TASK = "task"
    THOUGHT = "thought"
    COMMITMENT = "commitment"
    REMINDER = "reminder"
    WAITING_FOR = "waiting_for"
    USEFUL_CONTEXT = "useful_context"


class ItemStatus(StrEnum):
    CANDIDATE = "candidate"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OBSOLETE = "obsolete"
    WAITING_FOR = "waiting_for"


@dataclass(frozen=True)
class SourceRef:
    chat_id: int
    telegram_message_id: int


@dataclass(frozen=True)
class Message:
    account_id: str
    chat_id: int
    telegram_message_id: int
    sender_id: int
    direction: MessageDirection
    sent_at: datetime
    text: str = ""
    caption: str = ""
    reply_to_message_id: int | None = None

    @property
    def content_text(self) -> str:
        return self.text.strip() or self.caption.strip()


@dataclass(frozen=True)
class ExtractedItem:
    item_id: str
    item_type: ItemType
    title: str
    description: str
    confidence: float
    sources: tuple[SourceRef, ...]
    status: ItemStatus = ItemStatus.OPEN
    rationale: str = ""
    due_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)
