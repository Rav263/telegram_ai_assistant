from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
from enum import StrEnum
from typing import Any, Protocol, Sequence

from telegram_ai_assistant.domain import (
    ExtractedItem,
    ItemStatus,
    Message,
    MessageDirection,
    RuntimeEvent,
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


class ReviewRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

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
