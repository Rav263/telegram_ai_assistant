import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.app_context import (
    AppContext,
    default_bot_api_factory,
    default_lm_studio_client_factory,
    default_telegram_client_factory,
)
from telegram_ai_assistant.config import ConfigError, Settings
from telegram_ai_assistant.worker import WorkerResult


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
        self.committed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True
        return False

    def commit(self):
        self.committed = True


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

    def test_run_backfill_once_builds_service_with_settings(self):
        factory = FakeConnectionFactory()
        captured = {}

        class FakeBackfillService:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def run_once(self):
                return "result"

        context = AppContext(
            settings=make_settings(),
            connection_factory=factory,
            backfill_factory=FakeBackfillService,
            telegram_client_factory=lambda settings: "client-factory",
        )

        result = asyncio.run(context.run_backfill_once())

        self.assertEqual(result, "result")
        self.assertEqual(captured["account_id"], "owner")
        self.assertEqual(captured["chat_id"], 1001)
        self.assertEqual(captured["start_at"], datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
        self.assertEqual(captured["end_at"], datetime(2026, 6, 1, 0, 0, tzinfo=UTC))
        self.assertIsNone(captured["before_message_id"])
        self.assertEqual(captured["limit"], 500)
        self.assertIs(captured["connection_factory"], factory)
        self.assertEqual(captured["client_factory"], "client-factory")

    def test_run_backfill_once_requires_backfill_window_settings(self):
        factory = FakeConnectionFactory()
        context = AppContext(
            settings=replace(make_settings(), telegram_backfill_start_at=None),
            connection_factory=factory,
        )

        with self.assertRaises(ConfigError):
            asyncio.run(context.run_backfill_once())

        self.assertEqual(factory.opened, 0)

    def test_run_listener_forever_builds_service_with_settings(self):
        factory = FakeConnectionFactory()
        captured = {}

        class FakeListener:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def run_forever(self):
                return "result"

        settings = replace(
            make_settings(),
            telegram_listener_allowed_channel_ids=frozenset({-100111}),
            telegram_listener_denied_chat_ids=frozenset({1002}),
        )
        context = AppContext(
            settings=settings,
            connection_factory=factory,
            listener_factory=FakeListener,
            telegram_client_factory=lambda settings: "client-factory",
        )

        result = asyncio.run(context.run_listener_forever())

        self.assertEqual(result, "result")
        self.assertEqual(captured["account_id"], "owner")
        self.assertEqual(captured["policy"].allowed_channel_ids, frozenset({-100111}))
        self.assertEqual(captured["policy"].denied_chat_ids, frozenset({1002}))
        self.assertIs(captured["connection_factory"], factory)
        self.assertEqual(captured["client_factory"], "client-factory")
        self.assertEqual(captured["backfill_job_runner"].__class__.__name__, "ConnectionScopedBackfillJobRunner")
        self.assertEqual(captured["backfill_batch_size"], 25)
        self.assertEqual(factory.opened, 0)

    def test_run_worker_once_builds_worker_with_repositories_and_settings(self):
        factory = FakeConnectionFactory()
        captured = {}

        class FakeWorker:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def process_messages(self, *, limit):
                captured["message_limit"] = limit
                return WorkerResult(scored_messages=2, queued_candidates=1)

            def process_candidates(self, *, limit):
                captured["candidate_limit"] = limit
                return WorkerResult(processed_candidates=1, extracted_items=1, saved_items=1)

        context = AppContext(
            settings=make_settings(),
            connection_factory=factory,
            worker_factory=FakeWorker,
            lm_studio_client_factory=lambda settings: "llm-client",
        )

        result = context.run_worker_once()

        self.assertEqual(result.scored_messages, 2)
        self.assertEqual(result.queued_candidates, 1)
        self.assertEqual(result.processed_candidates, 1)
        self.assertEqual(result.extracted_items, 1)
        self.assertEqual(result.saved_items, 1)
        self.assertEqual(result.backfill_jobs, 0)
        self.assertEqual(result.backfill_saved_messages, 0)
        self.assertEqual(captured["message_limit"], 25)
        self.assertEqual(captured["candidate_limit"], 25)
        self.assertEqual(captured["item_auto_apply_threshold"], 0.8)
        self.assertEqual(captured["status_auto_apply_threshold"], 0.8)
        self.assertEqual(captured["extraction_service"]._llm_client, "llm-client")
        self.assertEqual(captured["message_source"].__class__.__name__, "MessageProcessingRepository")
        self.assertEqual(captured["runtime_event_repository"].__class__.__name__, "RuntimeEventRepository")
        self.assertNotIn("backfill_job_runner", captured)
        self.assertEqual(factory.opened, 1)
        self.assertTrue(factory.connection_obj.exited)

    def test_run_bot_forever_builds_owner_only_runtime(self):
        factory = FakeConnectionFactory()
        captured = {}

        class FakeBotRuntime:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run_forever(self, *, stop_requested=None):
                captured["stop_requested"] = stop_requested
                return "bot-result"

        context = AppContext(
            settings=make_settings(),
            connection_factory=factory,
            bot_api_factory=lambda settings: "bot-api",
            bot_runtime_factory=FakeBotRuntime,
        )
        stop_requested = lambda: True

        result = context.run_bot_forever(stop_requested=stop_requested)

        self.assertEqual(result, "bot-result")
        self.assertEqual(captured["bot_api"], "bot-api")
        self.assertEqual(captured["router"].access.allowed_user_id, 456)
        self.assertEqual(captured["router"].bot_api, "bot-api")
        self.assertEqual(captured["router"].services.runtime_event_repository.__class__.__name__, "RuntimeEventRepository")
        self.assertEqual(captured["router"].services.item_query_repository.__class__.__name__, "ItemQueryRepository")
        self.assertEqual(captured["router"].services.item_repository.__class__.__name__, "ItemRepository")
        self.assertEqual(captured["router"].services.summary_query_repository.__class__.__name__, "ItemQueryRepository")
        self.assertEqual(captured["router"].services.review_repository.__class__.__name__, "ReviewRepository")
        self.assertEqual(
            captured["router"].services.backfill_job_query_repository.__class__.__name__,
            "BackfillJobRepository",
        )
        self.assertEqual(captured["router"].services.backfill_job_repository.__class__.__name__, "BackfillJobRepository")
        self.assertEqual(captured["router"].services.chat_query_repository.__class__.__name__, "ChatQueryRepository")
        self.assertEqual(captured["router"].services.settings_snapshot.lm_studio_model, "local-model")
        self.assertEqual(captured["runtime_event_repository"].__class__.__name__, "RuntimeEventRepository")
        self.assertEqual(captured["state_repository"].__class__.__name__, "BotRuntimeStateRepository")
        self.assertEqual(captured["commit"], factory.connection_obj.commit)
        self.assertIs(captured["stop_requested"], stop_requested)
        self.assertEqual(factory.opened, 1)
        self.assertTrue(factory.connection_obj.exited)

    def test_default_lm_studio_client_factory_uses_available_settings(self):
        client = default_lm_studio_client_factory(make_settings())

        self.assertEqual(client.base_url, "http://127.0.0.1:1234/v1")
        self.assertEqual(client.model, "local-model")
        self.assertEqual(client.max_tokens, 8192)

    def test_default_bot_api_factory_uses_proxy_url(self):
        api = default_bot_api_factory(
            replace(
                make_settings(),
                telegram_bot_proxy_url="http://proxy.local:8080",
            )
        )

        self.assertEqual(api.token, "bot")
        self.assertEqual(api.proxy_url, "http://proxy.local:8080")

    def test_default_lm_studio_client_factory_uses_configured_model(self):
        settings = replace(
            make_settings(),
            lm_studio_model="qwen2.5-7b-instruct",
            lm_studio_max_tokens=16384,
        )

        client = default_lm_studio_client_factory(settings)

        self.assertEqual(client.model, "qwen2.5-7b-instruct")
        self.assertEqual(client.max_tokens, 16384)

    def test_default_telegram_client_factory_passes_mtproxy_settings(self):
        from telegram_ai_assistant import app_context

        captured = {}
        original_adapter = app_context.TelethonIngestionAdapter
        original_mtproxy_client_kwargs = app_context.mtproxy_client_kwargs

        class FakeTelethonIngestionAdapter:
            @staticmethod
            def connect(session, api_id, api_hash, **kwargs):
                captured.update(
                    {
                        "session": session,
                        "api_id": api_id,
                        "api_hash": api_hash,
                        "kwargs": kwargs,
                    }
                )
                return "telegram-client"

        def fake_mtproxy_client_kwargs(*, host, port, secret):
            captured["mtproxy_settings"] = (host, port, secret)
            return {"proxy": "mtproxy"}

        app_context.TelethonIngestionAdapter = FakeTelethonIngestionAdapter
        app_context.mtproxy_client_kwargs = fake_mtproxy_client_kwargs
        try:
            factory = default_telegram_client_factory(
                replace(
                    make_settings(),
                    telegram_mtproxy_host="proxy.local",
                    telegram_mtproxy_port=443,
                    telegram_mtproxy_secret="ddsecret",
                )
            )
            result = factory()
        finally:
            app_context.TelethonIngestionAdapter = original_adapter
            app_context.mtproxy_client_kwargs = original_mtproxy_client_kwargs

        self.assertEqual(result, "telegram-client")
        self.assertEqual(captured["session"], ".local/telegram-owner.session")
        self.assertEqual(captured["api_id"], 123)
        self.assertEqual(captured["api_hash"], "hash")
        self.assertEqual(captured["mtproxy_settings"], ("proxy.local", 443, "ddsecret"))
        self.assertEqual(captured["kwargs"], {"proxy": "mtproxy"})


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
        telegram_backfill_chat_id=1001,
        telegram_backfill_start_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        telegram_backfill_end_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
    )


if __name__ == "__main__":
    unittest.main()
