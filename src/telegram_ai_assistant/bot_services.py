from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .domain import (
    BackfillChatChoice,
    BackfillJobRecord,
    BackfillJobSummary,
    ChatPolicyChoice,
    ExtractedItem,
    ItemStatus,
    ItemType,
    ReviewEntry,
    RuntimeEvent,
)
from .health import HealthReport


BACKFILL_DAY_OPTIONS = (1, 5, 10, 15, 30, 90)
BACKFILL_CHAT_PAGE_SIZE = 6
SAFE_LOG_METADATA_KEYS = (
    "error_type",
    "candidate_count",
    "endpoint_scheme",
    "endpoint_host",
    "endpoint_path",
    "http_status",
    "transport_error_type",
    "timeout_seconds",
    "max_tokens",
    "max_completion_tokens",
    "context_length",
    "applied_context_length",
    "configured_model_key",
    "observed_model_count",
    "observed_instance_count",
    "mismatched_instance_count",
    "instance_id",
    "failure_stage",
    "response_keys",
    "choices_count",
    "choice_keys",
    "finish_reason",
    "message_keys",
    "content_type",
    "content_length",
    "reasoning_content_length",
    "validation_error",
    "action_type",
    "source_message_count",
    "count",
    "failures",
)
SAFE_HEALTH_DETAIL_KEYS = ("database", "endpoint", "models", "error", "mode")
ALLOWED_STATUS_CALLBACKS = {
    "completed": ItemStatus.COMPLETED,
    "partially_completed": ItemStatus.PARTIALLY_COMPLETED,
    "cancelled": ItemStatus.CANCELLED,
}


@dataclass(frozen=True)
class BotResponse:
    text: str
    reply_markup: Mapping[str, object] | None = None


