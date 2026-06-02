import unittest

from telegram_ai_assistant.config import ConfigError, Settings


VALID_ENV = {
    "TELEGRAM_API_ID": "123",
    "TELEGRAM_API_HASH": "hash",
    "TELEGRAM_BOT_TOKEN": "bot-token",
    "TELEGRAM_ALLOWED_USER_ID": "456",
    "TELEGRAM_SESSION_PATH": "/tmp/telegram.session",
    "TELEGRAM_INGEST_ACCOUNT_ID": "account-1",
    "TELEGRAM_INGEST_CHAT_ID": "789",
    "DATABASE_URL": "postgresql://localhost/telegram_ai",
}


class SettingsTests(unittest.TestCase):
    def test_loads_required_settings_and_defaults(self):
        settings = Settings.from_env(VALID_ENV)

        self.assertEqual(settings.telegram_api_id, 123)
        self.assertEqual(settings.telegram_api_hash, "hash")
        self.assertEqual(settings.telegram_bot_token, "bot-token")
        self.assertEqual(settings.telegram_allowed_user_id, 456)
        self.assertEqual(settings.telegram_session_path, "/tmp/telegram.session")
        self.assertEqual(settings.telegram_ingest_account_id, "account-1")
        self.assertEqual(settings.telegram_ingest_chat_id, 789)
        self.assertEqual(settings.telegram_ingest_limit, 100)
        self.assertEqual(settings.database_url, "postgresql://localhost/telegram_ai")
        self.assertEqual(settings.lm_studio_base_url, "http://127.0.0.1:1234/v1")
        self.assertEqual(settings.backfill_days, 30)

    def test_loads_optional_lm_studio_backfill_and_ingest_limit_values(self):
        env = {
            **VALID_ENV,
            "LM_STUDIO_BASE_URL": "http://lmstudio.local:1234/v1",
            "BACKFILL_DAYS": "14",
            "TELEGRAM_INGEST_LIMIT": "25",
        }

        settings = Settings.from_env(env)

        self.assertEqual(settings.lm_studio_base_url, "http://lmstudio.local:1234/v1")
        self.assertEqual(settings.backfill_days, 14)
        self.assertEqual(settings.telegram_ingest_limit, 25)

    def test_raises_when_required_setting_is_missing(self):
        env = dict(VALID_ENV)
        del env["TELEGRAM_API_HASH"]

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_session_path_is_missing(self):
        env = dict(VALID_ENV)
        del env["TELEGRAM_SESSION_PATH"]

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_ingest_account_id_is_missing(self):
        env = dict(VALID_ENV)
        del env["TELEGRAM_INGEST_ACCOUNT_ID"]

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_ingest_chat_id_is_missing(self):
        env = dict(VALID_ENV)
        del env["TELEGRAM_INGEST_CHAT_ID"]

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_ingest_chat_id_is_not_an_integer(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_INGEST_CHAT_ID": "not-an-int",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_ingest_limit_is_not_an_integer(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_INGEST_LIMIT": "not-an-int",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)


if __name__ == "__main__":
    unittest.main()
