import unittest

from telegram_ai_assistant.config import Settings
from telegram_ai_assistant.runtime import PROCESS_NAMES, offline_health_report, run_process


class RuntimeTests(unittest.TestCase):
    def test_run_process_dispatches_to_injected_runner(self):
        settings = Settings(
            telegram_api_id=123,
            telegram_api_hash="hash",
            telegram_bot_token="bot",
            telegram_allowed_user_id=456,
            database_url="postgresql://localhost/db",
        )
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


if __name__ == "__main__":
    unittest.main()
