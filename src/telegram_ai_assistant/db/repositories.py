from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
from enum import StrEnum
from typing import Any, Protocol, Sequence

from telegram_ai_assistant.domain import (
    BackfillJobSummary,
    ExtractedItem,
    ItemStatus,
    ItemType,
    Message,
    MessageDirection,
    ReviewEntry,
    RuntimeEvent,
    SourceRef,
)


class Cursor(Protocol):
    def execute(self, sql: str, params: object | None = None) -> object:
        ...

    def fetchone(self) -> object:
        ...

    def fetchall(self) -> object:
        ...


class Connection(Protocol):
    def cursor(self) -> Cursor:
        ...


def _execute(connection: Connection, sql: str, params: object | None = None) -> None:
    cursor = connection.cursor()

    if hasattr(cursor, "__enter__"):
        with cursor as active_cursor:
            active_cursor.execute(sql, params)
        return

    cursor.execute(sql, params)


def _fetchone(connection: Connection, sql: str, params: object | None = None) -> object:
    cursor = connection.cursor()

    if hasattr(cursor, "__enter__"):
        with cursor as active_cursor:
            active_cursor.execute(sql, params)
            return active_cursor.fetchone()

    cursor.execute(sql, params)
    return cursor.fetchone()


def _fetchall(connection: Connection, sql: str, params: object | None = None) -> list[object]:
    cursor = connection.cursor()

    if hasattr(cursor, "__enter__"):
        with cursor as active_cursor:
            active_cursor.execute(sql, params)
            return list(active_cursor.fetchall())

    cursor.execute(sql, params)
    return list(cursor.fetchall())


