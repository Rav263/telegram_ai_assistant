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