class BotServices:
    def __init__(
        self,
        *,
        runtime_event_repository: Any,
        health_report_provider: Any | None = None,
        item_query_repository: Any | None = None,
        item_repository: Any | None = None,
        summary_query_repository: Any | None = None,
        review_repository: Any | None = None,
        chat_query_repository: Any | None = None,
        chat_policy_repository: Any | None = None,
        bot_session_repository: Any | None = None,
        backfill_job_query_repository: Any | None = None,
        backfill_job_repository: Any | None = None,
        settings_snapshot: Any | None = None,
        clock: Any | None = None,
    ):
        self.runtime_event_repository = runtime_event_repository
        self.health_report_provider = health_report_provider
        self.item_query_repository = item_query_repository
        self.item_repository = item_repository
        self.summary_query_repository = summary_query_repository
        self.review_repository = review_repository
        self.chat_query_repository = chat_query_repository
        self.chat_policy_repository = chat_policy_repository
        self.bot_session_repository = bot_session_repository
        self.backfill_job_query_repository = backfill_job_query_repository
        self.backfill_job_repository = backfill_job_repository
        self.settings_snapshot = settings_snapshot
        self.clock = clock or (lambda: datetime.now(UTC))

    def logs(self) -> str:
        events = self.runtime_event_repository.latest_events(limit=10)
        if not events:
            return "No warning/error runtime events."

        lines = ["Latest warning/error runtime events:"]
        for event in events:
            lines.append(_format_runtime_event(event))
        return "\n".join(lines)

    def health(self) -> str:
        if self.health_report_provider is None:
            return "Health service is not configured."
        report = self.health_report_provider()
        return _format_health_report(report)

    def help(self) -> BotResponse:
        return BotResponse(
            text=_format_help(),
            reply_markup=_main_menu_markup(),
        )

    def assistant_menu(self) -> BotResponse:
        return BotResponse(_format_assistant_menu(), _assistant_menu_markup())

    def ops_menu(self) -> BotResponse:
        return BotResponse(_format_ops_menu(), _ops_menu_markup())

    def summary(self) -> BotResponse:
        if self.summary_query_repository is None:
            return BotResponse("Summary service is not configured.", _summary_markup())
        items = self.summary_query_repository.list_summary_items(limit=20)
        if not items:
            return BotResponse("No summary items yet.", _summary_markup())
        return BotResponse(_format_summary(items), _summary_markup())

    def tasks(self) -> BotResponse:
        if self.item_query_repository is None:
            return BotResponse("Task service is not configured.", _main_menu_markup())
        items = self.item_query_repository.list_open_tasks(limit=10)
        if not items:
            return BotResponse("No open tasks.", _main_menu_markup())
        return BotResponse(
            text=_format_tasks(items),
            reply_markup=_tasks_reply_markup(items),
        )

    def review(self) -> BotResponse:
        if self.review_repository is None:
            return BotResponse("Review service is not configured.", _main_menu_markup())
        entries = self.review_repository.list_pending_reviews(limit=5)
        if not entries:
            return BotResponse("No pending reviews.", _review_empty_markup())
        return BotResponse(_format_review_entries(entries), _review_reply_markup(entries))

    def backfill(self) -> BotResponse:
        jobs = []
        if self.backfill_job_query_repository is not None:
            jobs = self.backfill_job_query_repository.latest_jobs(limit=3)
        return BotResponse(_format_backfill(jobs), _backfill_days_markup())

    def blacklist(self) -> BotResponse:
        if self.settings_snapshot is None:
            return BotResponse("Settings service is not configured.", _main_menu_markup())
        return self._policy_chat_page(page=0)

    def settings(self) -> BotResponse:
        if self.settings_snapshot is None:
            return BotResponse("Settings service is not configured.", _main_menu_markup())
        return BotResponse(_format_settings(self.settings_snapshot), _settings_markup())

    def handle_review_callback(self, action: str, target_id: str) -> str:
        if self.review_repository is None:
            return "Review service is not configured."
        try:
            review_id = int(target_id)
        except ValueError:
            return "Invalid review id."
        if action == "approve":
            return str(self.review_repository.approve_review(review_id))
        if action == "reject":
            return str(self.review_repository.reject_review(review_id))
        return "Unknown review action."

    def handle_status_callback(self, action: str, target_id: str) -> str:
        status = ALLOWED_STATUS_CALLBACKS.get(action)
        if status is None:
            return "Unknown status action."
        if self.item_repository is None:
            return "Task status service is not configured."
        self.item_repository.apply_status_change(
            {
                "item_id": target_id,
                "new_status": status,
                "rationale": "Updated from bot callback.",
            }
        )
        return f"Status updated: {status.value}"

    def has_active_session(self, *, user_id: int, chat_id: int) -> bool:
        if self.bot_session_repository is None:
            return False
        session = self.bot_session_repository.get_active_session(
            telegram_user_id=user_id,
            bot_chat_id=chat_id,
            now=self.clock(),
        )
        return session is not None

    def cancel_session(self, *, user_id: int, chat_id: int) -> BotResponse:
        if self.bot_session_repository is not None:
            self.bot_session_repository.clear_user_sessions(
                telegram_user_id=user_id,
                bot_chat_id=chat_id,
            )
        return BotResponse("Active bot flow cancelled.", _main_menu_markup())

    def handle_session_message(self, *, user_id: int, chat_id: int, text: str) -> BotResponse:
        if self.bot_session_repository is None:
            return BotResponse("No active bot flow.", _main_menu_markup())
        session = self.bot_session_repository.get_active_session(
            telegram_user_id=user_id,
            bot_chat_id=chat_id,
            now=self.clock(),
        )
        if session is None:
            return BotResponse("No active bot flow.", _main_menu_markup())
        return BotResponse(
            "Active edit flow is not implemented in this release. Use /cancel to clear it.",
            _main_menu_markup(),
        )

    def handle_policy_callback(self, action: str, target_id: str) -> BotResponse | str:
        if action == "p":
            page = _parse_int(target_id)
            if page is None or page < 0:
                return "Invalid policy page."
            return self._policy_chat_page(page=page)

        chat_id = _parse_int(target_id)
        if chat_id is None:
            return "Invalid chat id."
        if self.chat_policy_repository is None:
            return "Chat policy service is not configured."
        if action == "allow":
            self.chat_policy_repository.allow_chat(chat_id)
        elif action == "deny":
            self.chat_policy_repository.deny_chat(chat_id)
        elif action == "reset":
            self.chat_policy_repository.reset_chat(chat_id)
        else:
            return "Unknown policy action."
        return self._policy_chat_page(page=0, prefix="Policy updated.")

    def handle_backfill_callback(self, action: str, target_id: str) -> str:
        if action in {"30d", "90d"}:
            return f"Backfill preset selected: last {action[:-1]} days."
        if action == "30d":
            return "Backfill preset selected: last 30 days."
        if action == "90d":
            return "Backfill preset selected: last 90 days."
        if action == "d":
            days = _parse_backfill_days(target_id)
            if days is None:
                return "Invalid backfill period."
            return self._backfill_chat_page(days=days, page=0)
        if action == "p":
            parsed = _parse_days_page(target_id)
            if parsed is None:
                return "Invalid backfill page."
            days, page = parsed
            return self._backfill_chat_page(days=days, page=page)
        if action in {"c", "confirm"}:
            parsed_selection = _parse_backfill_selection(target_id, includes_page=action == "c")
            if parsed_selection is None:
                return "Invalid backfill chat selection."
            days, _page, chat_id = parsed_selection
            return self._backfill_confirmation(days=days, chat_id=chat_id)
        if action == "start":
            parsed_start = _parse_days_chat(target_id)
            if parsed_start is None:
                return "Invalid backfill start request."
            days, chat_id = parsed_start
            return self._start_backfill(days=days, chat_id=chat_id)
        if action == "cancel":
            job_id = _parse_int(target_id)
            if job_id is None:
                return "Invalid backfill job id."
            if self.backfill_job_repository is None:
                return "Backfill job service is not configured."
            self.backfill_job_repository.request_cancel(job_id)
            return f"Backfill cancel requested for job #{job_id}."
        if action == "status":
            job_id = _parse_int(target_id)
            if job_id is None or job_id == 0:
                return "Backfill status is available from /backfill."
            return self._backfill_status(job_id)
        return "Unknown backfill action."

    def _backfill_chat_page(self, *, days: int, page: int) -> BotResponse:
        if self.chat_query_repository is None:
            return BotResponse("Backfill chat service is not configured.", _backfill_days_markup())
        chats = self.chat_query_repository.list_backfill_chats(page=page, page_size=BACKFILL_CHAT_PAGE_SIZE)
        return BotResponse(
            _format_backfill_chat_page(days=days, page=page, chats=chats),
            _backfill_chat_page_markup(days=days, page=page, chats=chats),
        )

    def _backfill_confirmation(self, *, days: int, chat_id: int) -> BotResponse:
        chat = self._get_backfill_chat(chat_id)
        if chat is None:
            return BotResponse("Backfill chat is not available.", _backfill_days_markup())
        from_date, to_date = _backfill_date_range(days, self.clock())
        return BotResponse(
            _format_backfill_confirmation(chat=chat, days=days, from_date=from_date, to_date=to_date),
            _backfill_confirmation_markup(days=days, chat_id=chat.chat_id),
        )

    def _start_backfill(self, *, days: int, chat_id: int) -> BotResponse:
        if self.backfill_job_repository is None:
            return BotResponse("Backfill job service is not configured.", _backfill_days_markup())
        chat = self._get_backfill_chat(chat_id)
        if chat is None:
            return BotResponse("Backfill chat is not available.", _backfill_days_markup())
        from_date, to_date = _backfill_date_range(days, self.clock())
        job = self.backfill_job_repository.create_job(
            chat_id=chat.chat_id,
            chat_title=chat.title,
            from_date=from_date,
            to_date=to_date,
        )
        return BotResponse(
            _format_backfill_job_created(job),
            _backfill_job_markup(job),
        )

    def _backfill_status(self, job_id: int) -> BotResponse:
        if self.backfill_job_repository is None:
            return BotResponse("Backfill job service is not configured.", _backfill_days_markup())
        getter = getattr(self.backfill_job_repository, "get_job", None)
        job = getter(job_id) if getter is not None else None
        if job is None:
            return BotResponse(f"Backfill job #{job_id} was not found.", _backfill_days_markup())
        return BotResponse(_format_backfill_job_status(job), _backfill_job_markup(job))

    def _get_backfill_chat(self, chat_id: int) -> BackfillChatChoice | None:
        if self.chat_query_repository is None:
            return None
        getter = getattr(self.chat_query_repository, "get_backfill_chat", None)
        if getter is not None:
            return getter(chat_id)
        for page in range(0, 20):
            chats = self.chat_query_repository.list_backfill_chats(page=page, page_size=BACKFILL_CHAT_PAGE_SIZE)
            match = next((chat for chat in chats if chat.chat_id == chat_id), None)
            if match is not None:
                return match
            if len(chats) < BACKFILL_CHAT_PAGE_SIZE:
                break
        return None

    def _policy_chat_page(self, *, page: int, prefix: str = "") -> BotResponse:
        chats = []
        if self.chat_query_repository is not None:
            lister = getattr(self.chat_query_repository, "list_policy_chats", None)
            if lister is not None:
                chats = lister(page=page, page_size=BACKFILL_CHAT_PAGE_SIZE)
        text = _format_blacklist(self.settings_snapshot, chats=chats, page=page, prefix=prefix)
        return BotResponse(text, _policy_chat_page_markup(page=page, chats=chats))


