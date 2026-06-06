from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.bot_services import BotServices
from telegram_ai_assistant.domain import (
    BackfillChatChoice,
    BackfillJobRecord,
    BackfillJobSummary,
    ExtractedItem,
    ItemStatus,
    ItemType,
    ReviewEntry,
    RuntimeEvent,
    SourceRef,
)
from telegram_ai_assistant.health import ComponentHealth, HealthReport, HealthStatus


class FakeRuntimeEventRepository:
    def __init__(self, events=()):
        self.events = list(events)
        self.calls = []

    def latest_events(self, *, limit):
        self.calls.append(("latest_events", limit))
        return self.events[:limit]


class FakeItemQueryRepository:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []

    def list_open_tasks(self, *, limit):
        self.calls.append(("list_open_tasks", limit))
        return self.items[:limit]


class FakeSummaryQueryRepository:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []

    def list_summary_items(self, *, limit):
        self.calls.append(("list_summary_items", limit))
        return self.items[:limit]


class FakeItemRepository:
    def __init__(self):
        self.status_changes = []

    def apply_status_change(self, change):
        self.status_changes.append(change)


class FakeReviewRepository:
    def __init__(self, entries=()):
        self.entries = list(entries)
        self.calls = []

    def list_pending_reviews(self, *, limit):
        self.calls.append(("list_pending_reviews", limit))
        return self.entries[:limit]

    def approve_review(self, review_id):
        self.calls.append(("approve_review", review_id))
        return "Review approved."

    def reject_review(self, review_id):
        self.calls.append(("reject_review", review_id))
        return "Review rejected."


class FakeBackfillJobQueryRepository:
    def __init__(self, jobs=()):
        self.jobs = list(jobs)
        self.calls = []

    def latest_jobs(self, *, limit):
        self.calls.append(("latest_jobs", limit))
        return self.jobs[:limit]


class FakeChatQueryRepository:
    def __init__(self, chats=()):
        self.chats = list(chats)
        self.calls = []

    def list_backfill_chats(self, *, page, page_size):
        self.calls.append(("list_backfill_chats", page, page_size))
        start = page * page_size
        return self.chats[start : start + page_size]

    def get_backfill_chat(self, chat_id):
        self.calls.append(("get_backfill_chat", chat_id))
        return next((chat for chat in self.chats if chat.chat_id == chat_id), None)


class FakeBackfillJobRepository(FakeBackfillJobQueryRepository):
    def __init__(self, jobs=()):
        super().__init__(jobs)
        self.created_jobs = []
        self.cancelled_jobs = []

    def create_job(self, *, chat_id, chat_title, from_date, to_date):
        self.created_jobs.append(
            {
                "chat_id": chat_id,
                "chat_title": chat_title,
                "from_date": from_date,
                "to_date": to_date,
            }
        )
        return make_backfill_record(
            backfill_job_id=99,
            chat_id=chat_id,
            chat_title=chat_title,
            status="pending",
            from_date=from_date,
            to_date=to_date,
        )

    def request_cancel(self, backfill_job_id):
        self.cancelled_jobs.append(backfill_job_id)

    def get_job(self, backfill_job_id):
        self.calls.append(("get_job", backfill_job_id))
        return next((job for job in self.jobs if job.backfill_job_id == backfill_job_id), None)


class FakeSettingsSnapshot:
    telegram_ingest_account_id = "owner"
    telegram_ingest_chat_id = 123
    telegram_listener_allowed_channel_ids = (777,)
    telegram_listener_denied_chat_ids = (888,)
    lm_studio_base_url = "http://host.docker.internal:1234/v1"
    lm_studio_model = "qwen2.5"
    worker_batch_size = 25
    worker_poll_interval_seconds = 10
    worker_item_auto_apply_threshold = 0.8
    worker_status_auto_apply_threshold = 0.8
    log_level = "INFO"
    telegram_data_dir = "/Users/blda/.telegram/telegram_ai_assistant"


def make_task(
    *,
    item_id="task-1",
    item_type=ItemType.TASK,
    title="Send report",
    status=ItemStatus.OPEN,
    due_at=None,
):
    return ExtractedItem(
        item_id=item_id,
        item_type=item_type,
        title=title,
        description="Prepare and send the report",
        confidence=0.91,
        status=status,
        due_at=due_at,
        sources=(SourceRef(chat_id=100, telegram_message_id=200),),
    )


