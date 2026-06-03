from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.bot_services import BotServices
from telegram_ai_assistant.domain import RuntimeEvent


class FakeRuntimeEventRepository:
    def __init__(self, events=()):
        self.events = list(events)
        self.calls = []

    def latest_events(self, *, limit):
        self.calls.append(("latest_events", limit))
        return self.events[:limit]


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


if __name__ == "__main__":
    unittest.main()