def _row_value(row: object, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row[key]
    return row[index]  # type: ignore[index]


def _message_from_row(row: object) -> Message:
    return Message(
        account_id=str(_row_value(row, "account_id", 0)),
        chat_id=int(_row_value(row, "chat_id", 1)),
        telegram_message_id=int(_row_value(row, "telegram_message_id", 2)),
        sender_id=int(_row_value(row, "sender_id", 3)),
        direction=MessageDirection(str(_row_value(row, "direction", 4))),
        sent_at=_row_value(row, "sent_at", 5),
        text=str(_row_value(row, "text", 6) or ""),
        caption=str(_row_value(row, "caption", 7) or ""),
        reply_to_message_id=_row_value(row, "reply_to_message_id", 8),
    )


def _runtime_event_from_row(row: object) -> RuntimeEvent:
    return RuntimeEvent(
        runtime_event_id=int(_row_value(row, "runtime_event_id", 0)),
        component=str(_row_value(row, "component", 1)),
        severity=str(_row_value(row, "severity", 2)),
        event_type=str(_row_value(row, "event_type", 3)),
        message=str(_row_value(row, "message", 4) or ""),
        metadata=_json_object(_row_value(row, "metadata", 5)),
        created_at=_row_value(row, "created_at", 6),
    )


def _item_from_row(row: object) -> ExtractedItem:
    return ExtractedItem(
        item_id=str(_row_value(row, "item_id", 0)),
        item_type=ItemType(str(_row_value(row, "item_type", 1))),
        title=str(_row_value(row, "title", 2)),
        description=str(_row_value(row, "description", 3) or ""),
        confidence=float(_row_value(row, "confidence", 4)),
        status=ItemStatus(str(_row_value(row, "status", 5))),
        rationale=str(_row_value(row, "rationale", 6) or ""),
        due_at=_row_value(row, "due_at", 7),
        sources=_source_refs_from_json(_row_value(row, "source_refs", 8)),
        metadata={str(key): str(value) for key, value in _json_object(_row_value(row, "metadata", 9)).items()},
    )


def _review_entry_from_row(row: object) -> ReviewEntry:
    return ReviewEntry(
        review_id=int(_row_value(row, "review_id", 0)),
        review_type=str(_row_value(row, "review_type", 1)),
        state=str(_row_value(row, "state", 2)),
        reason=str(_row_value(row, "reason", 3) or ""),
        payload=_json_object(_row_value(row, "payload", 4)),
        created_at=_row_value(row, "created_at", 5),
        item=_review_item_from_row(row),
    )


def _backfill_job_summary_from_row(row: object) -> BackfillJobSummary:
    return BackfillJobSummary(
        backfill_job_id=int(_row_value(row, "backfill_job_id", 0)),
        status=str(_row_value(row, "status", 1)),
        from_date=_row_value(row, "from_date", 2),
        to_date=_row_value(row, "to_date", 3),
        error=str(_row_value(row, "error", 4) or ""),
        created_at=_row_value(row, "created_at", 5),
    )


def _review_item_from_row(row: object) -> ExtractedItem | None:
    item_id = _row_value(row, "item_id", 6)
    if item_id is None:
        return None
    return ExtractedItem(
        item_id=str(item_id),
        item_type=ItemType(str(_row_value(row, "item_type", 7))),
        title=str(_row_value(row, "title", 8)),
        description=str(_row_value(row, "description", 9) or ""),
        confidence=float(_row_value(row, "confidence", 10)),
        status=ItemStatus(str(_row_value(row, "status", 11))),
        rationale=str(_row_value(row, "rationale", 12) or ""),
        due_at=_row_value(row, "due_at", 13),
        sources=_source_refs_from_json(_row_value(row, "source_refs", 14)),
        metadata={str(key): str(value) for key, value in _json_object(_row_value(row, "metadata", 15)).items()},
    )


def _source_refs_from_json(value: object) -> tuple[SourceRef, ...]:
    if isinstance(value, str):
        decoded = json.loads(value)
    else:
        decoded = value
    if not isinstance(decoded, list):
        return ()
    refs = []
    for item in decoded:
        if isinstance(item, Mapping):
            refs.append(
                SourceRef(
                    chat_id=int(item.get("chat_id", 0)),
                    telegram_message_id=int(item.get("telegram_message_id", 0)),
                )
            )
    return tuple(refs)


def _json_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _json_ready(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _json_dumps(value: object) -> str:
    return json.dumps(_json_ready(value), ensure_ascii=False)


def _status_value(value: object) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _source_refs_json(item: ExtractedItem) -> str:
    return _json_dumps(
        [
            {
                "chat_id": source.chat_id,
                "telegram_message_id": source.telegram_message_id,
            }
            for source in item.sources
        ]
    )


def _item_params(account_id: str, item: ExtractedItem, *, status: object | None = None) -> dict[str, object]:
    return {
        "account_id": account_id,
        "item_id": item.item_id,
        "item_type": item.item_type.value,
        "title": item.title,
        "description": item.description,
        "confidence": item.confidence,
        "status": _status_value(status if status is not None else item.status),
        "rationale": item.rationale,
        "due_at": item.due_at,
        "source_refs": _source_refs_json(item),
        "metadata": _json_dumps(item.metadata),
    }


def _upsert_item(
    connection: Connection,
    *,
    account_id: str,
    item: ExtractedItem,
    status: object | None = None,
) -> None:
    sql = """
        INSERT INTO extracted_items (
            item_id,
            account_id,
            item_type,
            title,
            description,
            confidence,
            status,
            rationale,
            due_at,
            source_refs,
            metadata
        )
        VALUES (
            %(item_id)s,
            %(account_id)s,
            %(item_type)s,
            %(title)s,
            %(description)s,
            %(confidence)s,
            %(status)s,
            %(rationale)s,
            %(due_at)s,
            %(source_refs)s::jsonb,
            %(metadata)s::jsonb
        )
        ON CONFLICT (item_id)
        DO UPDATE SET
            account_id = EXCLUDED.account_id,
            item_type = EXCLUDED.item_type,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            confidence = EXCLUDED.confidence,
            status = EXCLUDED.status,
            rationale = EXCLUDED.rationale,
            due_at = EXCLUDED.due_at,
            source_refs = EXCLUDED.source_refs,
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
    """

    _execute(connection, sql, _item_params(account_id, item, status=status))


class AccountRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def ensure_account(
        self,
        account_id: str,
        telegram_user_id: int | None = None,
        display_name: str = "",
    ) -> None:
        sql = """
            INSERT INTO accounts (
                account_id,
                telegram_user_id,
                display_name
            )
            VALUES (
                %(account_id)s,
                %(telegram_user_id)s,
                %(display_name)s
            )
            ON CONFLICT (account_id)
            DO UPDATE SET
                telegram_user_id = COALESCE(EXCLUDED.telegram_user_id, accounts.telegram_user_id),
                display_name = EXCLUDED.display_name
        """
        params = {
            "account_id": account_id,
            "telegram_user_id": telegram_user_id,
            "display_name": display_name,
        }

        _execute(self._connection, sql, params)


class ChatRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def ensure_chat(
        self,
        account_id: str,
        chat_id: int,
        title: str = "",
        chat_type: str = "",
    ) -> None:
        sql = """
            INSERT INTO chats (
                account_id,
                chat_id,
                title,
                chat_type
            )
            VALUES (
                %(account_id)s,
                %(chat_id)s,
                %(title)s,
                %(chat_type)s
            )
            ON CONFLICT (account_id, chat_id)
            DO UPDATE SET
                title = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                updated_at = NOW()
        """
        params = {
            "account_id": account_id,
            "chat_id": chat_id,
            "title": title,
            "chat_type": chat_type,
        }

        _execute(self._connection, sql, params)

    def get_last_ingested_message_id(self, account_id: str, chat_id: int) -> int:
        sql = """
            SELECT last_ingested_message_id
            FROM chats
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
        """
        params = {
            "account_id": account_id,
            "chat_id": chat_id,
        }

        row = _fetchone(self._connection, sql, params)
        if row is None:
            return 0
        if isinstance(row, dict):
            return int(row.get("last_ingested_message_id") or 0)
        return int(row[0] or 0)

    def update_ingestion_cursor(
        self,
        account_id: str,
        chat_id: int,
        last_message_id: int,
        ingested_at: object,
    ) -> None:
        sql = """
            UPDATE chats
            SET
                last_ingested_message_id = %(last_message_id)s,
                last_ingested_at = %(ingested_at)s,
                ingestion_error = '',
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
        """
        params = {
            "account_id": account_id,
            "chat_id": chat_id,
            "last_message_id": last_message_id,
            "ingested_at": ingested_at,
        }

        _execute(self._connection, sql, params)

    def record_ingestion_error(
        self,
        account_id: str,
        chat_id: int,
        error_type: str,
    ) -> None:
        sql = """
            UPDATE chats
            SET
                ingestion_error = %(error_type)s,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
        """
        params = {
            "account_id": account_id,
            "chat_id": chat_id,
            "error_type": error_type,
        }

        _execute(self._connection, sql, params)


class MessageRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def upsert_message(self, message: Message) -> None:
        sql = """
            INSERT INTO messages (
                account_id,
                chat_id,
                telegram_message_id,
                sender_id,
                direction,
                sent_at,
                text,
                caption,
                reply_to_message_id
            )
            VALUES (
                %(account_id)s,
                %(chat_id)s,
                %(telegram_message_id)s,
                %(sender_id)s,
                %(direction)s,
                %(sent_at)s,
                %(text)s,
                %(caption)s,
                %(reply_to_message_id)s
            )
            ON CONFLICT (account_id, chat_id, telegram_message_id)
            DO UPDATE SET
                sender_id = EXCLUDED.sender_id,
                direction = EXCLUDED.direction,
                sent_at = EXCLUDED.sent_at,
                text = EXCLUDED.text,
                caption = EXCLUDED.caption,
                reply_to_message_id = EXCLUDED.reply_to_message_id,
                updated_at = NOW()
        """
        params = {
            "account_id": message.account_id,
            "chat_id": message.chat_id,
            "telegram_message_id": message.telegram_message_id,
            "sender_id": message.sender_id,
            "direction": message.direction.value,
            "sent_at": message.sent_at,
            "text": message.text,
            "caption": message.caption,
            "reply_to_message_id": message.reply_to_message_id,
        }

        _execute(self._connection, sql, params)


class MessageProcessingRepository:
    CANDIDATE_FILTER_STAGE = "candidate_filter"

    def __init__(self, connection: Connection):
        self._connection = connection

    def pending_messages(self, limit: int) -> list[Message]:
        sql = """
            SELECT
                m.account_id,
                m.chat_id,
                m.telegram_message_id,
                m.sender_id,
                m.direction,
                m.sent_at,
                m.text,
                m.caption,
                m.reply_to_message_id
            FROM messages m
            WHERE NOT EXISTS (
                SELECT 1
                FROM message_processing_state s
                WHERE s.account_id = m.account_id
                  AND s.chat_id = m.chat_id
                  AND s.telegram_message_id = m.telegram_message_id
                  AND s.stage = 'candidate_filter'
                  AND s.status = 'processed'
            )
            ORDER BY m.sent_at, m.telegram_message_id
            LIMIT %(limit)s
        """
        rows = _fetchall(self._connection, sql, {"limit": limit})
        return [_message_from_row(row) for row in rows]

    def mark_candidate_filter_processed(self, messages: Sequence[Message]) -> None:
        for message in messages:
            self._upsert_candidate_filter_state(message, status="processed", error="")

    def mark_candidate_filter_failed(self, message: Message, error_type: str) -> None:
        self._upsert_candidate_filter_state(message, status="failed", error=error_type)

    def _upsert_candidate_filter_state(self, message: Message, *, status: str, error: str) -> None:
        sql = """
            INSERT INTO message_processing_state (
                account_id,
                chat_id,
                telegram_message_id,
                stage,
                status,
                error
            )
            VALUES (
                %(account_id)s,
                %(chat_id)s,
                %(telegram_message_id)s,
                %(stage)s,
                %(status)s,
                %(error)s
            )
            ON CONFLICT (account_id, chat_id, telegram_message_id, stage)
            DO UPDATE SET
                status = EXCLUDED.status,
                error = EXCLUDED.error,
                processed_at = NOW()
        """
        params = {
            "account_id": message.account_id,
            "chat_id": message.chat_id,
            "telegram_message_id": message.telegram_message_id,
            "stage": self.CANDIDATE_FILTER_STAGE,
            "status": status,
            "error": error,
        }

        _execute(self._connection, sql, params)


class CandidateRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def enqueue_candidate(
        self,
        *,
        account_id: str,
        chat_id: int,
        telegram_message_id: int,
        score: float,
        reasons: Sequence[str],
    ) -> None:
        sql = """
            INSERT INTO message_candidates (
                account_id,
                chat_id,
                telegram_message_id,
                score,
                reasons,
                status
            )
            VALUES (
                %(account_id)s,
                %(chat_id)s,
                %(telegram_message_id)s,
                %(score)s,
                %(reasons)s::jsonb,
                'queued'
            )
            ON CONFLICT (account_id, chat_id, telegram_message_id)
            DO UPDATE SET
                score = EXCLUDED.score,
                reasons = EXCLUDED.reasons,
                status = EXCLUDED.status,
                updated_at = NOW()
        """
        params = {
            "account_id": account_id,
            "chat_id": chat_id,
            "telegram_message_id": telegram_message_id,
            "score": score,
            "reasons": json.dumps(list(reasons)),
        }

        _execute(self._connection, sql, params)

    def pending_candidate_messages(self, limit: int) -> list[Message]:
        sql = """
            SELECT
                m.account_id,
                m.chat_id,
                m.telegram_message_id,
                m.sender_id,
                m.direction,
                m.sent_at,
                m.text,
                m.caption,
                m.reply_to_message_id
            FROM message_candidates c
            JOIN messages m
              ON m.account_id = c.account_id
             AND m.chat_id = c.chat_id
             AND m.telegram_message_id = c.telegram_message_id
            WHERE c.status = 'queued'
            ORDER BY c.created_at, c.candidate_id
            LIMIT %(limit)s
        """
        rows = _fetchall(self._connection, sql, {"limit": limit})
        return [_message_from_row(row) for row in rows]

    def mark_processed(self, messages: Sequence[Message]) -> None:
        sql = """
            UPDATE message_candidates
            SET
                status = 'processed',
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
              AND telegram_message_id = %(telegram_message_id)s
              AND status = 'queued'
        """
        for message in messages:
            params = {
                "account_id": message.account_id,
                "chat_id": message.chat_id,
                "telegram_message_id": message.telegram_message_id,
            }
            _execute(self._connection, sql, params)


class ItemRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

    def save_item(self, item: ExtractedItem) -> None:
        _upsert_item(self._connection, account_id=self._account_id, item=item)

    def apply_status_change(self, change: Mapping[str, object]) -> None:
        item_id = str(change["item_id"])
        new_status = _status_value(change.get("new_status", change.get("status")))
        reason = str(change.get("rationale", change.get("reason", "")))
        update_sql = """
            UPDATE extracted_items
            SET
                status = %(new_status)s,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND item_id = %(item_id)s
        """
        update_params = {
            "account_id": self._account_id,
            "item_id": item_id,
            "new_status": new_status,
        }
        _execute(self._connection, update_sql, update_params)

        event_sql = """
            INSERT INTO item_status_events (
                item_id,
                old_status,
                new_status,
                reason
            )
            VALUES (
                %(item_id)s,
                NULL,
                %(new_status)s,
                %(reason)s
            )
        """
        event_params = {
            "item_id": item_id,
            "new_status": new_status,
            "reason": reason,
        }
        _execute(self._connection, event_sql, event_params)


class ItemQueryRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

    def list_open_tasks(self, *, limit: int = 10) -> list[ExtractedItem]:
        sql = """
            SELECT
                item_id,
                item_type,
                title,
                description,
                confidence,
                status,
                rationale,
                due_at,
                source_refs,
                metadata
            FROM extracted_items
            WHERE account_id = %(account_id)s
              AND item_type = ANY(%(item_types)s)
              AND status = ANY(%(statuses)s)
            ORDER BY
                due_at ASC NULLS LAST,
                updated_at DESC,
                item_id ASC
            LIMIT %(limit)s
        """
        params = {
            "account_id": self._account_id,
            "item_types": [
                ItemType.TASK.value,
                ItemType.COMMITMENT.value,
                ItemType.REMINDER.value,
                ItemType.WAITING_FOR.value,
            ],
            "statuses": [
                ItemStatus.OPEN.value,
                ItemStatus.IN_PROGRESS.value,
                ItemStatus.PARTIALLY_COMPLETED.value,
                ItemStatus.WAITING_FOR.value,
            ],
            "limit": limit,
        }
        return [_item_from_row(row) for row in _fetchall(self._connection, sql, params)]

    def list_summary_items(self, *, limit: int = 20) -> list[ExtractedItem]:
        sql = """
            SELECT
                item_id,
                item_type,
                title,
                description,
                confidence,
                status,
                rationale,
                due_at,
                source_refs,
                metadata
            FROM extracted_items
            WHERE account_id = %(account_id)s
              AND item_type = ANY(%(item_types)s)
              AND status = ANY(%(statuses)s)
            ORDER BY
                due_at ASC NULLS LAST,
                updated_at DESC,
                confidence DESC,
                item_id ASC
            LIMIT %(limit)s
        """
        params = {
            "account_id": self._account_id,
            "item_types": [
                ItemType.TASK.value,
                ItemType.COMMITMENT.value,
                ItemType.REMINDER.value,
                ItemType.WAITING_FOR.value,
                ItemType.THOUGHT.value,
                ItemType.USEFUL_CONTEXT.value,
            ],
            "statuses": [
                ItemStatus.OPEN.value,
                ItemStatus.IN_PROGRESS.value,
                ItemStatus.PARTIALLY_COMPLETED.value,
                ItemStatus.WAITING_FOR.value,
            ],
            "limit": limit,
        }
        return [_item_from_row(row) for row in _fetchall(self._connection, sql, params)]


class ReviewRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

    def list_pending_reviews(self, *, limit: int = 5) -> list[ReviewEntry]:
        sql = """
            SELECT
                r.review_id,
                r.review_type,
                r.state,
                r.reason,
                r.payload,
                r.created_at,
                i.item_id,
                i.item_type,
                i.title,
                i.description,
                i.confidence,
                i.status,
                i.rationale,
                i.due_at,
                i.source_refs,
                i.metadata
            FROM review_queue r
            LEFT JOIN extracted_items i
              ON i.item_id = r.item_id
             AND i.account_id = %(account_id)s
            WHERE r.state = 'pending'
              AND (r.item_id IS NULL OR i.account_id = %(account_id)s)
            ORDER BY r.created_at ASC, r.review_id ASC
            LIMIT %(limit)s
        """
        params = {
            "account_id": self._account_id,
            "limit": limit,
        }
        return [_review_entry_from_row(row) for row in _fetchall(self._connection, sql, params)]

    def enqueue_item(self, item: ExtractedItem) -> None:
        _upsert_item(
            self._connection,
            account_id=self._account_id,
            item=item,
            status=ItemStatus.CANDIDATE,
        )
        sql = """
            INSERT INTO review_queue (
                item_id,
                review_type,
                state,
                reason,
                payload
            )
            VALUES (
                %(item_id)s,
                %(review_type)s,
                %(state)s,
                %(reason)s,
                %(payload)s::jsonb
            )
        """
        params = {
            "item_id": item.item_id,
            "review_type": "item",
            "state": "pending",
            "reason": item.rationale,
            "payload": _json_dumps(
                {
                    "confidence": item.confidence,
                    "item_type": item.item_type,
                }
            ),
        }
        _execute(self._connection, sql, params)

    def enqueue_status_change(self, change: Mapping[str, object]) -> None:
        sql = """
            INSERT INTO review_queue (
                item_id,
                review_type,
                state,
                reason,
                payload
            )
            VALUES (
                %(item_id)s,
                %(review_type)s,
                %(state)s,
                %(reason)s,
                %(payload)s::jsonb
            )
        """
        params = {
            "item_id": change.get("item_id"),
            "review_type": "status_change",
            "state": "pending",
            "reason": str(change.get("rationale", change.get("reason", ""))),
            "payload": _json_dumps(dict(change)),
        }
        _execute(self._connection, sql, params)

    def approve_review(self, review_id: int) -> str:
        review = self._get_pending_review_for_update(review_id)
        if review is None:
            return "Review is no longer pending."

        review_type = str(_row_value(review, "review_type", 1))
        if review_type == "item":
            self._activate_review_item(str(_row_value(review, "item_id", 2)))
        elif review_type == "status_change":
            self._apply_review_status_change(review)
        else:
            return "Unknown review type."

        self._resolve_review(review_id, "approved")
        return "Review approved."

    def reject_review(self, review_id: int) -> str:
        self._resolve_review(review_id, "rejected")
        return "Review rejected."

    def _get_pending_review_for_update(self, review_id: int) -> object | None:
        sql = """
            SELECT
                r.review_id,
                r.review_type,
                r.item_id,
                r.payload,
                r.reason
            FROM review_queue r
            LEFT JOIN extracted_items i
              ON i.item_id = r.item_id
             AND i.account_id = %(account_id)s
            WHERE r.review_id = %(review_id)s
              AND r.state = 'pending'
              AND (r.item_id IS NULL OR i.account_id = %(account_id)s)
            FOR UPDATE
        """
        return _fetchone(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "review_id": review_id,
            },
        )

    def _activate_review_item(self, item_id: str) -> None:
        sql = """
            UPDATE extracted_items
            SET
                status = %(status)s,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND item_id = %(item_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "item_id": item_id,
                "status": ItemStatus.OPEN.value,
            },
        )

    def _apply_review_status_change(self, review: object) -> None:
        payload = _json_object(_row_value(review, "payload", 3))
        item_id = str(payload.get("item_id", _row_value(review, "item_id", 2)))
        new_status = _status_value(payload.get("new_status", payload.get("status")))
        reason = str(payload.get("rationale", payload.get("reason", _row_value(review, "reason", 4) or "")))
        update_sql = """
            UPDATE extracted_items
            SET
                status = %(new_status)s,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND item_id = %(item_id)s
        """
        params = {
            "account_id": self._account_id,
            "item_id": item_id,
            "new_status": new_status,
        }
        _execute(self._connection, update_sql, params)

        event_sql = """
            INSERT INTO item_status_events (
                item_id,
                old_status,
                new_status,
                reason
            )
            VALUES (
                %(item_id)s,
                NULL,
                %(new_status)s,
                %(reason)s
            )
        """
        _execute(
            self._connection,
            event_sql,
            {
                "item_id": item_id,
                "new_status": new_status,
                "reason": reason,
            },
        )

    def _resolve_review(self, review_id: int, state: str) -> None:
        sql = """
            UPDATE review_queue
            SET
                state = %(state)s,
                resolved_at = NOW()
            WHERE review_id = %(review_id)s
              AND state = 'pending'
        """
        _execute(
            self._connection,
            sql,
            {
                "review_id": review_id,
                "state": state,
            },
        )


class BackfillJobQueryRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

    def latest_jobs(self, *, limit: int = 3) -> list[BackfillJobSummary]:
        sql = """
            SELECT
                backfill_job_id,
                status,
                from_date,
                to_date,
                error,
                created_at
            FROM backfill_jobs
            WHERE account_id = %(account_id)s
            ORDER BY created_at DESC, backfill_job_id DESC
            LIMIT %(limit)s
        """
        rows = _fetchall(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "limit": limit,
            },
        )
        return [_backfill_job_summary_from_row(row) for row in rows]


class RuntimeEventRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def record_event(
        self,
        *,
        component: str,
        severity: str,
        event_type: str,
        message: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        sql = """
            INSERT INTO runtime_events (
                component,
                severity,
                event_type,
                message,
                metadata
            )
            VALUES (
                %(component)s,
                %(severity)s,
                %(event_type)s,
                %(message)s,
                %(metadata)s::jsonb
            )
        """
        params = {
            "component": component,
            "severity": severity,
            "event_type": event_type,
            "message": message,
            "metadata": _json_dumps(dict(metadata or {})),
        }
        _execute(self._connection, sql, params)

    def latest_events(
        self,
        *,
        limit: int = 10,
        severities: Sequence[str] = ("warning", "error"),
    ) -> list[RuntimeEvent]:
        sql = """
            SELECT
                runtime_event_id,
                component,
                severity,
                event_type,
                message,
                metadata,
                created_at
            FROM runtime_events
            WHERE severity = ANY(%(severities)s)
            ORDER BY created_at DESC, runtime_event_id DESC
            LIMIT %(limit)s
        """
        params = {
            "severities": list(severities),
            "limit": limit,
        }
        rows = _fetchall(self._connection, sql, params)
        return [_runtime_event_from_row(row) for row in rows]


class BotRuntimeStateRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def get_last_update_id(self, *, bot_name: str) -> int | None:
        sql = """
            SELECT last_update_id
            FROM bot_runtime_state
            WHERE bot_name = %(bot_name)s
        """
        row = _fetchone(self._connection, sql, {"bot_name": bot_name})
        if row is None:
            return None
        return int(_row_value(row, "last_update_id", 0))

    def save_last_update_id(self, *, bot_name: str, last_update_id: int) -> None:
        sql = """
            INSERT INTO bot_runtime_state (
                bot_name,
                last_update_id
            )
            VALUES (
                %(bot_name)s,
                %(last_update_id)s
            )
            ON CONFLICT (bot_name)
            DO UPDATE SET
                last_update_id = EXCLUDED.last_update_id,
                updated_at = NOW()
        """
        _execute(
            self._connection,
            sql,
            {
                "bot_name": bot_name,
                "last_update_id": last_update_id,
            },
        )


class LLMRunRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def record_failure(self, error: BaseException, *, provider: str = "lm_studio", model: str = "") -> None:
        sql = """
            INSERT INTO llm_runs (
                provider,
                model,
                request_payload,
                response_payload,
                status,
                error,
                finished_at
            )
            VALUES (
                %(provider)s,
                %(model)s,
                %(request_payload)s::jsonb,
                NULL,
                %(status)s,
                %(error)s,
                NOW()
            )
        """
        params = {
            "provider": provider,
            "model": model,
            "request_payload": _json_dumps({}),
            "status": "failure",
            "error": type(error).__name__,
        }
        _execute(self._connection, sql, params)
