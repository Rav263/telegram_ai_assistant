from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.db.migrations import apply_schema
from telegram_ai_assistant.db.repositories import CandidateRepository, MessageRepository
from telegram_ai_assistant.domain import Message, MessageDirection


class RecordingCursor:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

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
