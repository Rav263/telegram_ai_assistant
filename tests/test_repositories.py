from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.db import repositories
from telegram_ai_assistant.db.migrations import apply_schema
from telegram_ai_assistant.db.repositories import (
    CandidateRepository,
    ItemRepository,
    LLMRunRepository,
    BotRuntimeStateRepository,
    ItemQueryRepository,
    MessageProcessingRepository,
    MessageRepository,
    ReviewRepository,
    RuntimeEventRepository,
)
from telegram_ai_assistant.domain import (
    ExtractedItem,
    ItemStatus,
    ItemType,
    Message,
    MessageDirection,
    RuntimeEvent,
    SourceRef,
)


class RecordingCursor:
    def __init__(self):
        self.statements = []
        self.fetchone_result = None
        self.fetchall_result = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result

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


def make_message(
    *,
    account_id: str = "main",
    chat_id: int = 100,
    telegram_message_id: int = 200,
    text: str = "Need to prepare the report",
) -> Message:
    return Message(
        account_id=account_id,
        chat_id=chat_id,
        telegram_message_id=telegram_message_id,
        sender_id=300,
        direction=MessageDirection.INCOMING,
        sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
        text=text,
    )


def make_item(confidence: float = 0.91) -> ExtractedItem:
    return ExtractedItem(
        item_id="item-1",
        item_type=ItemType.COMMITMENT,
        title="Call back",
        description="Call back in 30 minutes",
        confidence=confidence,
        sources=(SourceRef(chat_id=100, telegram_message_id=200),),
        status=ItemStatus.OPEN,
        rationale="Owner committed to call back.",
        metadata={"topic": "calls"},
    )


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

    def test_pending_candidate_messages_reads_queued_candidates(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {
                "account_id": "main",
                "chat_id": 100,
                "telegram_message_id": 200,
                "sender_id": 300,
                "direction": "incoming",
                "sent_at": datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
                "text": "Need to prepare the report",
                "caption": "",
                "reply_to_message_id": None,
            }
        ]

        messages = CandidateRepository(connection).pending_candidate_messages(limit=5)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from message_candidates c", normalized_sql)
        self.assertIn("join messages m", normalized_sql)
        self.assertIn("c.status = 'queued'", normalized_sql)
        self.assertIn("limit %(limit)s", normalized_sql)
        self.assertEqual(params["limit"], 5)
        self.assertEqual(messages, [make_message()])

    def test_mark_processed_updates_candidates_for_source_messages(self):
        connection = RecordingConnection()
        message = make_message()

        CandidateRepository(connection).mark_processed([message])

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("update message_candidates", normalized_sql)
        self.assertIn("status = 'processed'", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(params["telegram_message_id"], 200)


class MessageProcessingRepositoryTests(unittest.TestCase):
    def test_pending_messages_skips_processed_candidate_filter_stage(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {
                "account_id": "main",
                "chat_id": 100,
                "telegram_message_id": 200,
                "sender_id": 300,
                "direction": "incoming",
                "sent_at": datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
                "text": "Need to prepare the report",
                "caption": "",
                "reply_to_message_id": None,
            }
        ]

        messages = MessageProcessingRepository(connection).pending_messages(limit=10)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from messages m", normalized_sql)
        self.assertIn("not exists", normalized_sql)
        self.assertIn("message_processing_state s", normalized_sql)
        self.assertIn("s.stage = 'candidate_filter'", normalized_sql)
        self.assertIn("s.status = 'processed'", normalized_sql)
        self.assertEqual(params["limit"], 10)
        self.assertEqual(messages, [make_message()])

    def test_mark_candidate_filter_processed_upserts_state(self):
        connection = RecordingConnection()
        message = make_message()

        MessageProcessingRepository(connection).mark_candidate_filter_processed([message])

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into message_processing_state", normalized_sql)
        self.assertIn("on conflict (account_id, chat_id, telegram_message_id, stage)", normalized_sql)
        self.assertEqual(params["stage"], "candidate_filter")
        self.assertEqual(params["status"], "processed")
        self.assertEqual(params["error"], "")

    def test_mark_candidate_filter_failed_stores_error_type_only(self):
        connection = RecordingConnection()
        message = make_message()

        MessageProcessingRepository(connection).mark_candidate_filter_failed(
            message,
            "RuntimeError",
        )

        _sql, params = connection.statements[0]
        self.assertEqual(params["status"], "failed")
        self.assertEqual(params["error"], "RuntimeError")


class ItemRepositoryTests(unittest.TestCase):
    def test_save_item_upserts_extracted_item_for_account(self):
        connection = RecordingConnection()
        item = make_item()

        ItemRepository(connection, account_id="main").save_item(item)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into extracted_items", normalized_sql)
        self.assertIn("on conflict (item_id)", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["item_id"], "item-1")
        self.assertEqual(params["item_type"], "commitment")
        self.assertEqual(params["status"], "open")
        self.assertEqual(
            json.loads(params["source_refs"]),
            [{"chat_id": 100, "telegram_message_id": 200}],
        )
        self.assertEqual(json.loads(params["metadata"]), {"topic": "calls"})

    def test_apply_status_change_updates_item_and_records_event(self):
        connection = RecordingConnection()

        ItemRepository(connection, account_id="main").apply_status_change(
            {
                "item_id": "item-1",
                "new_status": "completed",
                "confidence": 0.91,
                "rationale": "Owner wrote it was done.",
            }
        )

        self.assertEqual(len(connection.statements), 2)
        update_sql, update_params = connection.statements[0]
        event_sql, event_params = connection.statements[1]
        self.assertIn("update extracted_items", compact_sql(update_sql).lower())
        self.assertEqual(update_params["item_id"], "item-1")
        self.assertEqual(update_params["new_status"], "completed")
        self.assertIn("insert into item_status_events", compact_sql(event_sql).lower())
        self.assertEqual(event_params["new_status"], "completed")
        self.assertEqual(event_params["reason"], "Owner wrote it was done.")


class ItemQueryRepositoryTests(unittest.TestCase):
    def test_list_open_tasks_reads_active_task_like_items_for_account(self):
        connection = RecordingConnection()
        due_at = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
        connection.cursor_obj.fetchall_result = [
            {
                "item_id": "item-1",
                "item_type": "task",
                "title": "Send report",
                "description": "Prepare and send the report",
                "confidence": 0.91,
                "status": "open",
                "rationale": "Owner promised it.",
                "due_at": due_at,
                "source_refs": [{"chat_id": 100, "telegram_message_id": 200}],
                "metadata": {"topic": "work"},
            }
        ]

        items = ItemQueryRepository(connection, account_id="main").list_open_tasks(limit=5)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from extracted_items", normalized_sql)
        self.assertIn("account_id = %(account_id)s", normalized_sql)
        self.assertIn("item_type = any", normalized_sql)
        self.assertIn("status = any", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["limit"], 5)
        self.assertEqual(params["item_types"], ["task", "commitment", "reminder", "waiting_for"])
        self.assertEqual(params["statuses"], ["open", "in_progress", "partially_completed", "waiting_for"])
        self.assertEqual(items[0].item_id, "item-1")
        self.assertEqual(items[0].item_type, ItemType.TASK)
        self.assertEqual(items[0].status, ItemStatus.OPEN)
        self.assertEqual(items[0].sources, (SourceRef(chat_id=100, telegram_message_id=200),))


class ReviewRepositoryTests(unittest.TestCase):
    def test_enqueue_item_saves_candidate_item_and_review_entry(self):
        connection = RecordingConnection()
        item = make_item(confidence=0.42)

        ReviewRepository(connection, account_id="main").enqueue_item(item)

        self.assertEqual(len(connection.statements), 2)
        _item_sql, item_params = connection.statements[0]
        review_sql, review_params = connection.statements[1]
        self.assertEqual(item_params["status"], "candidate")
        self.assertIn("insert into review_queue", compact_sql(review_sql).lower())
        self.assertEqual(review_params["item_id"], "item-1")
        self.assertEqual(review_params["review_type"], "item")
        self.assertEqual(review_params["state"], "pending")

    def test_enqueue_status_change_stores_sanitized_payload(self):
        connection = RecordingConnection()

        ReviewRepository(connection, account_id="main").enqueue_status_change(
            {
                "item_id": "item-1",
                "new_status": ItemStatus.PARTIALLY_COMPLETED,
                "confidence": 0.64,
                "rationale": "Only first part is clearly done.",
            }
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into review_queue", normalized_sql)
        self.assertEqual(params["item_id"], "item-1")
        self.assertEqual(params["review_type"], "status_change")
        self.assertEqual(params["state"], "pending")
        self.assertEqual(
            json.loads(params["payload"])["new_status"],
            "partially_completed",
        )


class RuntimeEventRepositoryTests(unittest.TestCase):
    def test_record_event_inserts_safe_metadata(self):
        connection = RecordingConnection()

        RuntimeEventRepository(connection).record_event(
            component="worker",
            severity="warning",
            event_type="llm_failure",
            message="LLM batch failed",
            metadata={"error_type": "RuntimeError", "count": 3},
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into runtime_events", normalized_sql)
        self.assertEqual(params["component"], "worker")
        self.assertEqual(params["severity"], "warning")
        self.assertEqual(params["event_type"], "llm_failure")
        self.assertEqual(json.loads(params["metadata"])["error_type"], "RuntimeError")

    def test_latest_events_reads_warning_and_error_events(self):
        connection = RecordingConnection()
        created_at = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
        connection.cursor_obj.fetchall_result = [
            {
                "runtime_event_id": 10,
                "component": "worker",
                "severity": "error",
                "event_type": "worker_cycle_failed",
                "message": "Worker cycle failed",
                "metadata": {"error_type": "RuntimeError"},
                "created_at": created_at,
            }
        ]

        events = RuntimeEventRepository(connection).latest_events(limit=10)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from runtime_events", normalized_sql)
        self.assertIn("severity = any", normalized_sql)
        self.assertIn("order by created_at desc, runtime_event_id desc", normalized_sql)
        self.assertEqual(params["severities"], ["warning", "error"])
        self.assertEqual(params["limit"], 10)
        self.assertEqual(
            events,
            [
                RuntimeEvent(
                    runtime_event_id=10,
                    component="worker",
                    severity="error",
                    event_type="worker_cycle_failed",
                    message="Worker cycle failed",
                    metadata={"error_type": "RuntimeError"},
                    created_at=created_at,
                )
            ],
        )


class BotRuntimeStateRepositoryTests(unittest.TestCase):
    def test_get_last_update_id_returns_none_for_missing_state(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = None

        last_update_id = BotRuntimeStateRepository(connection).get_last_update_id(bot_name="default")

        sql, params = connection.statements[0]
        self.assertIn("from bot_runtime_state", compact_sql(sql).lower())
        self.assertEqual(params["bot_name"], "default")
        self.assertIsNone(last_update_id)

    def test_save_last_update_id_upserts_state(self):
        connection = RecordingConnection()

        BotRuntimeStateRepository(connection).save_last_update_id(
            bot_name="default",
            last_update_id=42,
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into bot_runtime_state", normalized_sql)
        self.assertIn("on conflict (bot_name)", normalized_sql)
        self.assertEqual(params["bot_name"], "default")
        self.assertEqual(params["last_update_id"], 42)


class LLMRunRepositoryTests(unittest.TestCase):
    def test_record_failure_stores_exception_type_without_raw_message(self):
        connection = RecordingConnection()

        LLMRunRepository(connection).record_failure(RuntimeError("secret message text"))

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into llm_runs", normalized_sql)
        self.assertEqual(params["provider"], "lm_studio")
        self.assertEqual(params["status"], "failure")
        self.assertEqual(params["error"], "RuntimeError")
        self.assertNotIn("secret message text", json.dumps(params))


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
