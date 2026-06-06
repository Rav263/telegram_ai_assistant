import asyncio
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.ingestion.backfill import BackfillService


class FakeConnectionFactory:
    def __init__(self):
        self.connection_obj = FakeConnection()

    def connection(self):
        return self.connection_obj


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeAccountRepository:
    def __init__(self, connection):
        self.accounts = []

    def ensure_account(self, account_id, telegram_user_id=None, display_name=""):
        self.accounts.append((account_id, telegram_user_id, display_name))


class FakeChatRepository:
    def __init__(self, connection):
        self.chats = []
        self.updated_cursor = None

    def ensure_chat(self, account_id, chat_id, title="", chat_type=""):
        self.chats.append((account_id, chat_id, title, chat_type))

    def update_ingestion_cursor(self, account_id, chat_id, last_message_id, ingested_at):
        self.updated_cursor = (account_id, chat_id, last_message_id, ingested_at)


class FakeMessageRepository:
    def __init__(self, connection):
        self.messages = []

    def upsert_message(self, message):
        self.messages.append(message)


class FakeBackfillClient:
    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []

    async def iter_backfill_messages(
        self,
        chat_id,
        *,
        start_at,
        end_at,
        before_message_id=None,
        limit=None,
    ):
        self.calls.append(
            {
                "chat_id": chat_id,
                "start_at": start_at,
                "end_at": end_at,
                "before_message_id": before_message_id,
                "limit": limit,
            }
        )
        for message in self.messages:
            yield message

    async def close(self):
        self.calls.append({"method": "close"})


class RawMessage:
    def __init__(self, message_id, text, date):
        self.id = message_id
        self.chat_id = 1001
        self.sender_id = 3001
        self.date = date
        self.message = text
        self.out = False


class BackfillServiceTests(unittest.TestCase):
    def test_run_once_saves_historical_messages_without_moving_live_cursor(self):
        start_at = datetime(2022, 1, 1, tzinfo=UTC)
        end_at = datetime(2022, 2, 1, tzinfo=UTC)
        client = FakeBackfillClient(
            [
                RawMessage(30, "newest old message", datetime(2022, 1, 20, tzinfo=UTC)),
                RawMessage(20, "oldest old message", datetime(2022, 1, 5, tzinfo=UTC)),
            ]
        )
        service, repositories = make_service(
            client=client,
            start_at=start_at,
            end_at=end_at,
            before_message_id=500,
        )

        result = asyncio.run(service.run_once())

        self.assertEqual(
            client.calls,
            [
                {
                    "chat_id": 1001,
                    "start_at": start_at,
                    "end_at": end_at,
                    "before_message_id": 500,
                    "limit": 10,
                },
                {"method": "close"},
            ],
        )
        self.assertEqual(repositories.account.accounts, [("owner", None, "")])
        self.assertEqual(repositories.chat.chats, [("owner", 1001, "", "")])
        self.assertIsNone(repositories.chat.updated_cursor)
        self.assertEqual(
            repositories.messages.messages,
            [
                Message(
                    account_id="owner",
                    chat_id=1001,
                    telegram_message_id=30,
                    sender_id=3001,
                    direction=MessageDirection.INCOMING,
                    sent_at=datetime(2022, 1, 20, tzinfo=UTC),
                    text="newest old message",
                ),
                Message(
                    account_id="owner",
                    chat_id=1001,
                    telegram_message_id=20,
                    sender_id=3001,
                    direction=MessageDirection.INCOMING,
                    sent_at=datetime(2022, 1, 5, tzinfo=UTC),
                    text="oldest old message",
                ),
            ],
        )
        self.assertEqual(result.account_id, "owner")
        self.assertEqual(result.chat_id, 1001)
        self.assertEqual(result.saved_count, 2)
        self.assertEqual(result.requested_before_message_id, 500)
        self.assertEqual(result.next_before_message_id, 20)
        self.assertEqual(result.oldest_sent_at, datetime(2022, 1, 5, tzinfo=UTC))
        self.assertEqual(result.newest_sent_at, datetime(2022, 1, 20, tzinfo=UTC))

    def test_run_once_closes_client_when_normalization_fails(self):
        client = FakeBackfillClient(
            [RawMessage(30, "bad", datetime(2022, 1, 20, tzinfo=UTC))]
        )

        def failing_normalizer(account_id, raw_message):
            raise ValueError("bad raw message")

        service, _repositories = make_service(client=client, normalizer=failing_normalizer)

        with self.assertRaises(ValueError):
            asyncio.run(service.run_once())

        self.assertIn({"method": "close"}, client.calls)

    def test_run_once_with_client_does_not_close_externally_owned_client(self):
        start_at = datetime(2022, 1, 1, tzinfo=UTC)
        end_at = datetime(2022, 2, 1, tzinfo=UTC)
        client = FakeBackfillClient(
            [RawMessage(30, "newest old message", datetime(2022, 1, 20, tzinfo=UTC))]
        )
        service, repositories = make_service(
            client=client,
            start_at=start_at,
            end_at=end_at,
            before_message_id=None,
        )

        result = asyncio.run(service.run_once_with_client(client))

        self.assertEqual(result.saved_count, 1)
        self.assertEqual(
            client.calls,
            [
                {
                    "chat_id": 1001,
                    "start_at": start_at,
                    "end_at": end_at,
                    "before_message_id": None,
                    "limit": 10,
                }
            ],
        )
        self.assertEqual(len(repositories.messages.messages), 1)


class RepositoryBundle:
    def __init__(self, account, chat, messages):
        self.account = account
        self.chat = chat
        self.messages = messages


def make_service(client, normalizer=None, start_at=None, end_at=None, before_message_id=None):
    connection_factory = FakeConnectionFactory()
    repositories = RepositoryBundle(
        account=FakeAccountRepository(connection_factory.connection_obj),
        chat=FakeChatRepository(connection_factory.connection_obj),
        messages=FakeMessageRepository(connection_factory.connection_obj),
    )
    kwargs = {
        "account_id": "owner",
        "chat_id": 1001,
        "start_at": start_at or datetime(2022, 1, 1, tzinfo=UTC),
        "end_at": end_at or datetime(2022, 2, 1, tzinfo=UTC),
        "before_message_id": before_message_id,
        "limit": 10,
        "connection_factory": connection_factory,
        "client_factory": lambda: client,
        "account_repository_factory": lambda connection: repositories.account,
        "chat_repository_factory": lambda connection: repositories.chat,
        "message_repository_factory": lambda connection: repositories.messages,
    }
    if normalizer is not None:
        kwargs["normalizer"] = normalizer
    return BackfillService(**kwargs), repositories


if __name__ == "__main__":
    unittest.main()
