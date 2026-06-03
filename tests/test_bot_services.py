from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.bot_services import BotServices
from telegram_ai_assistant.domain import RuntimeEvent
from telegram_ai_assistant.health import ComponentHealth, HealthReport, HealthStatus


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

        self.assertEqual(services.tasks(), "Command /tasks is not implemented yet.")
        self.assertEqual(services.summary(), "Command /summary is not implemented yet.")


if __name__ == "__main__":
    unittest.main()
