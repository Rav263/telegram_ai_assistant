import asyncio
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.ingestion.live import LiveIngestor


class FakeConnectionFactory:
    def __init__(self):
        self.connection_obj = FakeConnection()

    def connection(self):
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


class FakeAccountRepository:
    def __init__(self, connection):
        self.connection = connection
        self.accounts = []

    def ensure_account(self, account_id, telegram_user_id=None, display_name=""):
        self.accounts.append((account_id, telegram_user_id, display_name))


class FakeChatRepository:
    def __init__(self, connection, *, cursor):
        self.connection = connection
        self.cursor = cursor
        self.chats = []
        self.updated_cursor = None

    def ensure_chat(self, account_id, chat_id, title="", chat_type=""):
        self.chats.append((account_id, chat_id, title, chat_type))

    def get_last_ingested_message_id(self, account_id, chat_id):
        return self.cursor

    def update_ingestion_cursor(self, account_id, chat_id, last_message_id, ingested_at):
        self.updated_cursor = (account_id, chat_id, last_message_id, ingested_at)


class FakeMessageRepository:
    def __init__(self, connection):
        self.connection = connection
        self.messages = []

    def upsert_message(self, message):
        self.messages.append(message)


class FakeIngestionClient:
    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []

    async def iter_new_messages(self, chat_id, *, min_id=None, limit=None):
        self.calls.append(("iter_new_messages", chat_id, min_id, limit))
        for message in self.messages:
            yield message

    async def close(self):
        self.calls.append(("close",))


class RawMessage:
    def __init__(self, message_id, text):
        self.id = message_id
        self.chat_id = 1001
        self.sender_id = 3001
        self.date = datetime(2026, 6, 2, 9, message_id - 200, tzinfo=UTC)
        self.message = text
        self.out = False


class LiveIngestorTests(unittest.TestCase):
    def test_run_once_reads_cursor_saves_messages_and_updates_cursor(self):
        client = FakeIngestionClient(
            [
                RawMessage(201, "first unread message"),
                RawMessage(202, "second unread message"),
            ]
        )
        ingestor, repositories = make_ingestor(client=client)

        result = asyncio.run(ingestor.run_once())

        self.assertEqual(client.calls, [("iter_new_messages", 1001, 200, 10), ("close",)])
        self.assertEqual(repositories.account.accounts, [("owner", None, "")])
        self.assertEqual(repositories.chat.chats, [("owner", 1001, "", "")])
        self.assertEqual(
            repositories.messages.messages,
            [
                Message(
                    account_id="owner",
                    chat_id=1001,
                    telegram_message_id=201,
                    sender_id=3001,
                    direction=MessageDirection.INCOMING,
                    sent_at=datetime(2026, 6, 2, 9, 1, tzinfo=UTC),
                    text="first unread message",
                ),
                Message(
                    account_id="owner",
                    chat_id=1001,
                    telegram_message_id=202,
                    sender_id=3001,
                    direction=MessageDirection.INCOMING,
                    sent_at=datetime(2026, 6, 2, 9, 2, tzinfo=UTC),
                    text="second unread message",
                ),
            ],
        )
        self.assertEqual(
            repositories.chat.updated_cursor,
            ("owner", 1001, 202, datetime(2026, 6, 2, 10, 0, tzinfo=UTC)),
        )
        self.assertEqual(result.account_id, "owner")
        self.assertEqual(result.chat_id, 1001)
        self.assertEqual(result.requested_min_id, 200)
        self.assertEqual(result.saved_count, 2)
        self.assertEqual(result.latest_message_id, 202)

    def test_run_once_does_not_move_cursor_when_no_messages_are_saved(self):
        client = FakeIngestionClient([])
        ingestor, repositories = make_ingestor(client=client)

        result = asyncio.run(ingestor.run_once())

        self.assertEqual(client.calls, [("iter_new_messages", 1001, 200, 10), ("close",)])
        self.assertIsNone(repositories.chat.updated_cursor)
        self.assertEqual(result.saved_count, 0)
        self.assertEqual(result.latest_message_id, 200)

    def test_run_once_closes_client_and_leaves_cursor_unchanged_when_normalization_fails(self):
        client = FakeIngestionClient([RawMessage(201, "bad")])

        def failing_normalizer(account_id, raw_message):
            raise ValueError("bad raw message")

        ingestor, repositories = make_ingestor(client=client, normalizer=failing_normalizer)

        with self.assertRaises(ValueError):
            asyncio.run(ingestor.run_once())

        self.assertIn(("close",), client.calls)
        self.assertIsNone(repositories.chat.updated_cursor)


class RepositoryBundle:
    def __init__(self, account, chat, messages):
        self.account = account
        self.chat = chat
        self.messages = messages


def make_ingestor(client, normalizer=None):
    connection_factory = FakeConnectionFactory()
    repositories = RepositoryBundle(
        account=FakeAccountRepository(connection_factory.connection_obj),
        chat=FakeChatRepository(connection_factory.connection_obj, cursor=200),
        messages=FakeMessageRepository(connection_factory.connection_obj),
    )

    kwargs = {
        "account_id": "owner",
        "chat_id": 1001,
        "limit": 10,
        "connection_factory": connection_factory,
        "client_factory": lambda: client,
        "account_repository_factory": lambda connection: repositories.account,
        "chat_repository_factory": lambda connection: repositories.chat,
        "message_repository_factory": lambda connection: repositories.messages,
        "now": lambda: datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
    }
    if normalizer is not None:
        kwargs["normalizer"] = normalizer
    return LiveIngestor(**kwargs), repositories


if __name__ == "__main__":
    unittest.main()
