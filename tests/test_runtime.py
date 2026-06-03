import io
from contextlib import redirect_stdout
from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.config import Settings
from telegram_ai_assistant.domain import MessageDirection
from telegram_ai_assistant.ingestion.backfill import BackfillRunResult
from telegram_ai_assistant.ingestion.listener import ListenerRunResult
from telegram_ai_assistant.ingestion.live import IngestedMessageDebug, IngestionRunResult
from telegram_ai_assistant.runtime import (
    PROCESS_NAMES,
    offline_health_report,
    run_backfill,
    run_ingestor,
    run_listener,
    run_process,
    run_worker,
)
from telegram_ai_assistant.worker import WorkerResult


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
        self.assertEqual(
            PROCESS_NAMES,
            ("ingestor", "backfill", "listener", "worker", "bot", "scheduler", "all"),
        )

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
                    bootstrap_mode="cursor",
                    oldest_sent_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
                    newest_sent_at=datetime(2026, 6, 2, 9, 2, tzinfo=UTC),
                )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FakeContext())

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run"])
        self.assertIn('"saved_count": 2', output.getvalue())
        self.assertIn('"latest_message_id": 202', output.getvalue())
        self.assertIn('"bootstrap_mode": "cursor"', output.getvalue())
        self.assertIn('"oldest_sent_at": "2026-06-02T09:01:00+00:00"', output.getvalue())
        self.assertIn('"newest_sent_at": "2026-06-02T09:02:00+00:00"', output.getvalue())
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
        with self.assertLogs("telegram_ai_assistant.runtime", level="ERROR"):
            with redirect_stdout(output):
                exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FailingContext())

        self.assertEqual(exit_code, 1)
        self.assertIn("ingestor failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())

    def test_run_backfill_executes_context_and_prints_result(self):
        calls = []

        class FakeContext:
            async def run_backfill_once(self):
                calls.append("run")
                return BackfillRunResult(
                    account_id="owner",
                    chat_id=1001,
                    start_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
                    end_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
                    requested_before_message_id=None,
                    next_before_message_id=900,
                    saved_count=3,
                    oldest_sent_at=datetime(2026, 5, 2, 9, 1, tzinfo=UTC),
                    newest_sent_at=datetime(2026, 5, 31, 9, 2, tzinfo=UTC),
                )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_backfill(make_settings(), context_factory=lambda settings: FakeContext())

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run"])
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["account_id"], "owner")
        self.assertEqual(payload["chat_id"], 1001)
        self.assertEqual(payload["start_at"], "2026-05-01T00:00:00+00:00")
        self.assertEqual(payload["end_at"], "2026-06-01T00:00:00+00:00")
        self.assertIsNone(payload["requested_before_message_id"])
        self.assertEqual(payload["next_before_message_id"], 900)
        self.assertEqual(payload["saved_count"], 3)
        self.assertEqual(payload["oldest_sent_at"], "2026-05-02T09:01:00+00:00")
        self.assertEqual(payload["newest_sent_at"], "2026-05-31T09:02:00+00:00")

    def test_run_backfill_failure_returns_nonzero_without_secret_values(self):
        class FailingContext:
            async def run_backfill_once(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with self.assertLogs("telegram_ai_assistant.runtime", level="ERROR"):
            with redirect_stdout(output):
                exit_code = run_backfill(make_settings(), context_factory=lambda settings: FailingContext())

        self.assertEqual(exit_code, 1)
        self.assertIn("backfill failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())

    def test_run_listener_executes_context_and_prints_startup_result(self):
        calls = []

        class FakeContext:
            async def run_listener_forever(self):
                calls.append("run")
                return ListenerRunResult(account_id="owner", status="stopped")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_listener(make_settings(), context_factory=lambda settings: FakeContext())

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run"])
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["process"], "listener")
        self.assertEqual(payload["account_id"], "owner")
        self.assertEqual(payload["status"], "stopped")

    def test_run_listener_failure_returns_nonzero_without_secret_values(self):
        class FailingContext:
            async def run_listener_forever(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with self.assertLogs("telegram_ai_assistant.runtime", level="ERROR") as logs:
            with redirect_stdout(output):
                exit_code = run_listener(make_settings(), context_factory=lambda settings: FailingContext())

        log_output = "\n".join(logs.output)
        self.assertEqual(exit_code, 1)
        self.assertIn("listener failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())
        self.assertIn("listener failed", log_output)
        self.assertIn("RuntimeError", log_output)
        self.assertNotIn("secret-token", log_output)

    def test_run_ingestor_failure_logs_error_without_secret_values(self):
        class FailingContext:
            async def run_ingestor_once(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with self.assertLogs("telegram_ai_assistant.runtime", level="ERROR") as logs:
            with redirect_stdout(output):
                exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FailingContext())

        log_output = "\n".join(logs.output)
        self.assertEqual(exit_code, 1)
        self.assertIn("ingestor failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())
        self.assertIn("ingestor failed", log_output)
        self.assertIn("RuntimeError", log_output)
        self.assertNotIn("secret-token", log_output)

    def test_run_backfill_failure_logs_error_without_secret_values(self):
        class FailingContext:
            async def run_backfill_once(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with self.assertLogs("telegram_ai_assistant.runtime", level="ERROR") as logs:
            with redirect_stdout(output):
                exit_code = run_backfill(make_settings(), context_factory=lambda settings: FailingContext())

        log_output = "\n".join(logs.output)
        self.assertEqual(exit_code, 1)
        self.assertIn("backfill failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())
        self.assertIn("backfill failed", log_output)
        self.assertIn("RuntimeError", log_output)
        self.assertNotIn("secret-token", log_output)

    def test_run_listener_success_logs_process_lifecycle(self):
        class FakeContext:
            async def run_listener_forever(self):
                return ListenerRunResult(account_id="owner", status="stopped")

        output = io.StringIO()
        with self.assertLogs("telegram_ai_assistant.runtime", level="INFO") as logs:
            with redirect_stdout(output):
                exit_code = run_listener(make_settings(), context_factory=lambda settings: FakeContext())

        log_output = "\n".join(logs.output)
        self.assertEqual(exit_code, 0)
        self.assertIn("listener started", log_output)
        self.assertIn("listener stopped", log_output)

    def test_run_worker_once_executes_context_and_prints_result(self):
        calls = []

        class FakeContext:
            def run_worker_once(self):
                calls.append("run")
                return WorkerResult(
                    scored_messages=2,
                    queued_candidates=1,
                    processed_candidates=1,
                    extracted_items=1,
                    saved_items=1,
                    review_items=0,
                    review_status_changes=0,
                    failures=0,
                )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_worker(
                make_settings(),
                once=True,
                context_factory=lambda settings: FakeContext(),
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run"])
        self.assertEqual(payload["process"], "worker")
        self.assertEqual(payload["scored_messages"], 2)
        self.assertEqual(payload["queued_candidates"], 1)
        self.assertEqual(payload["processed_candidates"], 1)
        self.assertEqual(payload["saved_items"], 1)

    def test_run_worker_daemon_repeats_until_stop_requested_without_stdout(self):
        calls = []
        sleeps = []

        class FakeContext:
            def run_worker_once(self):
                calls.append("run")
                return WorkerResult(scored_messages=1)

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_worker(
                make_settings(),
                once=False,
                context_factory=lambda settings: FakeContext(),
                sleep=sleeps.append,
                stop_requested=lambda: len(calls) >= 2,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run", "run"])
        self.assertEqual(sleeps, [10])
        self.assertEqual(output.getvalue(), "")

    def test_run_worker_failure_returns_nonzero_without_secret_values(self):
        class FailingContext:
            def run_worker_once(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with self.assertLogs("telegram_ai_assistant.runtime", level="ERROR") as logs:
            with redirect_stdout(output):
                exit_code = run_worker(
                    make_settings(),
                    once=True,
                    context_factory=lambda settings: FailingContext(),
                )

        log_output = "\n".join(logs.output)
        self.assertEqual(exit_code, 1)
        self.assertIn("worker failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())
        self.assertIn("worker failed", log_output)
        self.assertIn("RuntimeError", log_output)
        self.assertNotIn("secret-token", log_output)


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
        telegram_backfill_chat_id=1001,
        telegram_backfill_start_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        telegram_backfill_end_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
    )


if __name__ == "__main__":
    unittest.main()
