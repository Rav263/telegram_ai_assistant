import asyncio
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.ingestion.ports import ReadOnlyIngestionClient
from telegram_ai_assistant.ingestion.telethon_adapter import TelethonIngestionAdapter
from telegram_ai_assistant.telegram_readonly import MutatingTelegramMethodError, ReadOnlyTelegramGuard


class FakeTelegramClient:
    def __init__(self):
        self.calls = []
        self.messages = ["first", "second"]
        self.latest_message = FakeMessage(42)

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


class FakeMessage:
    def __init__(self, message_id, date=None):
        self.id = message_id
        self.date = date


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

    def test_mutating_call_is_rejected_before_fake_client_is_called(self):
        fake_client = FakeTelegramClient()
        client = ReadOnlyIngestionClient(fake_client)

        with self.assertRaises(MutatingTelegramMethodError):
            asyncio.run(client.call("send_message", 1001, "hello"))

        self.assertEqual(fake_client.calls, [])


class TelethonIngestionAdapterTests(unittest.TestCase):
    def test_connects_lazy_loaded_client_behind_read_only_guard(self):
        from telegram_ai_assistant.ingestion import telethon_adapter

        original_loader = telethon_adapter._load_telegram_client
        FakeTelethonClient.instances = []
        telethon_adapter._load_telegram_client = lambda: FakeTelethonClient
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

        fake_client = FakeTelethonClient.instances[0]
        self.assertIsInstance(adapter, TelethonIngestionAdapter)
        self.assertTrue(fake_client.connected)
        self.assertEqual(fake_client.session, "session-name")
        self.assertEqual(fake_client.kwargs, {"device_model": "test-device"})

        with self.assertRaises(MutatingTelegramMethodError):
            asyncio.run(adapter.call("send_message", 1001, "hello"))

        self.assertEqual(fake_client.calls, [])


if __name__ == "__main__":
    unittest.main()
