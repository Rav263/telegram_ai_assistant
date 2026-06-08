from datetime import UTC, datetime
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
        self.assertEqual(settings.telegram_bot_proxy_url, "")
        self.assertEqual(settings.telegram_allowed_user_id, 456)
        self.assertEqual(settings.telegram_session_path, "/tmp/telegram.session")
        self.assertEqual(settings.telegram_ingest_account_id, "account-1")
        self.assertEqual(settings.telegram_ingest_chat_id, 789)
        self.assertEqual(settings.telegram_ingest_limit, 100)
        self.assertFalse(settings.telegram_ingest_debug_messages)
        self.assertEqual(settings.telegram_ingest_bootstrap_mode, "recent")
        self.assertEqual(settings.telegram_ingest_bootstrap_days, 30)
        self.assertEqual(settings.telegram_mtproxy_host, "")
        self.assertEqual(settings.telegram_mtproxy_port, 0)
        self.assertEqual(settings.telegram_mtproxy_secret, "")
        self.assertEqual(settings.telegram_backfill_chat_id, 0)
        self.assertIsNone(settings.telegram_backfill_start_at)
        self.assertIsNone(settings.telegram_backfill_end_at)
        self.assertEqual(settings.telegram_backfill_limit, 500)
        self.assertEqual(settings.telegram_listener_allowed_channel_ids, frozenset())
        self.assertEqual(settings.telegram_listener_denied_chat_ids, frozenset())
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.worker_batch_size, 25)
        self.assertEqual(settings.worker_open_item_context_limit, 200)
        self.assertEqual(settings.worker_poll_interval_seconds, 10)
        self.assertEqual(settings.worker_item_auto_apply_threshold, 0.8)
        self.assertEqual(settings.worker_status_auto_apply_threshold, 0.8)
        self.assertEqual(settings.database_url, "postgresql://localhost/telegram_ai")
        self.assertEqual(settings.lm_studio_base_url, "http://127.0.0.1:1234/v1")
        self.assertEqual(settings.lm_studio_model, "local-model")
        self.assertEqual(settings.lm_studio_max_tokens, 8192)
        self.assertEqual(settings.lm_studio_context_length, 8192)
        self.assertEqual(settings.backfill_days, 30)

    def test_loads_optional_lm_studio_backfill_and_ingest_limit_values(self):
        env = {
            **VALID_ENV,
            "LM_STUDIO_BASE_URL": "http://lmstudio.local:1234/v1",
            "LM_STUDIO_MODEL": "qwen2.5-7b-instruct",
            "LM_STUDIO_MAX_TOKENS": "16384",
            "LM_STUDIO_CONTEXT_LENGTH": "32768",
            "TELEGRAM_BOT_PROXY_URL": "http://proxy.local:8080",
            "BACKFILL_DAYS": "14",
            "TELEGRAM_INGEST_LIMIT": "25",
            "TELEGRAM_INGEST_DEBUG_MESSAGES": "true",
            "TELEGRAM_INGEST_BOOTSTRAP_MODE": "start_now",
            "TELEGRAM_INGEST_BOOTSTRAP_DAYS": "7",
            "TELEGRAM_MTPROXY_HOST": "proxy.local",
            "TELEGRAM_MTPROXY_PORT": "443",
            "TELEGRAM_MTPROXY_SECRET": "ddsecret",
            "TELEGRAM_BACKFILL_CHAT_ID": "380453832",
            "TELEGRAM_BACKFILL_START_AT": "2022-01-01T00:00:00+00:00",
            "TELEGRAM_BACKFILL_END_AT": "2022-02-01T00:00:00+00:00",
            "TELEGRAM_BACKFILL_LIMIT": "250",
            "TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS": "-100111,-100222",
            "TELEGRAM_LISTENER_DENIED_CHAT_IDS": "123, 456",
            "LOG_LEVEL": "debug",
            "WORKER_BATCH_SIZE": "50",
            "WORKER_OPEN_ITEM_CONTEXT_LIMIT": "30",
            "WORKER_POLL_INTERVAL_SECONDS": "3",
            "WORKER_ITEM_AUTO_APPLY_THRESHOLD": "0.9",
            "WORKER_STATUS_AUTO_APPLY_THRESHOLD": "0.7",
        }

        settings = Settings.from_env(env)

        self.assertEqual(settings.lm_studio_base_url, "http://lmstudio.local:1234/v1")
        self.assertEqual(settings.lm_studio_model, "qwen2.5-7b-instruct")
        self.assertEqual(settings.lm_studio_max_tokens, 16384)
        self.assertEqual(settings.lm_studio_context_length, 32768)
        self.assertEqual(settings.telegram_bot_proxy_url, "http://proxy.local:8080")
        self.assertEqual(settings.backfill_days, 14)
        self.assertEqual(settings.telegram_ingest_limit, 25)
        self.assertTrue(settings.telegram_ingest_debug_messages)
        self.assertEqual(settings.telegram_ingest_bootstrap_mode, "start_now")
        self.assertEqual(settings.telegram_ingest_bootstrap_days, 7)
        self.assertEqual(settings.telegram_mtproxy_host, "proxy.local")
        self.assertEqual(settings.telegram_mtproxy_port, 443)
        self.assertEqual(settings.telegram_mtproxy_secret, "ddsecret")
        self.assertEqual(settings.telegram_backfill_chat_id, 380453832)
        self.assertEqual(
            settings.telegram_backfill_start_at,
            datetime(2022, 1, 1, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            settings.telegram_backfill_end_at,
            datetime(2022, 2, 1, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(settings.telegram_backfill_limit, 250)
        self.assertEqual(settings.telegram_listener_allowed_channel_ids, frozenset({-100111, -100222}))
        self.assertEqual(settings.telegram_listener_denied_chat_ids, frozenset({123, 456}))
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.worker_batch_size, 50)
        self.assertEqual(settings.worker_open_item_context_limit, 30)
        self.assertEqual(settings.worker_poll_interval_seconds, 3)
        self.assertEqual(settings.worker_item_auto_apply_threshold, 0.9)
        self.assertEqual(settings.worker_status_auto_apply_threshold, 0.7)

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

    def test_raises_when_telegram_ingest_debug_messages_is_not_a_boolean(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_INGEST_DEBUG_MESSAGES": "sometimes",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_ingest_bootstrap_mode_is_invalid(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_INGEST_BOOTSTRAP_MODE": "everything",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_ingest_bootstrap_days_is_not_positive(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_INGEST_BOOTSTRAP_DAYS": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_backfill_datetime_is_invalid(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_BACKFILL_START_AT": "not-a-date",
            "TELEGRAM_BACKFILL_END_AT": "2022-02-01T00:00:00+00:00",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_backfill_end_is_not_after_start(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_BACKFILL_START_AT": "2022-02-01T00:00:00+00:00",
            "TELEGRAM_BACKFILL_END_AT": "2022-01-01T00:00:00+00:00",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_backfill_limit_is_not_positive(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_BACKFILL_LIMIT": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_telegram_listener_id_list_is_invalid(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_LISTENER_DENIED_CHAT_IDS": "123,not-an-int",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_log_level_is_invalid(self):
        env = {
            **VALID_ENV,
            "LOG_LEVEL": "verbose",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_worker_batch_size_is_not_positive(self):
        env = {
            **VALID_ENV,
            "WORKER_BATCH_SIZE": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_worker_open_item_context_limit_is_not_positive(self):
        env = {
            **VALID_ENV,
            "WORKER_OPEN_ITEM_CONTEXT_LIMIT": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_mtproxy_config_is_partial(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_MTPROXY_HOST": "proxy.local",
            "TELEGRAM_MTPROXY_SECRET": "ddsecret",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_mtproxy_port_is_not_positive(self):
        env = {
            **VALID_ENV,
            "TELEGRAM_MTPROXY_HOST": "proxy.local",
            "TELEGRAM_MTPROXY_PORT": "0",
            "TELEGRAM_MTPROXY_SECRET": "ddsecret",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_lm_studio_max_tokens_is_not_positive(self):
        env = {
            **VALID_ENV,
            "LM_STUDIO_MAX_TOKENS": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_lm_studio_context_length_is_not_positive(self):
        env = {
            **VALID_ENV,
            "LM_STUDIO_CONTEXT_LENGTH": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_worker_poll_interval_is_not_positive(self):
        env = {
            **VALID_ENV,
            "WORKER_POLL_INTERVAL_SECONDS": "0",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_worker_threshold_is_not_a_float(self):
        env = {
            **VALID_ENV,
            "WORKER_ITEM_AUTO_APPLY_THRESHOLD": "high",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)

    def test_raises_when_worker_threshold_is_out_of_range(self):
        env = {
            **VALID_ENV,
            "WORKER_STATUS_AUTO_APPLY_THRESHOLD": "1.1",
        }

        with self.assertRaises(ConfigError):
            Settings.from_env(env)


if __name__ == "__main__":
    unittest.main()
