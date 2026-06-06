import asyncio
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy, ChatMetadata
from telegram_ai_assistant.ingestion.listener import LiveUpdateListener


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
        self.cursor = 0
        self.updated_cursors = []

    def ensure_chat(self, account_id, chat_id, title="", chat_type=""):
        self.chats.append((account_id, chat_id, title, chat_type))

    def get_last_ingested_message_id(self, account_id, chat_id):
        return self.cursor

    def update_ingestion_cursor(self, account_id, chat_id, last_message_id, ingested_at):
        self.cursor = last_message_id
        self.updated_cursors.append((account_id, chat_id, last_message_id, ingested_at))


class FakeMessageRepository:
    def __init__(self, connection):
        self.messages = []

    def upsert_message(self, message):
        self.messages.append(message)


class FakeListenerClient:
    def __init__(self):
        self.handler = None
        self.calls = []

    async def listen_new_messages(self, handler):
        self.handler = handler
        self.calls.append("listen")

    async def run_until_disconnected(self):
        self.calls.append("run_until_disconnected")

    async def close(self):
        self.calls.append("close")


class FakeBackfillJobRunner:
    def __init__(self):
        self.calls = []

    async def run_once_with_client(self, *, limit, client):
        self.calls.append({"limit": limit, "client": client})


class WaitForBackfillPollsClient(FakeListenerClient):
    def __init__(self, runner, target_calls):
        super().__init__()
        self.runner = runner
        self.target_calls = target_calls

    async def run_until_disconnected(self):
        self.calls.append("run_until_disconnected")
        while len(self.runner.calls) < self.target_calls:
            await asyncio.sleep(0)


class FakeEvent:
    def __init__(self, raw_message, chat_metadata):
        self.message = raw_message
        self.chat_metadata = chat_metadata


class RawMessage:
    def __init__(self, message_id, chat_id=1001, text="hello"):
        self.id = message_id
        self.chat_id = chat_id
        self.sender_id = 3001
        self.date = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)
        self.message = text
        self.out = False


class RepositoryBundle:
    def __init__(self, account, chat, messages):
        self.account = account
        self.chat = chat
        self.messages = messages


