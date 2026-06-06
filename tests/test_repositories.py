from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.db import repositories
from telegram_ai_assistant.db.migrations import apply_schema
from telegram_ai_assistant.db.repositories import (
    BackfillJobRepository,
    BackfillJobQueryRepository,
    CandidateRepository,
    ChatPolicyRepository,
    ChatQueryRepository,
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
    BackfillChatChoice,
    BackfillJobRecord,
    BackfillJobSummary,
    ChatPolicyChoice,
    ExtractedItem,
    ItemStatus,
    ItemType,
    Message,
    MessageDirection,
    ReviewEntry,
    RuntimeEvent,
    SourceRef,
)
from telegram_ai_assistant.filtering import CandidateScoringContext


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

    def test_list_catch_up_chats_reads_known_chats_with_cursors(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {
                "chat_id": 100,
                "title": "Tasks",
                "chat_type": "group",
                "last_ingested_message_id": 456,
            }
        ]

        chats = repositories.ChatRepository(connection).list_catch_up_chats("main")

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("select", normalized_sql)
        self.assertIn("last_ingested_message_id", normalized_sql)
        self.assertIn("from chats", normalized_sql)
        self.assertIn("where account_id = %(account_id)s", normalized_sql)
        self.assertIn("last_ingested_message_id > 0", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(chats[0].chat_id, 100)
        self.assertEqual(chats[0].title, "Tasks")
        self.assertEqual(chats[0].chat_type, "group")
        self.assertEqual(chats[0].last_ingested_message_id, 456)


class ChatPolicyRepositoryTests(unittest.TestCase):
    def test_effective_policy_combines_env_and_database_overrides(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {"chat_id": -100777, "policy_state": "allow"},
            {"chat_id": 1002, "policy_state": "deny"},
        ]

        policy = ChatPolicyRepository(connection, account_id="main").effective_policy(
            base_allowed_channel_ids=frozenset({-100111}),
            base_denied_chat_ids=frozenset({1001}),
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from chat_policy_overrides", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(policy.allowed_channel_ids, frozenset({-100111, -100777}))
        self.assertEqual(policy.denied_chat_ids, frozenset({1001, 1002}))

    def test_set_policy_upserts_allow_and_deny_states(self):
        connection = RecordingConnection()
        repository = ChatPolicyRepository(connection, account_id="main")

        repository.allow_chat(1001)
        repository.deny_chat(1002)

        allow_sql, allow_params = connection.statements[0]
        deny_sql, deny_params = connection.statements[1]
        self.assertIn("insert into chat_policy_overrides", compact_sql(allow_sql).lower())
        self.assertIn("on conflict (account_id, chat_id)", compact_sql(allow_sql).lower())
        self.assertEqual(allow_params["policy_state"], "allow")
        self.assertEqual(deny_params["policy_state"], "deny")

    def test_reset_policy_deletes_override(self):
        connection = RecordingConnection()

        ChatPolicyRepository(connection, account_id="main").reset_chat(1001)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("delete from chat_policy_overrides", normalized_sql)
        self.assertEqual(params, {"account_id": "main", "chat_id": 1001})


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
                "chat_type": "private",
            }
        ]

        repository = MessageProcessingRepository(connection)
        messages = repository.pending_messages(limit=10)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from messages m", normalized_sql)
        self.assertIn("left join chats c", normalized_sql)
        self.assertIn("c.chat_type", normalized_sql)
        self.assertIn("not exists", normalized_sql)
        self.assertIn("message_processing_state s", normalized_sql)
        self.assertIn("s.stage = 'candidate_filter'", normalized_sql)
        self.assertIn("s.status = 'processed'", normalized_sql)
        self.assertEqual(params["limit"], 10)
        self.assertEqual(messages, [make_message()])
        self.assertEqual(
            repository.scoring_context_for(messages[0]),
            CandidateScoringContext(chat_type="private"),
        )
        self.assertEqual(len(connection.statements), 1)

    def test_scoring_context_for_reads_chat_type_for_uncached_message(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = {"chat_type": "private"}
        message = make_message()

        context = MessageProcessingRepository(connection).scoring_context_for(message)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("select chat_type", normalized_sql)
        self.assertIn("from chats", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(context, CandidateScoringContext(chat_type="private"))

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

    def test_list_summary_items_reads_active_items_and_thoughts(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {
                "item_id": "task-1",
                "item_type": "task",
                "title": "Send report",
                "description": "Prepare report",
                "confidence": 0.91,
                "status": "open",
                "rationale": "Owner committed.",
                "due_at": None,
                "source_refs": [{"chat_id": 100, "telegram_message_id": 200}],
                "metadata": {},
            },
            {
                "item_id": "thought-1",
                "item_type": "thought",
                "title": "Consider pricing",
                "description": "Pricing concern.",
                "confidence": 0.82,
                "status": "open",
                "rationale": "Important thought.",
                "due_at": None,
                "source_refs": [],
                "metadata": {},
            },
        ]

        items = ItemQueryRepository(connection, account_id="main").list_summary_items(limit=20)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from extracted_items", normalized_sql)
        self.assertIn("account_id = %(account_id)s", normalized_sql)
        self.assertIn("item_type = any", normalized_sql)
        self.assertIn("status = any", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["limit"], 20)
        self.assertIn("thought", params["item_types"])
        self.assertEqual(items[0].item_id, "task-1")
        self.assertEqual(items[1].item_type, ItemType.THOUGHT)


class ReviewRepositoryTests(unittest.TestCase):
    def test_list_pending_reviews_reads_item_and_payload_data(self):
        connection = RecordingConnection()
        created_at = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
        connection.cursor_obj.fetchall_result = [
            {
                "review_id": 7,
                "review_type": "item",
                "state": "pending",
                "reason": "Low confidence.",
                "payload": {"confidence": 0.5},
                "created_at": created_at,
                "item_id": "item-1",
                "item_type": "task",
                "title": "Send report",
                "description": "Prepare report",
                "confidence": 0.5,
                "status": "candidate",
                "rationale": "Maybe a task.",
                "due_at": None,
                "source_refs": [],
                "metadata": {},
            }
        ]

        entries = ReviewRepository(connection, account_id="main").list_pending_reviews(limit=5)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from review_queue", normalized_sql)
        self.assertIn("left join extracted_items", normalized_sql)
        self.assertIn("r.state = 'pending'", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["limit"], 5)
        self.assertEqual(
            entries,
            [
                ReviewEntry(
                    review_id=7,
                    review_type="item",
                    state="pending",
                    reason="Low confidence.",
                    payload={"confidence": 0.5},
                    created_at=created_at,
                    item=ExtractedItem(
                        item_id="item-1",
                        item_type=ItemType.TASK,
                        title="Send report",
                        description="Prepare report",
                        confidence=0.5,
                        status=ItemStatus.CANDIDATE,
                        rationale="Maybe a task.",
                        due_at=None,
                        sources=(),
                        metadata={},
                    ),
                )
            ],
        )

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

    def test_approve_item_review_activates_item_and_marks_review_approved(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = {
            "review_id": 7,
            "review_type": "item",
            "item_id": "item-1",
            "payload": {},
            "reason": "Looks useful.",
        }

        result = ReviewRepository(connection, account_id="main").approve_review(7)

        statements = [compact_sql(sql).lower() for sql, _ in connection.statements]
        self.assertEqual(result, "Review approved.")
        self.assertIn("select", statements[0])
        self.assertIn("from review_queue", statements[0])
        self.assertIn("update extracted_items", statements[1])
        self.assertIn("update review_queue", statements[2])
        self.assertEqual(connection.statements[1][1]["status"], "open")
        self.assertEqual(connection.statements[2][1]["state"], "approved")

    def test_approve_status_change_review_applies_payload_status_and_marks_approved(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = {
            "review_id": 8,
            "review_type": "status_change",
            "item_id": "item-1",
            "payload": {"item_id": "item-1", "new_status": "completed", "rationale": "Owner said done."},
            "reason": "Owner said done.",
        }

        result = ReviewRepository(connection, account_id="main").approve_review(8)

        statements = [compact_sql(sql).lower() for sql, _ in connection.statements]
        self.assertEqual(result, "Review approved.")
        self.assertIn("update extracted_items", statements[1])
        self.assertIn("insert into item_status_events", statements[2])
        self.assertIn("update review_queue", statements[3])
        self.assertEqual(connection.statements[1][1]["new_status"], "completed")
        self.assertEqual(connection.statements[3][1]["state"], "approved")

    def test_reject_review_marks_review_rejected_without_item_update(self):
        connection = RecordingConnection()

        result = ReviewRepository(connection, account_id="main").reject_review(9)

        self.assertEqual(result, "Review rejected.")
        self.assertEqual(len(connection.statements), 1)
        sql, params = connection.statements[0]
        self.assertIn("update review_queue", compact_sql(sql).lower())
        self.assertEqual(params["review_id"], 9)
        self.assertEqual(params["state"], "rejected")


class BackfillJobQueryRepositoryTests(unittest.TestCase):
    def test_latest_backfill_jobs_reads_recent_jobs_for_account(self):
        connection = RecordingConnection()
        now = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
        connection.cursor_obj.fetchall_result = [
            {
                "backfill_job_id": 3,
                "status": "completed",
                "chat_id": 1001,
                "chat_title": "Alice",
                "from_date": now,
                "to_date": now,
                "saved_count": 42,
                "next_before_message_id": None,
                "last_error_type": "",
                "created_at": now,
            }
        ]

        jobs = BackfillJobQueryRepository(connection, account_id="main").latest_jobs(limit=3)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from backfill_jobs", normalized_sql)
        self.assertIn("account_id = %(account_id)s", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["limit"], 3)
        self.assertEqual(
            jobs,
            [
                BackfillJobSummary(
                    backfill_job_id=3,
                    status="completed",
                    chat_id=1001,
                    chat_title="Alice",
                    from_date=now,
                    to_date=now,
                    saved_count=42,
                    next_before_message_id=None,
                    last_error_type="",
                    created_at=now,
                )
            ],
        )


class ChatQueryRepositoryTests(unittest.TestCase):
    def test_list_backfill_chats_reads_policy_filtered_page(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {"chat_id": 1001, "title": "Alice", "chat_type": "private"},
            {"chat_id": 1002, "title": "Project", "chat_type": "supergroup"},
        ]

        chats = ChatQueryRepository(
            connection,
            account_id="main",
            allowed_channel_ids=frozenset({-100111}),
            denied_chat_ids=frozenset({2002}),
        ).list_backfill_chats(page=1, page_size=6)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from chats", normalized_sql)
        self.assertIn("account_id = %(account_id)s", normalized_sql)
        self.assertIn("chat_id <> all(%(denied_chat_ids)s)", normalized_sql)
        self.assertIn("chat_id = any(%(allowed_channel_ids)s)", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["limit"], 6)
        self.assertEqual(params["offset"], 6)
        self.assertEqual(params["allowed_channel_ids"], [-100111])
        self.assertEqual(params["denied_chat_ids"], [2002])
        self.assertEqual(
            chats,
            [
                BackfillChatChoice(chat_id=1001, title="Alice", chat_type="private"),
                BackfillChatChoice(chat_id=1002, title="Project", chat_type="supergroup"),
            ],
        )

    def test_get_backfill_chat_reads_one_policy_allowed_chat(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = {"chat_id": 1001, "title": "Alice", "chat_type": "private"}

        chat = ChatQueryRepository(
            connection,
            account_id="main",
            allowed_channel_ids=frozenset({-100111}),
            denied_chat_ids=frozenset({2002}),
        ).get_backfill_chat(1001)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from chats", normalized_sql)
        self.assertIn("chat_id = %(chat_id)s", normalized_sql)
        self.assertIn("chat_id <> all(%(denied_chat_ids)s)", normalized_sql)
        self.assertEqual(params["chat_id"], 1001)
        self.assertEqual(chat, BackfillChatChoice(chat_id=1001, title="Alice", chat_type="private"))

    def test_list_policy_chats_reads_known_chats_with_override_state(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchall_result = [
            {"chat_id": 1001, "title": "Alice", "chat_type": "private", "policy_state": "deny"},
            {"chat_id": -100777, "title": "News", "chat_type": "channel", "policy_state": None},
        ]

        chats = ChatQueryRepository(connection, account_id="main").list_policy_chats(page=0, page_size=6)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from chats", normalized_sql)
        self.assertIn("left join chat_policy_overrides", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["limit"], 6)
        self.assertEqual(params["offset"], 0)
        self.assertEqual(
            chats,
            [
                ChatPolicyChoice(chat_id=1001, title="Alice", chat_type="private", policy_state="deny"),
                ChatPolicyChoice(chat_id=-100777, title="News", chat_type="channel", policy_state="default"),
            ],
        )


class BackfillJobRepositoryTests(unittest.TestCase):
    def test_create_job_inserts_pending_job_and_returns_record(self):
        connection = RecordingConnection()
        created_at = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
        from_date = datetime(2026, 5, 7, 9, 0, tzinfo=UTC)
        to_date = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
        connection.cursor_obj.fetchone_result = {
            "backfill_job_id": 7,
            "account_id": "main",
            "chat_id": 1001,
            "chat_title": "Alice",
            "status": "pending",
            "from_date": from_date,
            "to_date": to_date,
            "next_before_message_id": None,
            "saved_count": 0,
            "last_error_type": "",
            "last_error_metadata": {},
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "updated_at": created_at,
        }

        job = BackfillJobRepository(connection, account_id="main").create_job(
            chat_id=1001,
            chat_title="Alice",
            from_date=from_date,
            to_date=to_date,
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into backfill_jobs", normalized_sql)
        self.assertIn("'pending'", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 1001)
        self.assertEqual(params["chat_title"], "Alice")
        self.assertEqual(job.backfill_job_id, 7)
        self.assertEqual(job.status, "pending")

    def test_request_cancel_updates_pending_and_running_jobs(self):
        connection = RecordingConnection()

        BackfillJobRepository(connection, account_id="main").request_cancel(7)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("update backfill_jobs", normalized_sql)
        self.assertIn("status = 'cancel_requested'", normalized_sql)
        self.assertIn("status in ('pending', 'running')", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["backfill_job_id"], 7)

    def test_claim_next_job_uses_row_lock_and_returns_record(self):
        connection = RecordingConnection()
        now = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
        connection.cursor_obj.fetchone_result = {
            "backfill_job_id": 7,
            "account_id": "main",
            "chat_id": 1001,
            "chat_title": "Alice",
            "status": "running",
            "from_date": now,
            "to_date": now,
            "next_before_message_id": 500,
            "saved_count": 10,
            "last_error_type": "",
            "last_error_metadata": {},
            "created_at": now,
            "started_at": now,
            "finished_at": None,
            "updated_at": now,
        }

        job = BackfillJobRepository(connection, account_id="main").claim_next_job()

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("for update skip locked", normalized_sql)
        self.assertIn("status in ('pending', 'running', 'cancel_requested')", normalized_sql)
        self.assertIn("returning", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertIsInstance(job, BackfillJobRecord)
        self.assertEqual(job.backfill_job_id, 7)
        self.assertEqual(job.next_before_message_id, 500)

    def test_get_job_reads_account_scoped_backfill_job(self):
        connection = RecordingConnection()
        now = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
        connection.cursor_obj.fetchone_result = {
            "backfill_job_id": 7,
            "account_id": "main",
            "chat_id": 1001,
            "chat_title": "Alice",
            "status": "failed",
            "from_date": now,
            "to_date": now,
            "next_before_message_id": 500,
            "saved_count": 10,
            "last_error_type": "TimeoutError",
            "last_error_metadata": {"endpoint_host": "localhost"},
            "created_at": now,
            "started_at": now,
            "finished_at": now,
            "updated_at": now,
        }

        job = BackfillJobRepository(connection, account_id="main").get_job(7)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("from backfill_jobs", normalized_sql)
        self.assertIn("account_id = %(account_id)s", normalized_sql)
        self.assertIn("backfill_job_id = %(backfill_job_id)s", normalized_sql)
        self.assertEqual(params["backfill_job_id"], 7)
        self.assertEqual(job.last_error_type, "TimeoutError")

    def test_record_progress_accumulates_saved_count_and_cursor(self):
        connection = RecordingConnection()

        BackfillJobRepository(connection, account_id="main").record_progress(
            backfill_job_id=7,
            saved_count=12,
            next_before_message_id=450,
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("saved_count = saved_count + %(saved_count)s", normalized_sql)
        self.assertIn("next_before_message_id = %(next_before_message_id)s", normalized_sql)
        self.assertEqual(params["saved_count"], 12)
        self.assertEqual(params["next_before_message_id"], 450)

    def test_terminal_updates_store_sanitized_failure_metadata(self):
        connection = RecordingConnection()
        repository = BackfillJobRepository(connection, account_id="main")

        repository.mark_completed(7)
        repository.mark_cancelled(8)
        repository.mark_failed(9, error_type="TimeoutError", metadata={"endpoint_host": "localhost"})

        completed_sql, completed_params = connection.statements[0]
        cancelled_sql, cancelled_params = connection.statements[1]
        failed_sql, failed_params = connection.statements[2]
        self.assertIn("status = 'completed'", compact_sql(completed_sql).lower())
        self.assertIn("status = 'cancelled'", compact_sql(cancelled_sql).lower())
        self.assertIn("status = 'failed'", compact_sql(failed_sql).lower())
        self.assertEqual(completed_params["backfill_job_id"], 7)
        self.assertEqual(cancelled_params["backfill_job_id"], 8)
        self.assertEqual(failed_params["backfill_job_id"], 9)
        self.assertEqual(failed_params["last_error_type"], "TimeoutError")
        self.assertEqual(json.loads(failed_params["last_error_metadata"]), {"endpoint_host": "localhost"})


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