def _format_runtime_event(event: RuntimeEvent) -> str:
    metadata = _format_safe_metadata(event.metadata)
    suffix = f" {metadata}" if metadata else ""
    return (
        f"{event.created_at.isoformat()} "
        f"[{event.severity.upper()}] "
        f"{event.component} {event.event_type}{suffix}"
    )


def _format_safe_metadata(metadata: dict[str, object]) -> str:
    parts = []
    for key in SAFE_LOG_METADATA_KEYS:
        if key in metadata:
            parts.append(f"{key}={metadata[key]}")
    return " ".join(parts)


def _format_health_report(report: HealthReport) -> str:
    lines = [f"Health: {report.status.value}"]
    for component in report.components:
        details = _format_safe_health_details(component.details or {})
        suffix = f" {details}" if details else ""
        lines.append(f"{component.name}: {component.status.value}{suffix}")
    return "\n".join(lines)


def _format_safe_health_details(details: Any) -> str:
    parts = []
    for key in SAFE_HEALTH_DETAIL_KEYS:
        if key in details:
            parts.append(f"{key}={details[key]}")
    return " ".join(parts)


def _format_help() -> str:
    return "\n".join(
        [
            "Commands:",
            "/cancel - clear active bot flow",
            "/summary - daily structured summary",
            "/tasks - open tasks and commitments",
            "/review - pending low-confidence items",
            "/backfill - safe history import controls",
            "/blacklist - listener allow/deny policy",
            "/settings - non-secret runtime settings",
            "/health - component health",
            "/logs - latest safe warning/error events",
        ]
    )


