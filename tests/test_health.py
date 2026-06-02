import unittest

from telegram_ai_assistant.health import ComponentHealth, HealthChecker, HealthStatus


class HealthCheckerTests(unittest.TestCase):
    def test_reports_ok_when_all_components_are_ok(self):
        checker = HealthChecker(
            {
                "postgres": lambda: ComponentHealth(
                    name="postgres",
                    status=HealthStatus.OK,
                    details={"database": "connected"},
                ),
                "lm_studio": lambda: ComponentHealth(
                    name="lm_studio",
                    status=HealthStatus.OK,
                    details={"endpoint": "available"},
                ),
            }
        )

        report = checker.check()

        self.assertEqual(report.status, HealthStatus.OK)
        self.assertEqual(report.component("postgres").details["database"], "connected")
        self.assertEqual(report.component("lm_studio").status, HealthStatus.OK)

    def test_reports_degraded_when_any_component_is_degraded(self):
        checker = HealthChecker(
            {
                "ingestion": lambda: ComponentHealth(
                    name="ingestion",
                    status=HealthStatus.DEGRADED,
                    details={"lag": "15m"},
                ),
                "worker": lambda: ComponentHealth(
                    name="worker",
                    status=HealthStatus.OK,
                    details={"queue": "empty"},
                ),
            }
        )

        report = checker.check()

        self.assertEqual(report.status, HealthStatus.DEGRADED)
        self.assertEqual(report.component("ingestion").details["lag"], "15m")

    def test_reports_down_when_component_fails(self):
        def failing_bot_check():
            raise RuntimeError("bot token rejected")

        checker = HealthChecker(
            {
                "bot": failing_bot_check,
                "postgres": lambda: ComponentHealth(
                    name="postgres",
                    status=HealthStatus.OK,
                    details={"database": "connected"},
                ),
            }
        )

        report = checker.check()

        self.assertEqual(report.status, HealthStatus.DOWN)
        self.assertEqual(report.component("bot").status, HealthStatus.DOWN)
        self.assertEqual(report.component("bot").details["error"], "bot token rejected")


if __name__ == "__main__":
    unittest.main()
