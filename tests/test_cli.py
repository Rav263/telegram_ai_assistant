import io
import logging
import unittest
from contextlib import redirect_stderr, redirect_stdout

from telegram_ai_assistant.cli import build_parser, main


VALID_ENV = {
    "TELEGRAM_API_ID": "123",
    "TELEGRAM_API_HASH": "hash",
    "TELEGRAM_BOT_TOKEN": "bot-token",
    "TELEGRAM_ALLOWED_USER_ID": "456",
    "TELEGRAM_SESSION_PATH": ".local/telegram-owner.session",
    "TELEGRAM_INGEST_ACCOUNT_ID": "owner",
    "TELEGRAM_INGEST_CHAT_ID": "1001",
    "DATABASE_URL": "postgresql://localhost/telegram_ai",
    "LM_STUDIO_MAX_TOKENS": "1024",
    "LM_STUDIO_CONTEXT_LENGTH": "8192",
}


class CLITests(unittest.TestCase):
    def tearDown(self):
        logging.basicConfig(level=logging.WARNING, force=True)

    def test_parses_version_command(self):
        args = build_parser().parse_args(["version"])

        self.assertEqual(args.command, "version")

    def test_parses_global_log_level(self):
        args = build_parser().parse_args(["--log-level", "debug", "run", "listener"])

        self.assertEqual(args.log_level, "DEBUG")
        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "listener")

    def test_parses_run_worker_command(self):
        args = build_parser().parse_args(["run", "worker"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "worker")
        self.assertFalse(args.once)

    def test_parses_run_worker_once_command(self):
        args = build_parser().parse_args(["run", "worker", "--once"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "worker")
        self.assertTrue(args.once)

    def test_rejects_once_for_non_worker_processes(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit):
            build_parser().parse_args(["run", "listener", "--once"])

    def test_parses_run_backfill_command(self):
        args = build_parser().parse_args(["run", "backfill"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "backfill")

    def test_parses_run_listener_command(self):
        args = build_parser().parse_args(["run", "listener"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "listener")

    def test_parses_health_offline_command(self):
        args = build_parser().parse_args(["health", "--offline"])

        self.assertEqual(args.command, "health")
        self.assertTrue(args.offline)

    def test_parses_migrate_command(self):
        args = build_parser().parse_args(["migrate"])

        self.assertEqual(args.command, "migrate")

    def test_version_command_returns_success(self):
        exit_code = main(["version"])

        self.assertEqual(exit_code, 0)

    def test_health_offline_command_returns_success(self):
        exit_code = main(["health", "--offline"])

        self.assertEqual(exit_code, 0)

    def test_run_command_accepts_injected_runner(self):
        calls = []

        def runner(settings):
            calls.append(settings.telegram_ingest_chat_id)
            return 9

        exit_code = main(
            ["run", "ingestor"],
            environ=VALID_ENV,
            runners={"ingestor": runner},
        )

        self.assertEqual(exit_code, 9)
        self.assertEqual(calls, [1001])

    def test_run_command_log_level_argument_overrides_environment(self):
        calls = []

        def runner(settings):
            calls.append(settings.log_level)
            return 0

        exit_code = main(
            ["--log-level", "debug", "run", "ingestor"],
            environ={**VALID_ENV, "LOG_LEVEL": "ERROR"},
            runners={"ingestor": runner},
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["DEBUG"])

    def test_run_worker_once_passes_once_flag_to_runner(self):
        calls = []

        def runner(settings, *, once=False):
            calls.append(once)
            return 0

        exit_code = main(
            ["run", "worker", "--once"],
            environ=VALID_ENV,
            runners={"worker": runner},
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [True])

    def test_logs_go_to_stderr_without_replacing_stdout_payloads(self):
        def runner(settings):
            import logging

            logging.getLogger("telegram_ai_assistant.test").debug("debug line")
            print("stdout payload")
            return 0

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(
                ["--log-level", "debug", "run", "ingestor"],
                environ=VALID_ENV,
                runners={"ingestor": runner},
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("stdout payload", stdout.getvalue())
        self.assertNotIn("debug line", stdout.getvalue())
        self.assertIn("debug line", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