def _format_assistant_menu() -> str:
    return "\n".join(
        [
            "Assistant:",
            "/summary - daily structured summary",
            "/tasks - open tasks and commitments",
            "/review - pending low-confidence items",
            "/backfill - safe history import controls",
        ]
    )


def _format_ops_menu() -> str:
    return "\n".join(
        [
            "Ops:",
            "/health - component health",
            "/logs - latest safe warning/error events",
            "/backfill - safe history import controls",
            "/blacklist - listener allow/deny policy",
        ]
    )


def _main_menu_markup() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "Assistant", "callback_data": "menu:assistant:0"},
                {"text": "Ops", "callback_data": "menu:ops:0"},
            ],
            [
                {"text": "Settings", "callback_data": "menu:settings:0"},
                {"text": "Help", "callback_data": "menu:help:0"},
            ],
        ]
    }


def _shell_navigation_rows() -> list[list[dict[str, str]]]:
    return [
        [
            {"text": "Assistant", "callback_data": "menu:assistant:0"},
            {"text": "Ops", "callback_data": "menu:ops:0"},
        ],
        [
            {"text": "Settings", "callback_data": "menu:settings:0"},
            {"text": "Help", "callback_data": "menu:help:0"},
        ],
    ]


def _with_shell_navigation(rows: list[list[dict[str, str]]]) -> dict[str, object]:
    return {"inline_keyboard": rows + _shell_navigation_rows()}


