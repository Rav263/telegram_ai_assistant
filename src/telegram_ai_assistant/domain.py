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


class LLMActionType(StrEnum):
    CREATE_ITEM = "create_item"
    UPDATE_ITEM_STATUS = "update_item_status"
    UPDATE_ITEM_FIELD = "update_item_field"
    MERGE_DUPLICATE = "merge_duplicate"
    SCHEDULE_NOTIFICATION = "schedule_notification"
    LINK_SOURCE = "link_source"


class LLMActionState(StrEnum):
    PENDING = "pending"
    REVIEW = "review"
    APPLIED = "applied"
    REJECTED = "rejected"
    FAILED = "failed"
    IGNORED = "ignored"


class LLMActionDecision(StrEnum):
    AUTO_APPLY = "auto_apply"
    REVIEW = "review"
    REJECT = "reject"


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


@dataclass(frozen=True)
class ReviewEntry:
    review_id: int
    review_type: str
    state: str
    reason: str
    payload: dict[str, object]
    created_at: datetime
    item: ExtractedItem | None = None
    llm_action: "LLMAction | None" = None


@dataclass(frozen=True)
class LLMAction:
    action_key: str
    action_type: LLMActionType
    state: LLMActionState
    confidence: float
    payload: dict[str, object]
    source_refs: tuple[SourceRef, ...]
    rationale: str
    llm_action_id: int | None = None
    target_item_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BackfillChatChoice:
    chat_id: int
    title: str
    chat_type: str


@dataclass(frozen=True)
class ChatCursor:
    chat_id: int
    title: str
    chat_type: str
    last_ingested_message_id: int


@dataclass(frozen=True)
class ChatPolicyChoice:
    chat_id: int
    title: str
    chat_type: str
    policy_state: str


@dataclass(frozen=True)
class BotSession:
    telegram_user_id: int
    bot_chat_id: int
    flow_id: str
    payload: dict[str, object]
    expires_at: datetime


@dataclass(frozen=True)
class BackfillJobSummary:
    backfill_job_id: int
    status: str
    from_date: datetime
    to_date: datetime
    error: str = ""
    created_at: datetime | None = None
    chat_id: int = 0
    chat_title: str = ""
    saved_count: int = 0
    next_before_message_id: int | None = None
    last_error_type: str = ""


@dataclass(frozen=True)
class BackfillJobRecord:
    backfill_job_id: int
    account_id: str
    chat_id: int
    chat_title: str
    status: str
    from_date: datetime
    to_date: datetime
    next_before_message_id: int | None
    saved_count: int
    last_error_type: str
    last_error_metadata: dict[str, object]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class RuntimeEvent:
    runtime_event_id: int
    component: str
    severity: str
    event_type: str
    message: str
    metadata: dict[str, object]
    created_at: datetime
