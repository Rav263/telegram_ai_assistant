import io
from contextlib import redirect_stdout
from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.config import Settings
from telegram_ai_assistant.domain import MessageDirection
from telegram_ai_assistant.ingestion.live import IngestedMessageDebug, IngestionRunResult
from telegram_ai_assistant.runtime import PROCESS_NAMES, offline_health_report, run_ingestor, run_process


class RuntimeTests(unittest.TestCase):
    def test_run_process_dispatches_to_injected_runner(self):
        settings = make_settings()
        calls = []

        def runner(received_settings):
            calls.append(received_settings)
            return 7

        exit_code = run_process("worker", settings, runners={"worker": runner})

        self.assertEqual(exit_code, 7)
        self.assertEqual(calls, [settings])

    def test_all_declared_processes_have_default_runners(self):
        self.assertEqual(PROCESS_NAMES, ("ingestor", "worker", "bot", "scheduler", "all"))

    def test_offline_health_report_contains_core_components(self):
        report = offline_health_report()

        self.assertEqual(report.status, "ok")
        self.assertEqual(
            [component.name for component in report.components],
            ["postgres", "lm_studio", "ingestor", "worker", "bot"],
        )

    def test_run_ingestor_executes_context_and_prints_result(self):
        calls = []

        class FakeContext:
            async def run_ingestor_once(self):
                calls.append("run")
                return IngestionRunResult(
                    account_id="owner",
                    chat_id=1001,
                    requested_min_id=200,
                    saved_count=2,
                    latest_message_id=202,
                )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FakeContext())

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run"])
        self.assertIn('"saved_count": 2', output.getvalue())
        self.assertIn('"latest_message_id": 202', output.getvalue())
        self.assertNotIn("debug_messages", output.getvalue())

    def test_run_ingestor_prints_debug_messages_when_result_contains_them(self):
        class FakeContext:
            async def run_ingestor_once(self):
                return IngestionRunResult(
                    account_id="owner",
                    chat_id=1001,
                    requested_min_id=200,
                    saved_count=1,
                    latest_message_id=201,
                    debug_messages=(
                        IngestedMessageDebug(
                            telegram_message_id=201,
                            sender_id=3001,
                            direction=MessageDirection.INCOMING,
                            sent_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
                            text="Не грузи деда",
                            caption="",
                        ),
                    ),
                )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FakeContext())

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            payload["debug_messages"],
            [
                {
                    "telegram_message_id": 201,
                    "sender_id": 3001,
                    "direction": "incoming",
                    "sent_at": "2026-06-02T09:01:00+00:00",
                    "text": "Не грузи деда",
                    "caption": "",
                }
            ],
        )
        self.assertIn("Не грузи деда", output.getvalue())
        self.assertNotIn("\\u041d", output.getvalue())

    def test_run_ingestor_failure_returns_nonzero_without_secret_values(self):
        class FailingContext:
            async def run_ingestor_once(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FailingContext())

        self.assertEqual(exit_code, 1)
        self.assertIn("ingestor failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())


def make_settings() -> Settings:
    return Settings(
        telegram_api_id=123,
        telegram_api_hash="hash",
        telegram_bot_token="bot",
        telegram_allowed_user_id=456,
        database_url="postgresql://localhost/db",
        telegram_session_path=".local/telegram-owner.session",
        telegram_ingest_account_id="owner",
        telegram_ingest_chat_id=1001,
    )


if __name__ == "__main__":
    unittest.main()
