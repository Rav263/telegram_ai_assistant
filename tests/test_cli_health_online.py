import io
import json
from contextlib import redirect_stdout
import unittest

from telegram_ai_assistant.cli import main
from telegram_ai_assistant.health import ComponentHealth, HealthReport, HealthStatus


class FakeContext:
    def online_health_report(self):
        return HealthReport(
            status=HealthStatus.OK,
            components=(
                ComponentHealth("postgres", HealthStatus.OK, {"database": "connected"}),
                ComponentHealth("lm_studio", HealthStatus.OK, {"models": "1"}),
            ),
        )


class FailingContext:
    def online_health_report(self):
        raise RuntimeError("failed with secret-token")


class CLIHealthOnlineTests(unittest.TestCase):
    def test_health_command_uses_context_and_prints_report(self):
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["health"], context_factory=lambda environment: FakeContext())

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["components"][0]["name"], "postgres")

    def test_health_failure_returns_nonzero_without_secret_values(self):
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["health"], context_factory=lambda environment: FailingContext())

        self.assertEqual(exit_code, 1)
        self.assertIn("health check failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