def _assistant_menu_markup() -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": "Summary", "callback_data": "menu:summary:0"},
                {"text": "Tasks", "callback_data": "menu:tasks:0"},
            ],
            [
                {"text": "Review", "callback_data": "menu:review:0"},
                {"text": "Backfill", "callback_data": "menu:backfill:0"},
            ],
        ]
    )


def _ops_menu_markup() -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": "Health", "callback_data": "menu:health:0"},
                {"text": "Logs", "callback_data": "menu:logs:0"},
            ],
            [
                {"text": "Backfill", "callback_data": "menu:backfill:0"},
                {"text": "Blacklist", "callback_data": "menu:blacklist:0"},
            ],
        ]
    )


def _format_summary(items: list[ExtractedItem]) -> str:
    sections = [
        ("Tasks and commitments:", _summary_task_items(items)),
        ("Waiting:", [item for item in items if item.item_type == ItemType.WAITING_FOR]),
        ("Thoughts:", [item for item in items if item.item_type in (ItemType.THOUGHT, ItemType.USEFUL_CONTEXT)]),
    ]
    lines = ["Summary:"]
    for title, section_items in sections:
        if not section_items:
            continue
        lines.append(title)
        for item in section_items[:8]:
            due = f" due={item.due_at.isoformat()}" if item.due_at is not None else ""
            lines.append(f"- {item.title} [{item.item_type.value}/{item.status.value}]{due}")
    return "\n".join(lines)


def _summary_task_items(items: list[ExtractedItem]) -> list[ExtractedItem]:
    return [
        item
        for item in items
        if item.item_type
        in (
            ItemType.TASK,
            ItemType.COMMITMENT,
            ItemType.REMINDER,
        )
    ]


def _summary_markup() -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": "Tasks", "callback_data": "menu:tasks:0"},
                {"text": "Review", "callback_data": "menu:review:0"},
            ],
            [
                {"text": "Refresh", "callback_data": "menu:summary:0"},
            ],
        ]
    )


def _format_review_entries(entries: list[ReviewEntry]) -> str:
    action_entries = [entry for entry in entries if entry.llm_action is not None]
    legacy_entries = [entry for entry in entries if entry.llm_action is None]
    if action_entries:
        lines = _format_action_review_entries(action_entries)
        if legacy_entries:
            lines.append("Legacy reviews:")
            lines.extend(_format_legacy_review_entries(legacy_entries)[1:])
        return "\n".join(lines)
    return "\n".join(_format_legacy_review_entries(entries))


def _format_legacy_review_entries(entries: list[ReviewEntry]) -> list[str]:
    lines = ["Pending reviews:"]
    for index, entry in enumerate(entries, start=1):
        item_text = _review_entry_item_text(entry)
        confidence = _review_confidence(entry)
        confidence_text = f" confidence={confidence}" if confidence else ""
        reason = f" reason={entry.reason}" if entry.reason else ""
        lines.append(f"{index}. #{entry.review_id} {entry.review_type}{confidence_text}: {item_text}{reason}")
    return lines


def _format_action_review_entries(entries: list[ReviewEntry]) -> list[str]:
    lines = ["Pending action reviews:"]
    grouped: dict[str, list[ReviewEntry]] = {}
    for entry in entries:
        source = entry.llm_action.source_refs[0] if entry.llm_action and entry.llm_action.source_refs else None
        key = "unknown" if source is None else f"{source.chat_id}/{source.telegram_message_id}"
        grouped.setdefault(key, []).append(entry)
    for source_key, group_entries in grouped.items():
        lines.append(f"Source {source_key}")
        for index, entry in enumerate(group_entries, start=1):
            action = entry.llm_action
            if action is None:
                continue
            confidence = f"{float(action.confidence):.2f}"
            target = f" target={action.target_item_id}" if action.target_item_id else ""
            summary = _action_payload_summary(action.payload)
            lines.append(
                f"{index}. #{entry.review_id} {action.action_type.value}{target} "
                f"confidence={confidence}: {summary} reason={action.rationale}"
            )
    return lines


