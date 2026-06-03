from __future__ import annotations

import json
from typing import Protocol, Sequence

from telegram_ai_assistant.domain import Message


class Cursor(Protocol):
    def execute(self, sql: str, params: object | None = None) -> object:
        ...

    def fetchone(self) -> object:
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
