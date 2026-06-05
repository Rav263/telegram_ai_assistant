import asyncio
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.ingestion.ports import ReadOnlyIngestionClient
from telegram_ai_assistant.ingestion.telethon_adapter import TelethonIngestionAdapter, mtproxy_client_kwargs
from telegram_ai_assistant.telegram_readonly import MutatingTelegramMethodError, ReadOnlyTelegramGuard


class FakeTelegramClient:
    def __init__(self):
        self.calls = []
        self.messages = ["first", "second"]
        self.latest_message = FakeMessage(42)
        self.event_handlers = []
        self.disconnected_waited = False

    async def iter_messages(
        self,
        chat_id,
        *,
        limit=None,
        min_id=None,
        max_id=None,
        offset_date=None,
        reverse=False,
    ):
        self.calls.append(("iter_messages", chat_id, limit, min_id, max_id, offset_date, reverse))
        for message in self.messages:
            yield message

    async def get_messages(self, chat_id, *, limit=None):
        self.calls.append(("get_messages", chat_id, limit))
        if limit == 1:
            return [self.latest_message]
        return list(self.messages)

    async def get_me(self):
        self.calls.append(("get_me",))
        return {"id": 1}

    async def disconnect(self):
        self.calls.append(("disconnect",))

    async def send_message(self, chat_id, text):
        self.calls.append(("send_message", chat_id, text))

    def add_event_handler(self, handler, event):
        self.calls.append(("add_event_handler", event.__class__.__name__))
        self.event_handlers.append((handler, event))

    async def run_until_disconnected(self):
        self.calls.append(("run_until_disconnected",))
        self.disconnected_waited = True


class FakeMessage:
    def __init__(self, message_id, date=None):
        self.id = message_id
        self.date = date


class FakeNewMessageEvent:
    pass


class FakeTelethonClient(FakeTelegramClient):
    instances = []

    def __init__(self, session, api_id, api_hash, **kwargs):
        super().__init__()
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.kwargs = kwargs
        self.connected = False
        self.instances.append(self)

    async def connect(self):
        self.connected = True


async def collect(async_iterable):
    return [item async for item in async_iterable]


class ReadOnlyIngestionClientTests(unittest.TestCase):
    def test_iter_history_and_new_messages_call_allowed_iter_messages(self):
        fake_client = FakeTelegramClient()
        client = ReadOnlyIngestionClient(fake_client, guard=ReadOnlyTelegramGuard())

        history_messages = asyncio.run(collect(client.iter_history(chat_id=1001, limit=2)))
        new_messages = asyncio.run(collect(client.iter_new_messages(chat_id=1001, min_id=40, limit=10)))

        self.assertEqual(history_messages, ["first", "second"])
        self.assertEqual(new_messages, ["first", "second"])
        self.assertEqual(
            fake_client.calls,
            [
                ("iter_messages", 1001, 2, None, None, None, False),
                ("iter_messages", 1001, 10, 40, None, None, True),
            ],
        )

    def test_recent_messages_and_latest_id_use_read_only_retrieval_methods(self):
        fake_client = FakeTelegramClient()
        client = ReadOnlyIngestionClient(fake_client, guard=ReadOnlyTelegramGuard())
        since = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)

        recent_messages = asyncio.run(collect(client.iter_recent_messages(chat_id=1001, since=since, limit=10)))
        latest_message_id = asyncio.run(client.get_latest_message_id(chat_id=1001))

        self.assertEqual(recent_messages, ["first", "second"])
        self.assertEqual(latest_message_id, 42)
        self.assertEqual(
            fake_client.calls,
            [
                ("iter_messages", 1001, 10, None, None, since, True),
                ("get_messages", 1001, 1),
            ],
        )

    def test_backfill_messages_use_date_range_and_stop_at_start_bound(self):
        start_at = datetime(2022, 1, 1, tzinfo=UTC)
        end_at = datetime(2022, 2, 1, tzinfo=UTC)
        fake_client = FakeTelegramClient()
        fake_client.messages = [
            FakeMessage(30, datetime(2022, 1, 20, tzinfo=UTC)),
            FakeMessage(20, datetime(2022, 1, 5, tzinfo=UTC)),
            FakeMessage(10, datetime(2021, 12, 31, tzinfo=UTC)),
        ]
        client = ReadOnlyIngestionClient(fake_client, guard=ReadOnlyTelegramGuard())

        messages = asyncio.run(
            collect(
                client.iter_backfill_messages(
                    chat_id=1001,
                    start_at=start_at,
                    end_at=end_at,
                    before_message_id=500,
                    limit=100,
                )
            )
        )

        self.assertEqual([message.id for message in messages], [30, 20])
        self.assertEqual(
            fake_client.calls,
            [
                ("iter_messages", 1001, 100, None, 500, end_at, False),
            ],
        )

    def test_backfill_without_before_message_id_uses_telethon_default_max_id(self):
        start_at = datetime(2022, 1, 1, tzinfo=UTC)
        end_at = datetime(2022, 2, 1, tzinfo=UTC)
        fake_client = FakeTelegramClient()
        fake_client.messages = [FakeMessage(30, datetime(2022, 1, 20, tzinfo=UTC))]
        client = ReadOnlyIngestionClient(fake_client, guard=ReadOnlyTelegramGuard())

        messages = asyncio.run(
            collect(
                client.iter_backfill_messages(
                    chat_id=1001,
                    start_at=start_at,
                    end_at=end_at,
                    limit=100,
                )
            )
        )

        self.assertEqual([message.id for message in messages], [30])
        self.assertEqual(
            fake_client.calls,
            [
                ("iter_messages", 1001, 100, None, 0, end_at, False),
            ],
        )

    def test_allowed_call_and_close_call_through(self):
        fake_client = FakeTelegramClient()
        client = ReadOnlyIngestionClient(fake_client)

        identity = asyncio.run(client.call("get_me"))
        asyncio.run(client.close())

        self.assertEqual(identity, {"id": 1})
        self.assertEqual(fake_client.calls, [("get_me",), ("disconnect",)])

    def test_listen_new_messages_registers_allowed_handler_and_waits_until_disconnected(self):
        fake_client = FakeTelegramClient()
        client = ReadOnlyIngestionClient(
            fake_client,
            guard=ReadOnlyTelegramGuard(),
            new_message_event_factory=FakeNewMessageEvent,
        )

        async def handler(update):
            return None

        asyncio.run(client.listen_new_messages(handler))
        asyncio.run(client.run_until_disconnected())

        self.assertEqual(len(fake_client.event_handlers), 1)
        self.assertIs(fake_client.event_handlers[0][0], handler)
        self.assertIsInstance(fake_client.event_handlers[0][1], FakeNewMessageEvent)
        self.assertEqual(
            fake_client.calls[-2:],
            [("add_event_handler", "FakeNewMessageEvent"), ("run_until_disconnected",)],
        )

    def test_mutating_call_is_rejected_before_fake_client_is_called(self):
        fake_client = FakeTelegramClient()
        client = ReadOnlyIngestionClient(fake_client)

        with self.assertRaises(MutatingTelegramMethodError):
            asyncio.run(client.call("send_message", 1001, "hello"))

        self.assertEqual(fake_client.calls, [])