def _action_payload_summary(payload: Mapping[str, object]) -> str:
    for key in ("title", "new_status", "new_value", "notification_type"):
        value = payload.get(key)
        if value:
            return str(value)
    if payload.get("field"):
        return f"{payload.get('field')}={payload.get('new_value', '')}"
    return "payload"


def _review_entry_item_text(entry: ReviewEntry) -> str:
    if entry.item is not None:
        return entry.item.title
    item_id = entry.payload.get("item_id")
    new_status = entry.payload.get("new_status", entry.payload.get("status"))
    if item_id and new_status:
        return f"{item_id} -> {new_status}"
    return "Status change"


def _review_confidence(entry: ReviewEntry) -> str:
    confidence = entry.payload.get("confidence")
    if confidence is None and entry.item is not None:
        confidence = entry.item.confidence
    if confidence is None:
        return ""
    try:
        return f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        return str(confidence)


def _review_reply_markup(entries: list[ReviewEntry]) -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": f"Approve {index}", "callback_data": f"review:approve:{entry.review_id}"},
                {"text": f"Reject {index}", "callback_data": f"review:reject:{entry.review_id}"},
            ]
            for index, entry in enumerate(entries, start=1)
        ]
    )


def _review_empty_markup() -> dict[str, object]:
    return _main_menu_markup()


def _format_backfill(jobs: list[BackfillJobSummary]) -> str:
    lines = [
        "Backfill:",
        "Presets are bounded and use configured backfill limits.",
    ]
    if not jobs:
        lines.append("Last jobs: none")
        return "\n".join(lines)

    lines.append("Last jobs:")
    for job in jobs:
        error = f" error={job.error}" if job.error else ""
        lines.append(
            f"- #{job.backfill_job_id} {job.status} "
            f"{job.from_date.isoformat()}..{job.to_date.isoformat()}{error}"
        )
    return "\n".join(lines)


def _backfill_days_markup() -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": "1d", "callback_data": "bf:d:1"},
                {"text": "5d", "callback_data": "bf:d:5"},
                {"text": "10d", "callback_data": "bf:d:10"},
            ],
            [
                {"text": "15d", "callback_data": "bf:d:15"},
                {"text": "30d", "callback_data": "bf:d:30"},
                {"text": "90d", "callback_data": "bf:d:90"},
            ],
            [
                {"text": "Refresh", "callback_data": "menu:backfill:0"},
            ],
        ]
    )


def _format_backfill_chat_page(*, days: int, page: int, chats: list[BackfillChatChoice]) -> str:
    lines = [
        "Backfill: choose chat",
        f"Period: last {days} days",
        f"Page: {page + 1}",
    ]
    if not chats:
        lines.append("No eligible chats on this page.")
        return "\n".join(lines)
    for index, chat in enumerate(chats, start=1):
        lines.append(f"{index}. {_chat_display_name(chat)} [{chat.chat_type}]")
    return "\n".join(lines)


def _backfill_chat_page_markup(*, days: int, page: int, chats: list[BackfillChatChoice]) -> dict[str, object]:
    rows = [
        [{"text": _chat_display_name(chat), "callback_data": f"bf:c:{days}:{page}:{chat.chat_id}"}]
        for chat in chats
    ]
    navigation = []
    if page > 0:
        navigation.append({"text": "Previous", "callback_data": f"bf:p:{days}:{page - 1}"})
    navigation.append({"text": "Next", "callback_data": f"bf:p:{days}:{page + 1}"})
    rows.append([{"text": "Periods", "callback_data": "menu:backfill:0"}])
    rows.extend(_shell_navigation_rows())
    rows.append(navigation)
    return {"inline_keyboard": rows}


def _format_backfill_confirmation(
    *,
    chat: BackfillChatChoice,
    days: int,
    from_date: datetime,
    to_date: datetime,
) -> str:
    return "\n".join(
        [
            "Confirm backfill",
            f"Chat: {_chat_display_name(chat)}",
            f"Period: last {days} days",
            f"From: {from_date.isoformat()}",
            f"To: {to_date.isoformat()}",
        ]
    )


