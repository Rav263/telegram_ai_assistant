from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.db import repositories
from telegram_ai_assistant.db.migrations import apply_schema
from telegram_ai_assistant.db.repositories import CandidateRepository, MessageRepository
from telegram_ai_assistant.domain import Message, MessageDirection


class RecordingCursor:
    def __init__(self):
        self.statements = []
        self.fetchone_result = None

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()

    @property
    def statements(self):
        return self.cursor_obj.statements

    def cursor(self):
        return self.cursor_obj


def compact_sql(sql):
    return " ".join(sql.split())


class MessageRepositoryTests(unittest.TestCase):
    def test_upsert_message_inserts_with_conflict_update(self):
        connection = RecordingConnection()
        message = Message(
            account_id="main",
            chat_id=100,
            telegram_message_id=200,
            sender_id=300,
            direction=MessageDirection.INCOMING,
            sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
            text="Need to prepare the report",
            caption="",
            reply_to_message_id=199,
        )

        MessageRepository(connection).upsert_message(message)

        self.assertEqual(len(connection.statements), 1)
        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into messages", normalized_sql)
        self.assertIn(
            "on conflict (account_id, chat_id, telegram_message_id)",
            normalized_sql,
        )
        self.assertIn("do update set", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(params["telegram_message_id"], 200)
        self.assertEqual(params["sender_id"], 300)
        self.assertEqual(params["direction"], "incoming")
        self.assertEqual(params["sent_at"], datetime(2026, 6, 2, 8, 0, tzinfo=UTC))
        self.assertEqual(params["text"], "Need to prepare the report")
        self.assertEqual(params["caption"], "")
        self.assertEqual(params["reply_to_message_id"], 199)


class AccountRepositoryTests(unittest.TestCase):
    def test_ensure_account_inserts_and_updates_identity_fields(self):
        connection = RecordingConnection()

        repositories.AccountRepository(connection).ensure_account(
            account_id="main",
            telegram_user_id=12345,
            display_name="Personal Telegram",
        )

        self.assertEqual(len(connection.statements), 1)
        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into accounts", normalized_sql)
        self.assertIn("on conflict (account_id)", normalized_sql)
        self.assertIn("do update set", normalized_sql)
        self.assertIn(
            "telegram_user_id = coalesce(excluded.telegram_user_id, accounts.telegram_user_id)",
            normalized_sql,
        )
        self.assertIn("display_name = excluded.display_name", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["telegram_user_id"], 12345)
        self.assertEqual(params["display_name"], "Personal Telegram")

    def test_ensure_account_defaults_optional_values(self):
        connection = RecordingConnection()

        repositories.AccountRepository(connection).ensure_account("main")

        _, params = connection.statements[0]
        self.assertEqual(params["account_id"], "main")
        self.assertIsNone(params["telegram_user_id"])
        self.assertEqual(params["display_name"], "")


class ChatRepositoryTests(unittest.TestCase):
    def test_ensure_chat_upserts_without_moving_ingestion_cursor(self):
        connection = RecordingConnection()

        repositories.ChatRepository(connection).ensure_chat(
            account_id="main",
            chat_id=100,
            title="Tasks",
            chat_type="group",
        )

        self.assertEqual(len(connection.statements), 1)
        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into chats", normalized_sql)
        self.assertIn("on conflict (account_id, chat_id)", normalized_sql)
        self.assertIn("do update set", normalized_sql)
        self.assertIn("title = excluded.title", normalized_sql)
        self.assertIn("chat_type = excluded.chat_type", normalized_sql)
        self.assertNotIn("last_ingested_message_id", normalized_sql)
        self.assertNotIn("last_ingested_at", normalized_sql)
        self.assertNotIn("ingestion_error", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(params["title"], "Tasks")
        self.assertEqual(params["chat_type"], "group")

    def test_ensure_chat_defaults_optional_values(self):
        connection = RecordingConnection()

        repositories.ChatRepository(connection).ensure_chat("main", 100)

        _, params = connection.statements[0]
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(params["title"], "")
        self.assertEqual(params["chat_type"], "")

    def test_get_last_ingested_message_id_returns_existing_cursor(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = (987,)

        result = repositories.ChatRepository(connection).get_last_ingested_message_id(
            "main",
            100,
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("select last_ingested_message_id", normalized_sql)
        self.assertIn("from chats", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(result, 987)

    def test_get_last_ingested_message_id_returns_zero_for_missing_chat(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = None

        result = repositories.ChatRepository(connection).get_last_ingested_message_id(
            "main",
            100,
        )

        self.assertEqual(result, 0)

    def test_get_last_ingested_message_id_returns_zero_for_null_cursor(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = (None,)

        result = repositories.ChatRepository(connection).get_last_ingested_message_id(
            "main",
            100,
        )

        self.assertEqual(result, 0)

    def test_update_ingestion_cursor_sets_message_id_and_timestamp(self):
        connection = RecordingConnection()
        ingested_at = datetime(2026, 6, 2, 9, 30, tzinfo=UTC)

        repositories.ChatRepository(connection).update_ingestion_cursor(
            account_id="main",
            chat_id=100,
            last_message_id=456,
            ingested_at=ingested_at,
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("update chats", normalized_sql)
        self.assertIn("last_ingested_message_id = %(last_message_id)s", normalized_sql)
        self.assertIn("last_ingested_at = %(ingested_at)s", normalized_sql)
        self.assertIn("ingestion_error = ''", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(params["last_message_id"], 456)
        self.assertEqual(params["ingested_at"], ingested_at)

    def test_record_ingestion_error_stores_error_type_without_cursor_change(self):
        connection = RecordingConnection()

        repositories.ChatRepository(connection).record_ingestion_error(
            account_id="main",
            chat_id=100,
            error_type="rate_limited",
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("update chats", normalized_sql)
        self.assertIn("ingestion_error = %(error_type)s", normalized_sql)
        self.assertNotIn("last_ingested_message_id =", normalized_sql)
        self.assertNotIn("last_ingested_at =", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(params["error_type"], "rate_limited")


class CandidateRepositoryTests(unittest.TestCase):
    def test_enqueue_candidate_writes_score_and_reasons(self):
        connection = RecordingConnection()
        reasons = ["explicit task language", "owner commitment"]

        CandidateRepository(connection).enqueue_candidate(
            account_id="main",
            chat_id=100,
            telegram_message_id=200,
            score=0.875,
            reasons=reasons,
        )

        self.assertEqual(len(connection.statements), 1)
        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into message_candidates", normalized_sql)
        self.assertIn("score", normalized_sql)
        self.assertIn("reasons", normalized_sql)
        self.assertEqual(params["score"], 0.875)
        self.assertEqual(json.loads(params["reasons"]), reasons)


class MigrationTests(unittest.TestCase):
    def test_apply_schema_executes_schema_sql(self):
        connection = RecordingConnection()

        apply_schema(connection)

        self.assertEqual(len(connection.statements), 1)
        sql, params = connection.statements[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS messages", sql)
        self.assertIsNone(params)


if __name__ == "__main__":
    unittest.main()