class LiveUpdateListenerTests(unittest.TestCase):
    def test_run_forever_registers_handler_and_closes_client(self):
        client = FakeListenerClient()
        listener, _repositories = make_listener(client)

        result = asyncio.run(listener.run_forever())

        self.assertIsNotNone(client.handler)
        self.assertEqual(client.calls, ["listen", "run_until_disconnected", "close"])
        self.assertEqual(result.account_id, "owner")
        self.assertEqual(result.status, "stopped")

    def test_run_forever_registers_handler_and_polls_backfill_with_shared_client(self):
        client = FakeListenerClient()
        runner = FakeBackfillJobRunner()
        listener, _repositories = make_listener(
            client,
            backfill_job_runner=runner,
            backfill_batch_size=25,
        )

        result = asyncio.run(listener.run_forever())

        self.assertIsNotNone(client.handler)
        self.assertEqual(client.calls, ["listen", "run_until_disconnected", "close"])
        self.assertEqual(runner.calls, [{"limit": 25, "client": client}])
        self.assertEqual(result.status, "stopped")

    def test_run_forever_polls_backfill_periodically_while_connected(self):
        runner = FakeBackfillJobRunner()
        client = WaitForBackfillPollsClient(runner, target_calls=2)
        listener, _repositories = make_listener(
            client,
            backfill_job_runner=runner,
            backfill_batch_size=25,
            backfill_poll_interval_seconds=0,
        )

        result = asyncio.run(asyncio.wait_for(listener.run_forever(), timeout=1))

        self.assertEqual(result.status, "stopped")
        self.assertGreaterEqual(len(runner.calls), 2)
        self.assertTrue(all(call["client"] is client for call in runner.calls))

    def test_handler_saves_accepted_update_and_advances_cursor(self):
        client = FakeListenerClient()
        listener, repositories = make_listener(client)
        asyncio.run(listener.run_forever())

        with self.assertLogs("telegram_ai_assistant.ingestion.listener", level="INFO") as logs:
            asyncio.run(
                client.handler(
                    FakeEvent(
                        RawMessage(50, text="secret text"),
                        ChatMetadata(chat_id=1001, chat_type="private", title="Alice"),
                    )
                )
            )

        self.assertEqual(repositories.account.accounts, [("owner", None, "")])
        self.assertEqual(repositories.chat.chats, [("owner", 1001, "Alice", "private")])
        self.assertEqual(
            repositories.messages.messages,
            [
                Message(
                    account_id="owner",
                    chat_id=1001,
                    telegram_message_id=50,
                    sender_id=3001,
                    direction=MessageDirection.INCOMING,
                    sent_at=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                    text="secret text",
                )
            ],
        )
        self.assertEqual(repositories.chat.updated_cursors[-1][2], 50)
        log_output = "\n".join(logs.output)
        self.assertIn("saved live update", log_output)
        self.assertIn("chat_id=1001", log_output)
        self.assertIn("telegram_message_id=50", log_output)
        self.assertNotIn("secret text", log_output)

    def test_handler_does_not_move_cursor_backwards(self):
        client = FakeListenerClient()
        listener, repositories = make_listener(client)
        repositories.chat.cursor = 100
        asyncio.run(listener.run_forever())

        asyncio.run(
            client.handler(
                FakeEvent(
                    RawMessage(50),
                    ChatMetadata(chat_id=1001, chat_type="private"),
                )
            )
        )

        self.assertEqual(repositories.chat.updated_cursors[-1][2], 100)

    def test_handler_skips_rejected_update(self):
        client = FakeListenerClient()
        listener, repositories = make_listener(
            client,
            policy=ChatIngestionPolicy(denied_chat_ids=frozenset({1001})),
        )
        asyncio.run(listener.run_forever())

        with self.assertLogs("telegram_ai_assistant.ingestion.listener", level="DEBUG") as logs:
            asyncio.run(
                client.handler(
                    FakeEvent(
                        RawMessage(50, text="secret text"),
                        ChatMetadata(chat_id=1001, chat_type="private"),
                    )
                )
            )

        self.assertEqual(repositories.account.accounts, [])
        self.assertEqual(repositories.chat.chats, [])
        self.assertEqual(repositories.messages.messages, [])
        self.assertEqual(repositories.chat.updated_cursors, [])
        log_output = "\n".join(logs.output)
        self.assertIn("skipped live update", log_output)
        self.assertIn("chat_id=1001", log_output)
        self.assertIn("chat_type=private", log_output)
        self.assertNotIn("secret text", log_output)


def make_listener(
    client,
    policy=None,
    backfill_job_runner=None,
    backfill_batch_size=25,
    backfill_poll_interval_seconds=10,
):
    connection_factory = FakeConnectionFactory()
    repositories = RepositoryBundle(
        account=FakeAccountRepository(connection_factory.connection_obj),
        chat=FakeChatRepository(connection_factory.connection_obj),
        messages=FakeMessageRepository(connection_factory.connection_obj),
    )
    listener = LiveUpdateListener(
        account_id="owner",
        connection_factory=connection_factory,
        client_factory=lambda: client,
        policy=policy or ChatIngestionPolicy(),
        account_repository_factory=lambda connection: repositories.account,
        chat_repository_factory=lambda connection: repositories.chat,
        message_repository_factory=lambda connection: repositories.messages,
        now=lambda: datetime(2026, 6, 3, 11, 0, tzinfo=UTC),
        chat_metadata_extractor=lambda event: event.chat_metadata,
        message_extractor=lambda event: event.message,
        backfill_job_runner=backfill_job_runner,
        backfill_batch_size=backfill_batch_size,
        backfill_poll_interval_seconds=backfill_poll_interval_seconds,
    )
    return listener, repositories


if __name__ == "__main__":
    unittest.main()