def _backfill_confirmation_markup(*, days: int, chat_id: int) -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": "Start", "callback_data": f"bf:start:{days}:{chat_id}"},
                {"text": "Cancel", "callback_data": f"bf:d:{days}"},
            ]
        ]
    )


def _format_backfill_job_created(job: BackfillJobRecord) -> str:
    return "\n".join(
        [
            f"Backfill job #{job.backfill_job_id} created.",
            f"Chat: {job.chat_title or job.chat_id}",
            f"Status: {job.status}",
            f"From: {job.from_date.isoformat()}",
            f"To: {job.to_date.isoformat()}",
        ]
    )


def _format_backfill_job_status(job: BackfillJobRecord) -> str:
    lines = [
        f"Backfill job #{job.backfill_job_id}",
        f"Chat: {job.chat_title or job.chat_id}",
        f"Status: {job.status}",
        f"Saved: {job.saved_count}",
        f"From: {job.from_date.isoformat()}",
        f"To: {job.to_date.isoformat()}",
    ]
    if job.next_before_message_id is not None:
        lines.append(f"Next cursor: {job.next_before_message_id}")
    if job.last_error_type:
        lines.append(f"Error: {job.last_error_type}")
    return "\n".join(lines)


def _backfill_job_markup(job: BackfillJobRecord) -> dict[str, object]:
    row = [{"text": "Status", "callback_data": f"bf:status:{job.backfill_job_id}"}]
    if job.status in {"pending", "running"}:
        row.append({"text": "Cancel", "callback_data": f"bf:cancel:{job.backfill_job_id}"})
    return _with_shell_navigation([row, [{"text": "Backfill", "callback_data": "menu:backfill:0"}]])


def _chat_display_name(chat: BackfillChatChoice) -> str:
    return chat.title.strip() or str(chat.chat_id)


