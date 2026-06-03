import unittest

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
}


class CLITests(unittest.TestCase):
    def test_parses_version_command(self):
        args = build_parser().parse_args(["version"])

        self.assertEqual(args.command, "version")

    def test_parses_run_worker_command(self):
        args = build_parser().parse_args(["run", "worker"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "worker")

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


if __name__ == "__main__":
    unittest.main()
