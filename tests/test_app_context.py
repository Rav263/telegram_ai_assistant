import asyncio
import unittest

from telegram_ai_assistant.app_context import AppContext
from telegram_ai_assistant.config import Settings


class FakeConnectionFactory:
    def __init__(self):
        self.opened = 0
        self.connection_obj = FakeConnection()

    def connection(self):
        self.opened += 1
        return self.connection_obj


class FakeConnection:
    def __init__(self):
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True
        return False


class AppContextTests(unittest.TestCase):
    def test_construction_does_not_open_database_connection(self):
        factory = FakeConnectionFactory()
        settings = make_settings()

        AppContext(settings=settings, connection_factory=factory)

        self.assertEqual(factory.opened, 0)

    def test_migrate_opens_connection_and_applies_schema(self):
        factory = FakeConnectionFactory()
        applied_to = []
        context = AppContext(
            settings=make_settings(),
            connection_factory=factory,
            schema_applier=applied_to.append,
        )

        context.migrate()

        self.assertEqual(factory.opened, 1)
        self.assertEqual(applied_to, [factory.connection_obj])

    def test_run_ingestor_once_builds_service_with_settings(self):
        factory = FakeConnectionFactory()
        captured = {}

        class FakeIngestor:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def run_once(self):
                return "result"

        context = AppContext(
            settings=make_settings(),
            connection_factory=factory,
            ingestor_factory=FakeIngestor,
            telegram_client_factory=lambda settings: "client-factory",
        )

        result = asyncio.run(context.run_ingestor_once())

        self.assertEqual(result, "result")
        self.assertEqual(captured["account_id"], "owner")
        self.assertEqual(captured["chat_id"], 1001)
        self.assertEqual(captured["limit"], 100)
        self.assertEqual(captured["bootstrap_mode"], "recent")
        self.assertEqual(captured["bootstrap_days"], 30)
        self.assertIs(captured["connection_factory"], factory)
        self.assertEqual(captured["client_factory"], "client-factory")


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