def make_backfill_record(
    *,
    backfill_job_id=7,
    chat_id=1001,
    chat_title="Alice",
    status="running",
    from_date=datetime(2026, 5, 7, 9, 0, tzinfo=UTC),
    to_date=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
    saved_count=12,
    next_before_message_id=450,
    last_error_type="",
):
    now = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
    return BackfillJobRecord(
        backfill_job_id=backfill_job_id,
        account_id="owner",
        chat_id=chat_id,
        chat_title=chat_title,
        status=status,
        from_date=from_date,
        to_date=to_date,
        next_before_message_id=next_before_message_id,
        saved_count=saved_count,
        last_error_type=last_error_type,
        last_error_metadata={},
        created_at=now,
        started_at=now if status == "running" else None,
        finished_at=None,
        updated_at=now,
    )


class BotServicesTests(unittest.TestCase):
    def test_logs_formats_latest_runtime_events_without_raw_messages(self):
        repository = FakeRuntimeEventRepository(
            events=[
                RuntimeEvent(
                    runtime_event_id=10,
                    component="worker",
                    severity="error",
                    event_type="worker_cycle_failed",
                    message="failed with secret-token and Telegram message text",
                    metadata={
                        "error_type": "RuntimeError",
                        "candidate_count": 3,
                        "raw": "secret-token",
                    },
                    created_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
                )
            ]
        )

        text = BotServices(runtime_event_repository=repository).logs()

        self.assertEqual(repository.calls, [("latest_events", 10)])
        self.assertIn("worker_cycle_failed", text)
        self.assertIn("RuntimeError", text)
        self.assertIn("candidate_count=3", text)
        self.assertNotIn("secret-token", text)
        self.assertNotIn("Telegram message text", text)
        self.assertNotIn("raw", text)

    def test_logs_returns_empty_message_when_no_events_exist(self):
        text = BotServices(runtime_event_repository=FakeRuntimeEventRepository()).logs()

        self.assertEqual(text, "No warning/error runtime events.")

    def test_logs_includes_allowlisted_lm_studio_diagnostics(self):
        repository = FakeRuntimeEventRepository(
            events=[
                RuntimeEvent(
                    runtime_event_id=11,
                    component="worker",
                    severity="warning",
                    event_type="llm_failure",
                    message="raw private text",
                    metadata={
                        "error_type": "LMStudioError",
                        "endpoint_host": "127.0.0.1",
                        "endpoint_path": "/v1/chat/completions",
                        "transport_error_type": "URLError",
                        "timeout_seconds": 300.0,
                        "max_tokens": 8192,
                        "max_completion_tokens": 8192,
                        "failure_stage": "response_schema",
                        "response_keys": ["error", "object"],
                        "choices_count": 0,
                        "choice_keys": ["finish_reason", "message"],
                        "finish_reason": "length",
                        "message_keys": ["content", "role"],
                        "content_type": "str",
                        "content_length": 0,
                        "reasoning_content_length": 120,
                    },
                    created_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
                )
            ]
        )

        text = BotServices(runtime_event_repository=repository).logs()

        self.assertIn("endpoint_host=127.0.0.1", text)
        self.assertIn("endpoint_path=/v1/chat/completions", text)
        self.assertIn("transport_error_type=URLError", text)
        self.assertIn("timeout_seconds=300.0", text)
        self.assertIn("max_tokens=8192", text)
        self.assertIn("max_completion_tokens=8192", text)
        self.assertIn("failure_stage=response_schema", text)
        self.assertIn("response_keys=['error', 'object']", text)
        self.assertIn("choices_count=0", text)
        self.assertIn("choice_keys=['finish_reason', 'message']", text)
        self.assertIn("finish_reason=length", text)
        self.assertIn("message_keys=['content', 'role']", text)
        self.assertIn("content_type=str", text)
        self.assertIn("content_length=0", text)
        self.assertIn("reasoning_content_length=120", text)
        self.assertNotIn("raw private text", text)

    def test_health_formats_component_statuses(self):
        def health_report():
            return HealthReport(
                status=HealthStatus.DEGRADED,
                components=(
                    ComponentHealth("postgres", HealthStatus.OK, {"database": "connected"}),
                    ComponentHealth("lm_studio", HealthStatus.DOWN, {"error": "URLError"}),
                ),
            )

        text = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            health_report_provider=health_report,
        ).health()

        self.assertIn("Health: degraded", text)
        self.assertIn("postgres: ok database=connected", text)
        self.assertIn("lm_studio: down error=URLError", text)

    def test_settings_returns_safe_message_when_not_configured(self):
        services = BotServices(runtime_event_repository=FakeRuntimeEventRepository())

        self.assertEqual(services.settings().text, "Settings service is not configured.")

    def test_summary_groups_items_and_includes_navigation_buttons(self):
        query = FakeSummaryQueryRepository(
            [
                make_task(item_id="task-1", item_type=ItemType.TASK, title="Send report"),
                make_task(item_id="commitment-1", item_type=ItemType.COMMITMENT, title="Call Alice"),
                make_task(item_id="wait-1", item_type=ItemType.WAITING_FOR, title="Waiting for invoice"),
                make_task(item_id="thought-1", item_type=ItemType.THOUGHT, title="Pricing concern"),
            ]
        )
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            summary_query_repository=query,
        )

        response = services.summary()

        self.assertEqual(query.calls, [("list_summary_items", 20)])
        self.assertIn("Summary:", response.text)
        self.assertIn("Tasks and commitments:", response.text)
        self.assertIn("Send report", response.text)
        self.assertIn("Call Alice", response.text)
        self.assertIn("Waiting:", response.text)
        self.assertIn("Waiting for invoice", response.text)
        self.assertIn("Thoughts:", response.text)
        self.assertIn("Pricing concern", response.text)
        self.assertEqual(
            response.reply_markup["inline_keyboard"][-1],
            [
                {"text": "Refresh", "callback_data": "menu:summary:0"},
                {"text": "Help", "callback_data": "menu:help:0"},
            ],
        )

    def test_summary_returns_empty_message_when_no_items_exist(self):
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            summary_query_repository=FakeSummaryQueryRepository(),
        )

        response = services.summary()

        self.assertEqual(response.text, "No summary items yet.")
        self.assertIsNotNone(response.reply_markup)

    def test_help_lists_commands_with_main_menu_buttons(self):
        services = BotServices(runtime_event_repository=FakeRuntimeEventRepository())

        response = services.help()

        self.assertIn("Commands:", response.text)
        for command in (
            "/summary",
            "/tasks",
            "/review",
            "/backfill",
            "/blacklist",
            "/settings",
            "/health",
            "/logs",
        ):
            self.assertIn(command, response.text)
        self.assertEqual(
            response.reply_markup,
            {
                "inline_keyboard": [
                    [
                        {"text": "Summary", "callback_data": "menu:summary:0"},
                        {"text": "Tasks", "callback_data": "menu:tasks:0"},
                    ],
                    [
                        {"text": "Review", "callback_data": "menu:review:0"},
                        {"text": "Backfill", "callback_data": "menu:backfill:0"},
                    ],
                    [
                        {"text": "Health", "callback_data": "menu:health:0"},
                        {"text": "Logs", "callback_data": "menu:logs:0"},
                    ],
                    [
                        {"text": "Settings", "callback_data": "menu:settings:0"},
                        {"text": "Help", "callback_data": "menu:help:0"},
                    ],
                ]
            },
        )

    def test_tasks_lists_open_items_with_status_action_buttons(self):
        query = FakeItemQueryRepository(
            [
                make_task(item_id="task-1", title="Send report"),
                make_task(
                    item_id="task-2",
                    item_type=ItemType.COMMITMENT,
                    title="Call back",
                    status=ItemStatus.WAITING_FOR,
                ),
            ]
        )
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            item_query_repository=query,
        )

        response = services.tasks()

        self.assertEqual(query.calls, [("list_open_tasks", 10)])
        self.assertIn("Open tasks:", response.text)
        self.assertIn("1. Send report [task/open]", response.text)
        self.assertIn("2. Call back [commitment/waiting_for]", response.text)
        self.assertEqual(
            response.reply_markup,
            {
                "inline_keyboard": [
                    [
                        {"text": "Done 1", "callback_data": "status:completed:task-1"},
                        {"text": "Partial 1", "callback_data": "status:partially_completed:task-1"},
                        {"text": "Cancel 1", "callback_data": "status:cancelled:task-1"},
                    ],
                    [
                        {"text": "Done 2", "callback_data": "status:completed:task-2"},
                        {"text": "Partial 2", "callback_data": "status:partially_completed:task-2"},
                        {"text": "Cancel 2", "callback_data": "status:cancelled:task-2"},
                    ],
                    [{"text": "Menu", "callback_data": "menu:help:0"}],
                ]
            },
        )

    def test_tasks_returns_empty_message_when_no_open_items_exist(self):
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            item_query_repository=FakeItemQueryRepository(),
        )

        response = services.tasks()

        self.assertEqual(response.text, "No open tasks.")
        self.assertIsNone(response.reply_markup)

    def test_review_lists_pending_entries_with_action_buttons(self):
        entry = ReviewEntry(
            review_id=7,
            review_type="item",
            state="pending",
            reason="Low confidence.",
            payload={"confidence": 0.5},
            created_at=datetime(2026, 6, 3, 8, 0, tzinfo=UTC),
            item=make_task(item_id="item-1", title="Send report", status=ItemStatus.CANDIDATE),
        )
        repository = FakeReviewRepository([entry])
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            review_repository=repository,
        )

        response = services.review()

        self.assertEqual(repository.calls, [("list_pending_reviews", 5)])
        self.assertIn("Pending reviews:", response.text)
        self.assertIn("#7 item", response.text)
        self.assertIn("Send report", response.text)
        self.assertEqual(
            response.reply_markup["inline_keyboard"][0],
            [
                {"text": "Approve 1", "callback_data": "review:approve:7"},
                {"text": "Reject 1", "callback_data": "review:reject:7"},
            ],
        )

    def test_review_returns_empty_message_when_no_entries_exist(self):
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            review_repository=FakeReviewRepository(),
        )

        response = services.review()

        self.assertEqual(response.text, "No pending reviews.")
        self.assertIsNotNone(response.reply_markup)

    def test_review_callback_dispatches_approve_and_reject(self):
        repository = FakeReviewRepository()
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            review_repository=repository,
        )

        approve = services.handle_review_callback("approve", "7")
        reject = services.handle_review_callback("reject", "8")

        self.assertEqual(approve, "Review approved.")
        self.assertEqual(reject, "Review rejected.")
        self.assertEqual(repository.calls, [("approve_review", 7), ("reject_review", 8)])

    def test_backfill_shows_presets_and_latest_jobs(self):
        now = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
        jobs = FakeBackfillJobQueryRepository(
            [
                BackfillJobSummary(
                    backfill_job_id=3,
                    status="completed",
                    from_date=now,
                    to_date=now,
                    error="",
                    created_at=now,
                )
            ]
        )
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            backfill_job_query_repository=jobs,
        )

        response = services.backfill()

        self.assertEqual(jobs.calls, [("latest_jobs", 3)])
        self.assertIn("Backfill:", response.text)
        self.assertIn("Last jobs:", response.text)
        self.assertEqual(
            [button["callback_data"] for button in response.reply_markup["inline_keyboard"][0]],
            ["bf:d:1", "bf:d:5", "bf:d:10"],
        )
        self.assertEqual(
            [button["callback_data"] for button in response.reply_markup["inline_keyboard"][1]],
            ["bf:d:15", "bf:d:30", "bf:d:90"],
        )

    def test_blacklist_shows_listener_policy_from_settings_snapshot(self):
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            settings_snapshot=FakeSettingsSnapshot(),
        )

        response = services.blacklist()

        self.assertIn("Listener policy:", response.text)
        self.assertIn("allowed_channel_ids=777", response.text)
        self.assertIn("denied_chat_ids=888", response.text)
        self.assertNotIn("api_hash", response.text.lower())

    def test_settings_shows_allowlisted_non_secret_values(self):
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            settings_snapshot=FakeSettingsSnapshot(),
        )

        response = services.settings()

        self.assertIn("Settings:", response.text)
        self.assertIn("account_id=owner", response.text)
        self.assertIn("lm_studio_model=qwen2.5", response.text)
        self.assertNotIn("token", response.text.lower())
        self.assertNotIn("api_hash", response.text.lower())
        self.assertNotIn("database_url", response.text.lower())

    def test_backfill_period_callback_shows_six_chat_choices(self):
        chats = FakeChatQueryRepository(
            [
                BackfillChatChoice(chat_id=1001, title="Alice", chat_type="private"),
                BackfillChatChoice(chat_id=1002, title="Project", chat_type="supergroup"),
            ]
        )
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            chat_query_repository=chats,
        )

        response = services.handle_backfill_callback("d", "30")

        self.assertEqual(chats.calls, [("list_backfill_chats", 0, 6)])
        self.assertIn("Backfill: choose chat", response.text)
        self.assertIn("Alice", response.text)
        self.assertEqual(response.reply_markup["inline_keyboard"][0][0]["callback_data"], "bf:c:30:0:1001")

    def test_backfill_chat_page_callback_has_previous_and_next_buttons(self):
        chats = FakeChatQueryRepository(
            [BackfillChatChoice(chat_id=chat_id, title=f"Chat {chat_id}", chat_type="private") for chat_id in range(12)]
        )
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            chat_query_repository=chats,
        )

        response = services.handle_backfill_callback("p", "30:1")

        self.assertEqual(chats.calls, [("list_backfill_chats", 1, 6)])
        buttons = response.reply_markup["inline_keyboard"][-1]
        self.assertEqual(buttons[0]["callback_data"], "bf:p:30:0")
        self.assertEqual(buttons[1]["callback_data"], "bf:p:30:2")

    def test_backfill_chat_selection_shows_confirmation(self):
        chats = FakeChatQueryRepository([BackfillChatChoice(chat_id=1001, title="Alice", chat_type="private")])
        now = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            chat_query_repository=chats,
            clock=lambda: now,
        )

        response = services.handle_backfill_callback("c", "30:0:1001")

        self.assertEqual(chats.calls, [("get_backfill_chat", 1001)])
        self.assertIn("Confirm backfill", response.text)
        self.assertIn("Alice", response.text)
        self.assertIn("2026-05-07T09:00:00+00:00", response.text)
        self.assertEqual(response.reply_markup["inline_keyboard"][0][0]["callback_data"], "bf:start:30:1001")

    def test_backfill_start_creates_pending_job(self):
        chats = FakeChatQueryRepository([BackfillChatChoice(chat_id=1001, title="Alice", chat_type="private")])
        jobs = FakeBackfillJobRepository()
        now = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            chat_query_repository=chats,
            backfill_job_query_repository=jobs,
            backfill_job_repository=jobs,
            clock=lambda: now,
        )

        response = services.handle_backfill_callback("start", "30:1001")

        self.assertEqual(jobs.created_jobs[0]["chat_id"], 1001)
        self.assertEqual(jobs.created_jobs[0]["chat_title"], "Alice")
        self.assertEqual(jobs.created_jobs[0]["from_date"].isoformat(), "2026-05-07T09:00:00+00:00")
        self.assertIn("Backfill job #99 created", response.text)
        self.assertEqual(response.reply_markup["inline_keyboard"][0][0]["callback_data"], "bf:status:99")

    def test_backfill_cancel_requests_cancellation(self):
        jobs = FakeBackfillJobRepository()
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            backfill_job_repository=jobs,
        )

        response = services.handle_backfill_callback("cancel", "7")

        self.assertEqual(jobs.cancelled_jobs, [7])
        self.assertIn("cancel requested", response)

    def test_backfill_status_returns_safe_job_details(self):
        jobs = FakeBackfillJobRepository(
            [
                make_backfill_record(
                    backfill_job_id=7,
                    chat_title="Alice",
                    status="failed",
                    last_error_type="TimeoutError",
                )
            ]
        )
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            backfill_job_repository=jobs,
        )

        response = services.handle_backfill_callback("status", "7")

        self.assertIn("Backfill job #7", response.text)
        self.assertIn("TimeoutError", response.text)
        self.assertNotIn("secret", response.text.lower())

    def test_status_callback_applies_allowed_status_change(self):
        items = FakeItemRepository()
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            item_repository=items,
        )

        text = services.handle_status_callback("completed", "task-1")

        self.assertEqual(text, "Status updated: completed")
        self.assertEqual(
            items.status_changes,
            [
                {
                    "item_id": "task-1",
                    "new_status": ItemStatus.COMPLETED,
                    "rationale": "Updated from bot callback.",
                }
            ],
        )

    def test_status_callback_rejects_unknown_status_without_database_write(self):
        items = FakeItemRepository()
        services = BotServices(
            runtime_event_repository=FakeRuntimeEventRepository(),
            item_repository=items,
        )

        text = services.handle_status_callback("unknown", "task-1")

        self.assertEqual(text, "Unknown status action.")
        self.assertEqual(items.status_changes, [])


if __name__ == "__main__":
    unittest.main()