def _backfill_date_range(days: int, now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - timedelta(days=days), now


def _parse_backfill_days(value: str) -> int | None:
    days = _parse_int(value)
    if days in BACKFILL_DAY_OPTIONS:
        return days
    return None


def _parse_days_page(value: str) -> tuple[int, int] | None:
    parts = value.split(":")
    if len(parts) != 2:
        return None
    days = _parse_backfill_days(parts[0])
    page = _parse_int(parts[1])
    if days is None or page is None or page < 0:
        return None
    return days, page


def _parse_backfill_selection(value: str, *, includes_page: bool) -> tuple[int, int, int] | None:
    parts = value.split(":")
    if includes_page:
        if len(parts) != 3:
            return None
        days = _parse_backfill_days(parts[0])
        page = _parse_int(parts[1])
        chat_id = _parse_int(parts[2])
    else:
        if len(parts) != 2:
            return None
        days = _parse_backfill_days(parts[0])
        page = 0
        chat_id = _parse_int(parts[1])
    if days is None or page is None or chat_id is None:
        return None
    return days, page, chat_id


def _parse_days_chat(value: str) -> tuple[int, int] | None:
    parsed = _parse_backfill_selection(value, includes_page=False)
    if parsed is None:
        return None
    days, _page, chat_id = parsed
    return days, chat_id


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_blacklist(
    settings: Any,
    *,
    chats: list[ChatPolicyChoice] | None = None,
    page: int = 0,
    prefix: str = "",
) -> str:
    allowed = _ids_text(getattr(settings, "telegram_listener_allowed_channel_ids", ()))
    denied = _ids_text(getattr(settings, "telegram_listener_denied_chat_ids", ()))
    lines = []
    if prefix:
        lines.append(prefix)
    lines.extend(
        [
            "Listener policy:",
            "private/basic groups/supergroups are allowed by default",
            "broadcast channels are ignored unless allowlisted",
            f"allowed_channel_ids={allowed}",
            f"denied_chat_ids={denied}",
            "Bot overrides are applied without restart.",
        ]
    )
    if chats is None:
        return "\n".join(lines)

    lines.extend(["Policy chats:", f"Page: {page + 1}"])
    if not chats:
        lines.append("No known chats on this page.")
        return "\n".join(lines)
    for index, chat in enumerate(chats, start=1):
        lines.append(f"{index}. {_policy_chat_display_name(chat)} [{chat.chat_type}/{chat.policy_state}]")
    return "\n".join(lines)


def _policy_chat_page_markup(*, page: int, chats: list[ChatPolicyChoice]) -> dict[str, object]:
    rows = [
        [
            {"text": f"Deny {index}", "callback_data": f"policy:deny:{chat.chat_id}"},
            {"text": f"Allow {index}", "callback_data": f"policy:allow:{chat.chat_id}"},
            {"text": f"Reset {index}", "callback_data": f"policy:reset:{chat.chat_id}"},
        ]
        for index, chat in enumerate(chats, start=1)
    ]
    navigation = []
    if page > 0:
        navigation.append({"text": "Previous", "callback_data": f"policy:p:{page - 1}"})
    navigation.append({"text": "Next", "callback_data": f"policy:p:{page + 1}"})
    rows.extend(_shell_navigation_rows())
    rows.append(navigation)
    return {"inline_keyboard": rows}


def _policy_chat_display_name(chat: ChatPolicyChoice) -> str:
    return chat.title.strip() or str(chat.chat_id)


def _format_settings(settings: Any) -> str:
    allowed = _ids_text(getattr(settings, "telegram_listener_allowed_channel_ids", ()))
    denied = _ids_text(getattr(settings, "telegram_listener_denied_chat_ids", ()))
    return "\n".join(
        [
            "Settings:",
            f"account_id={getattr(settings, 'telegram_ingest_account_id', '')}",
            f"ingest_chat_id={getattr(settings, 'telegram_ingest_chat_id', 0)}",
            f"listener_allowed_channel_ids={allowed}",
            f"listener_denied_chat_ids={denied}",
            f"lm_studio_base_url={getattr(settings, 'lm_studio_base_url', '')}",
            f"lm_studio_model={getattr(settings, 'lm_studio_model', '')}",
            f"lm_studio_context_length={getattr(settings, 'lm_studio_context_length', '')}",
            f"worker_batch_size={getattr(settings, 'worker_batch_size', '')}",
            f"worker_open_item_context_limit={getattr(settings, 'worker_open_item_context_limit', '')}",
            f"worker_poll_interval_seconds={getattr(settings, 'worker_poll_interval_seconds', '')}",
            f"worker_item_auto_apply_threshold={getattr(settings, 'worker_item_auto_apply_threshold', '')}",
            f"worker_status_auto_apply_threshold={getattr(settings, 'worker_status_auto_apply_threshold', '')}",
            f"log_level={getattr(settings, 'log_level', '')}",
            f"telegram_data_dir={getattr(settings, 'telegram_data_dir', '')}",
        ]
    )


def _settings_markup() -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": "Health", "callback_data": "menu:health:0"},
            ]
        ]
    )


def _ids_text(values: object) -> str:
    items = tuple(values or ())
    if not items:
        return "none"
    return ",".join(str(value) for value in items)


def _format_tasks(items: list[ExtractedItem]) -> str:
    lines = ["Open tasks:"]
    for index, item in enumerate(items, start=1):
        due = f" due={item.due_at.isoformat()}" if item.due_at is not None else ""
        lines.append(f"{index}. {item.title} [{item.item_type.value}/{item.status.value}]{due}")
    return "\n".join(lines)


def _tasks_reply_markup(items: list[ExtractedItem]) -> dict[str, object]:
    return _with_shell_navigation(
        [
            [
                {"text": f"Done {index}", "callback_data": f"task:completed:{item.item_id}"},
                {
                    "text": f"Partial {index}",
                    "callback_data": f"task:partially_completed:{item.item_id}",
                },
                {"text": f"Cancel {index}", "callback_data": f"task:cancelled:{item.item_id}"},
            ]
            for index, item in enumerate(items, start=1)
        ]
    )
