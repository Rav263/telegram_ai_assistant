import unittest

from telegram_ai_assistant.app_context import AppContext
from telegram_ai_assistant.config import Settings
from telegram_ai_assistant.health import (
    HealthStatus,
    lm_studio_health_check,
    postgres_health_check,
)


class FakeConnectionFactory:
    def __init__(self):
        self.connection_obj = FakeConnection()

    def connection(self):
        return self.connection_obj


class FakeConnection:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement):
        self.executed.append(statement)
        return FakeCursor()


class FakeCursor:
    def fetchone(self):
        return (1,)


class FailingConnectionFactory:
    def connection(self):
        return FailingConnection()


class FailingConnection:
    def __enter__(self):
        raise RuntimeError("could not connect with password=secret")

    def __exit__(self, exc_type, exc, traceback):
        return False


class OnlineHealthTests(unittest.TestCase):
    def test_postgres_health_check_runs_select_one(self):
        factory = FakeConnectionFactory()

        component = postgres_health_check(factory)

        self.assertEqual(component.name, "postgres")
        self.assertEqual(component.status, HealthStatus.OK)
        self.assertEqual(factory.connection_obj.executed, ["SELECT 1"])

    def test_postgres_health_check_reports_failure_without_secret_values(self):
        component = postgres_health_check(FailingConnectionFactory())

        self.assertEqual(component.name, "postgres")
        self.assertEqual(component.status, HealthStatus.DOWN)
        self.assertEqual(component.details["error"], "RuntimeError")
        self.assertNotIn("secret", str(component.details))

    def test_lm_studio_health_check_uses_models_endpoint(self):
        requested_urls = []

        def transport(url):
            requested_urls.append(url)
            return b'{"data": [{"id": "local-model"}]}'

        component = lm_studio_health_check("http://127.0.0.1:1234/v1", transport)

        self.assertEqual(component.name, "lm_studio")
        self.assertEqual(component.status, HealthStatus.OK)
        self.assertEqual(component.details["models"], "1")
        self.assertEqual(requested_urls, ["http://127.0.0.1:1234/v1/models"])

    def test_app_context_online_health_report_checks_postgres_and_lm_studio(self):
        context = AppContext(
            settings=make_settings(),
            connection_factory=FakeConnectionFactory(),
            health_transport=lambda url: b'{"data": []}',
        )

        report = context.online_health_report()

        self.assertEqual(report.status, HealthStatus.OK)
        self.assertEqual(report.component("postgres").status, HealthStatus.OK)
        self.assertEqual(report.component("lm_studio").status, HealthStatus.OK)


def make_settings() -> Settings:
    return Settings(
        telegram_api_id=123,
        telegram_api_hash="hash",
        telegram_bot_token="bot",
        telegram_allowed_user_id=456,
        database_url="postgresql://localhost/db",
    )


if __name__ == "__main__":
    unittest.main()