class TelethonIngestionAdapterTests(unittest.TestCase):
    def test_mtproxy_client_kwargs_builds_telethon_proxy_configuration(self):
        from telegram_ai_assistant.ingestion import telethon_adapter

        original_loader = telethon_adapter._load_mtproxy_connection

        class FakeMTProxyConnection:
            pass

        telethon_adapter._load_mtproxy_connection = lambda: FakeMTProxyConnection
        try:
            kwargs = mtproxy_client_kwargs(
                host="proxy.local",
                port=443,
                secret="ddsecret",
            )
        finally:
            telethon_adapter._load_mtproxy_connection = original_loader

        self.assertEqual(
            kwargs,
            {
                "connection": FakeMTProxyConnection,
                "proxy": ("proxy.local", 443, "ddsecret"),
            },
        )

    def test_mtproxy_client_kwargs_is_empty_without_host(self):
        self.assertEqual(mtproxy_client_kwargs(host="", port=0, secret=""), {})

    def test_connects_lazy_loaded_client_behind_read_only_guard(self):
        from telegram_ai_assistant.ingestion import telethon_adapter

        original_loader = telethon_adapter._load_telegram_client
        original_event_loader = telethon_adapter._load_new_message_event
        FakeTelethonClient.instances = []
        telethon_adapter._load_telegram_client = lambda: FakeTelethonClient
        telethon_adapter._load_new_message_event = lambda: FakeNewMessageEvent
        try:
            adapter = asyncio.run(
                TelethonIngestionAdapter.connect(
                    "session-name",
                    123,
                    "hash",
                    device_model="test-device",
                )
            )
        finally:
            telethon_adapter._load_telegram_client = original_loader
            telethon_adapter._load_new_message_event = original_event_loader

        fake_client = FakeTelethonClient.instances[0]
        self.assertIsInstance(adapter, TelethonIngestionAdapter)
        self.assertTrue(fake_client.connected)
        self.assertEqual(fake_client.session, "session-name")
        self.assertEqual(fake_client.kwargs, {"device_model": "test-device"})

        with self.assertRaises(MutatingTelegramMethodError):
            asyncio.run(adapter.call("send_message", 1001, "hello"))

        self.assertEqual(fake_client.calls, [])

    def test_telethon_adapter_loads_new_message_event_factory(self):
        from telegram_ai_assistant.ingestion import telethon_adapter

        original_loader = telethon_adapter._load_telegram_client
        original_event_loader = telethon_adapter._load_new_message_event
        FakeTelethonClient.instances = []

        class FakeLoadedNewMessageEvent:
            pass

        telethon_adapter._load_telegram_client = lambda: FakeTelethonClient
        telethon_adapter._load_new_message_event = lambda: FakeLoadedNewMessageEvent
        try:
            adapter = asyncio.run(
                TelethonIngestionAdapter.connect(
                    "session-name",
                    123,
                    "hash",
                )
            )
        finally:
            telethon_adapter._load_telegram_client = original_loader
            telethon_adapter._load_new_message_event = original_event_loader

        async def handler(update):
            return None

        asyncio.run(adapter.listen_new_messages(handler))

        fake_client = FakeTelethonClient.instances[0]
        self.assertEqual(fake_client.calls[-1], ("add_event_handler", "FakeLoadedNewMessageEvent"))


if __name__ == "__main__":
    unittest.main()
