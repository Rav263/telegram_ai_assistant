from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.bot_services import BotServices
from telegram_ai_assistant.domain import ExtractedItem, ItemStatus, ItemType, RuntimeEvent, SourceRef
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


class FakeItemRepository:
    def __init__(self):
        self.status_changes = []

    def apply_status_change(self, change):
        self.status_changes.append(change)


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
                    },
                    created_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
                )
            ]
        )

        text = BotServices(runtime_event_repository=repository).logs()

        self.assertIn("endpoint_host=127.0.0.1", text)
        self.assertIn("endpoint_path=/v1/chat/completions", text)
        self.assertIn("transport_error_type=URLError", text)
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

    def test_unimplemented_commands_return_stable_message(self):
        services = BotServices(runtime_event_repository=FakeRuntimeEventRepository())

        self.assertEqual(services.summary(), "Command /summary is not implemented yet.")

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
