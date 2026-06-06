from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
from enum import StrEnum
from typing import Any, Protocol, Sequence

from telegram_ai_assistant.domain import (
    BackfillChatChoice,
    BackfillJobRecord,
    BackfillJobSummary,
    BotSession,
    ChatCursor,
    ChatPolicyChoice,
    ExtractedItem,
    ItemStatus,
    ItemType,
    LLMAction,
    LLMActionState,
    LLMActionType,
    Message,
    MessageDirection,
    ReviewEntry,
    RuntimeEvent,
    SourceRef,
)
from telegram_ai_assistant.filtering import CandidateScoringContext
from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy


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
        llm_action=_review_action_from_row(row),
    )


def _backfill_job_summary_from_row(row: object) -> BackfillJobSummary:
    last_error_type = str(_optional_row_value(row, "last_error_type", 8, "") or "")
    legacy_error = str(_optional_row_value(row, "error", 4, "") or "")
    return BackfillJobSummary(
        backfill_job_id=int(_row_value(row, "backfill_job_id", 0)),
        status=str(_row_value(row, "status", 1)),
        chat_id=int(_optional_row_value(row, "chat_id", 2, 0) or 0),
        chat_title=str(_optional_row_value(row, "chat_title", 3, "") or ""),
        from_date=_row_value(row, "from_date", 4),
        to_date=_row_value(row, "to_date", 5),
        saved_count=int(_optional_row_value(row, "saved_count", 6, 0) or 0),
        next_before_message_id=_optional_row_value(row, "next_before_message_id", 7, None),
        last_error_type=last_error_type,
        error=last_error_type or legacy_error,
        created_at=_row_value(row, "created_at", 9),
    )


def _backfill_chat_choice_from_row(row: object) -> BackfillChatChoice:
    return BackfillChatChoice(
        chat_id=int(_row_value(row, "chat_id", 0)),
        title=str(_row_value(row, "title", 1) or ""),
        chat_type=str(_row_value(row, "chat_type", 2) or ""),
    )


def _chat_cursor_from_row(row: object) -> ChatCursor:
    return ChatCursor(
        chat_id=int(_row_value(row, "chat_id", 0)),
        title=str(_row_value(row, "title", 1) or ""),
        chat_type=str(_row_value(row, "chat_type", 2) or ""),
        last_ingested_message_id=int(_row_value(row, "last_ingested_message_id", 3) or 0),
    )


def _chat_policy_choice_from_row(row: object) -> ChatPolicyChoice:
    return ChatPolicyChoice(
        chat_id=int(_row_value(row, "chat_id", 0)),
        title=str(_row_value(row, "title", 1) or ""),
        chat_type=str(_row_value(row, "chat_type", 2) or ""),
        policy_state=str(_row_value(row, "policy_state", 3) or "default"),
    )


def _bot_session_from_row(row: object) -> BotSession:
    return BotSession(
        telegram_user_id=int(_row_value(row, "telegram_user_id", 0)),
        bot_chat_id=int(_row_value(row, "bot_chat_id", 1)),
        flow_id=str(_row_value(row, "flow_id", 2)),
        payload=_json_object(_row_value(row, "payload", 3)),
        expires_at=_row_value(row, "expires_at", 4),
    )


def _llm_action_from_row(row: object) -> LLMAction:
    return LLMAction(
        llm_action_id=int(_row_value(row, "llm_action_id", 0)),
        action_key=str(_row_value(row, "action_key", 1)),
        action_type=LLMActionType(str(_row_value(row, "action_type", 2))),
        state=LLMActionState(str(_row_value(row, "state", 3))),
        confidence=float(_row_value(row, "confidence", 4)),
        target_item_id=_row_value(row, "target_item_id", 5),
        payload=_json_object(_row_value(row, "payload", 6)),
        source_refs=_source_refs_from_json(_row_value(row, "source_refs", 7)),
        rationale=str(_row_value(row, "rationale", 8) or ""),
        created_at=_row_value(row, "created_at", 9),
        updated_at=_row_value(row, "updated_at", 10),
    )


def _backfill_job_record_from_row(row: object) -> BackfillJobRecord:
    return BackfillJobRecord(
        backfill_job_id=int(_row_value(row, "backfill_job_id", 0)),
        account_id=str(_row_value(row, "account_id", 1)),
        chat_id=int(_row_value(row, "chat_id", 2)),
        chat_title=str(_row_value(row, "chat_title", 3) or ""),
        status=str(_row_value(row, "status", 4)),
        from_date=_row_value(row, "from_date", 5),
        to_date=_row_value(row, "to_date", 6),
        next_before_message_id=_row_value(row, "next_before_message_id", 7),
        saved_count=int(_row_value(row, "saved_count", 8) or 0),
        last_error_type=str(_row_value(row, "last_error_type", 9) or ""),
        last_error_metadata=_json_object(_row_value(row, "last_error_metadata", 10)),
        created_at=_row_value(row, "created_at", 11),
        started_at=_row_value(row, "started_at", 12),
        finished_at=_row_value(row, "finished_at", 13),
        updated_at=_row_value(row, "updated_at", 14),
    )


def _optional_row_value(row: object, key: str, index: int, default: Any) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[index]  # type: ignore[index]
    except IndexError:
        return default


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


def _review_action_from_row(row: object) -> LLMAction | None:
    llm_action_id = _optional_row_value(row, "llm_action_id", 16, None)
    if llm_action_id is None:
        return None
    return LLMAction(
        llm_action_id=int(llm_action_id),
        action_key=str(_optional_row_value(row, "action_key", 17, "")),
        action_type=LLMActionType(str(_optional_row_value(row, "action_type", 18, LLMActionType.CREATE_ITEM.value))),
        state=LLMActionState(str(_optional_row_value(row, "action_state", 19, LLMActionState.PENDING.value))),
        confidence=float(_optional_row_value(row, "action_confidence", 20, 0.0)),
        target_item_id=_optional_row_value(row, "target_item_id", 21, None),
        payload=_json_object(_optional_row_value(row, "action_payload", 22, {})),
        source_refs=_source_refs_from_json(_optional_row_value(row, "action_source_refs", 23, [])),
        rationale=str(_optional_row_value(row, "action_rationale", 24, "") or ""),
        created_at=_optional_row_value(row, "action_created_at", 25, None),
        updated_at=_optional_row_value(row, "action_updated_at", 26, None),
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


def _source_ref_values(source_refs: Sequence[SourceRef]) -> list[dict[str, int]]:
    return [
        {
            "chat_id": source.chat_id,
            "telegram_message_id": source.telegram_message_id,
        }
        for source in source_refs
    ]


def _source_refs_json_from_refs(source_refs: Sequence[SourceRef]) -> str:
    return _json_dumps(_source_ref_values(source_refs))


def _canonical_json(value: object) -> str:
    return json.dumps(_json_ready(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def llm_action_key(
    *,
    action_type: LLMActionType | str,
    source_refs: Sequence[SourceRef],
    target_item_id: str | None,
    payload: Mapping[str, object],
) -> str:
    action_type_value = action_type.value if isinstance(action_type, StrEnum) else str(action_type)
    source_values = sorted(
        _source_ref_values(source_refs),
        key=lambda source: (source["chat_id"], source["telegram_message_id"]),
    )
    canonical = _canonical_json(
        {
            "action_type": action_type_value,
            "source_refs": source_values,
            "target_item_id": target_item_id or "",
            "payload": dict(payload),
        }
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{action_type_value}:{digest}"


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

    def list_catch_up_chats(self, account_id: str) -> list[ChatCursor]:
        sql = """
            SELECT
                chat_id,
                title,
                chat_type,
                last_ingested_message_id
            FROM chats
            WHERE account_id = %(account_id)s
              AND last_ingested_message_id > 0
            ORDER BY COALESCE(last_ingested_at, created_at), chat_id
        """
        rows = _fetchall(self._connection, sql, {"account_id": account_id})
        return [_chat_cursor_from_row(row) for row in rows]


class ChatPolicyRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

    def effective_policy(
        self,
        *,
        base_allowed_channel_ids: frozenset[int] = frozenset(),
        base_denied_chat_ids: frozenset[int] = frozenset(),
    ) -> ChatIngestionPolicy:
        allowed_channel_ids, denied_chat_ids = self.effective_ids(
            base_allowed_channel_ids=base_allowed_channel_ids,
            base_denied_chat_ids=base_denied_chat_ids,
        )
        return ChatIngestionPolicy(
            allowed_channel_ids=allowed_channel_ids,
            denied_chat_ids=denied_chat_ids,
        )

    def effective_ids(
        self,
        *,
        base_allowed_channel_ids: frozenset[int] = frozenset(),
        base_denied_chat_ids: frozenset[int] = frozenset(),
    ) -> tuple[frozenset[int], frozenset[int]]:
        sql = """
            SELECT
                chat_id,
                policy_state
            FROM chat_policy_overrides
            WHERE account_id = %(account_id)s
        """
        rows = _fetchall(self._connection, sql, {"account_id": self._account_id})
        allowed = set(base_allowed_channel_ids)
        denied = set(base_denied_chat_ids)
        for row in rows:
            chat_id = int(_row_value(row, "chat_id", 0))
            state = str(_row_value(row, "policy_state", 1))
            if state == "allow":
                allowed.add(chat_id)
            elif state == "deny":
                denied.add(chat_id)
        allowed.difference_update(denied)
        return frozenset(allowed), frozenset(denied)

    def allow_chat(self, chat_id: int) -> None:
        self._set_policy(chat_id=chat_id, policy_state="allow")

    def deny_chat(self, chat_id: int) -> None:
        self._set_policy(chat_id=chat_id, policy_state="deny")

    def reset_chat(self, chat_id: int) -> None:
        sql = """
            DELETE FROM chat_policy_overrides
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "chat_id": chat_id,
            },
        )

    def _set_policy(self, *, chat_id: int, policy_state: str) -> None:
        sql = """
            INSERT INTO chat_policy_overrides (
                account_id,
                chat_id,
                policy_state
            )
            VALUES (
                %(account_id)s,
                %(chat_id)s,
                %(policy_state)s
            )
            ON CONFLICT (account_id, chat_id)
            DO UPDATE SET
                policy_state = EXCLUDED.policy_state,
                updated_at = NOW()
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "chat_id": chat_id,
                "policy_state": policy_state,
            },
        )


class BotSessionRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def save_session(
        self,
        *,
        telegram_user_id: int,
        bot_chat_id: int,
        flow_id: str,
        payload: Mapping[str, object],
        expires_at: object,
    ) -> None:
        sql = """
            INSERT INTO bot_sessions (
                telegram_user_id,
                bot_chat_id,
                flow_id,
                payload,
                expires_at
            )
            VALUES (
                %(telegram_user_id)s,
                %(bot_chat_id)s,
                %(flow_id)s,
                %(payload)s::jsonb,
                %(expires_at)s
            )
            ON CONFLICT (telegram_user_id, bot_chat_id, flow_id)
            DO UPDATE SET
                payload = EXCLUDED.payload,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW()
        """
        _execute(
            self._connection,
            sql,
            {
                "telegram_user_id": telegram_user_id,
                "bot_chat_id": bot_chat_id,
                "flow_id": flow_id,
                "payload": _json_dumps(dict(payload)),
                "expires_at": expires_at,
            },
        )

    def get_active_session(
        self,
        *,
        telegram_user_id: int,
        bot_chat_id: int,
        now: object,
    ) -> BotSession | None:
        sql = """
            SELECT
                telegram_user_id,
                bot_chat_id,
                flow_id,
                payload,
                expires_at
            FROM bot_sessions
            WHERE telegram_user_id = %(telegram_user_id)s
              AND bot_chat_id = %(bot_chat_id)s
              AND expires_at > %(now)s
            ORDER BY updated_at DESC, flow_id
            LIMIT 1
        """
        row = _fetchone(
            self._connection,
            sql,
            {
                "telegram_user_id": telegram_user_id,
                "bot_chat_id": bot_chat_id,
                "now": now,
            },
        )
        return None if row is None else _bot_session_from_row(row)

    def clear_session(self, *, telegram_user_id: int, bot_chat_id: int, flow_id: str) -> None:
        sql = """
            DELETE FROM bot_sessions
            WHERE telegram_user_id = %(telegram_user_id)s
              AND bot_chat_id = %(bot_chat_id)s
              AND flow_id = %(flow_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "telegram_user_id": telegram_user_id,
                "bot_chat_id": bot_chat_id,
                "flow_id": flow_id,
            },
        )

    def clear_user_sessions(self, *, telegram_user_id: int, bot_chat_id: int) -> None:
        sql = """
            DELETE FROM bot_sessions
            WHERE telegram_user_id = %(telegram_user_id)s
              AND bot_chat_id = %(bot_chat_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "telegram_user_id": telegram_user_id,
                "bot_chat_id": bot_chat_id,
            },
        )

    def clear_expired_sessions(self, *, now: object) -> None:
        sql = """
            DELETE FROM bot_sessions
            WHERE expires_at <= %(now)s
        """
        _execute(self._connection, sql, {"now": now})


class LLMActionRepository:
    def __init__(self, connection: Connection, *, account_id: str):
        self._connection = connection
        self._account_id = account_id

    def save_action(self, action: LLMAction) -> None:
        sql = """
            INSERT INTO llm_actions (
                account_id,
                action_key,
                action_type,
                state,
                confidence,
                target_item_id,
                payload,
                source_refs,
                rationale
            )
            VALUES (
                %(account_id)s,
                %(action_key)s,
                %(action_type)s,
                %(state)s,
                %(confidence)s,
                %(target_item_id)s,
                %(payload)s::jsonb,
                %(source_refs)s::jsonb,
                %(rationale)s
            )
            ON CONFLICT (action_key)
            DO UPDATE SET
                confidence = EXCLUDED.confidence,
                target_item_id = EXCLUDED.target_item_id,
                payload = EXCLUDED.payload,
                source_refs = EXCLUDED.source_refs,
                rationale = EXCLUDED.rationale,
                updated_at = NOW()
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "action_key": action.action_key,
                "action_type": action.action_type.value,
                "state": action.state.value,
                "confidence": action.confidence,
                "target_item_id": action.target_item_id,
                "payload": _json_dumps(action.payload),
                "source_refs": _source_refs_json_from_refs(action.source_refs),
                "rationale": action.rationale,
            },
        )

    def get_by_key(self, action_key: str) -> LLMAction | None:
        sql = """
            SELECT
                llm_action_id,
                action_key,
                action_type,
                state,
                confidence,
                target_item_id,
                payload,
                source_refs,
                rationale,
                created_at,
                updated_at
            FROM llm_actions
            WHERE account_id = %(account_id)s
              AND action_key = %(action_key)s
        """
        row = _fetchone(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "action_key": action_key,
            },
        )
        return None if row is None else _llm_action_from_row(row)

    def list_pending_review_actions(self, *, limit: int) -> list[LLMAction]:
        sql = """
            SELECT
                llm_action_id,
                action_key,
                action_type,
                state,
                confidence,
                target_item_id,
                payload,
                source_refs,
                rationale,
                created_at,
                updated_at
            FROM llm_actions
            WHERE account_id = %(account_id)s
              AND state = %(state)s
            ORDER BY created_at ASC, llm_action_id ASC
            LIMIT %(limit)s
        """
        rows = _fetchall(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "state": LLMActionState.REVIEW.value,
                "limit": limit,
            },
        )
        return [_llm_action_from_row(row) for row in rows]

    def mark_review(self, llm_action_id: int) -> None:
        self._set_state(llm_action_id, LLMActionState.REVIEW)

    def mark_applied(self, llm_action_id: int) -> None:
        sql = """
            UPDATE llm_actions
            SET
                state = %(state)s,
                applied_at = NOW(),
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND llm_action_id = %(llm_action_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "llm_action_id": llm_action_id,
                "state": LLMActionState.APPLIED.value,
            },
        )

    def mark_rejected(self, llm_action_id: int) -> None:
        sql = """
            UPDATE llm_actions
            SET
                state = %(state)s,
                rejected_at = NOW(),
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND llm_action_id = %(llm_action_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "llm_action_id": llm_action_id,
                "state": LLMActionState.REJECTED.value,
            },
        )

    def mark_failed(self, llm_action_id: int, *, error_type: str) -> None:
        sql = """
            UPDATE llm_actions
            SET
                state = %(state)s,
                payload = payload || %(failure_payload)s::jsonb,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND llm_action_id = %(llm_action_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "llm_action_id": llm_action_id,
                "state": LLMActionState.FAILED.value,
                "error_type": error_type,
                "failure_payload": _json_dumps({"error_type": error_type}),
            },
        )

    def _set_state(self, llm_action_id: int, state: LLMActionState) -> None:
        sql = """
            UPDATE llm_actions
            SET
                state = %(state)s,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND llm_action_id = %(llm_action_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "llm_action_id": llm_action_id,
                "state": state.value,
            },
        )


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
        self._scoring_contexts: dict[tuple[str, int], CandidateScoringContext] = {}

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
                m.reply_to_message_id,
                c.chat_type
            FROM messages m
            LEFT JOIN chats c
              ON c.account_id = m.account_id
             AND c.chat_id = m.chat_id
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
        messages = []
        for row in rows:
            message = _message_from_row(row)
            self._scoring_contexts[(message.account_id, message.chat_id)] = CandidateScoringContext(
                chat_type=str(_row_value(row, "chat_type", 9) or "")
            )
            messages.append(message)
        return messages

    def scoring_context_for(self, message: Message) -> CandidateScoringContext:
        key = (message.account_id, message.chat_id)
        cached = self._scoring_contexts.get(key)
        if cached is not None:
            return cached

        sql = """
            SELECT chat_type
            FROM chats
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
        """
        row = _fetchone(
            self._connection,
            sql,
            {"account_id": message.account_id, "chat_id": message.chat_id},
        )
        context = CandidateScoringContext(
            chat_type="" if row is None else str(_row_value(row, "chat_type", 0) or "")
        )
        self._scoring_contexts[key] = context
        return context

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

    def list_open_items_for_llm(self, *, limit: int = 200) -> list[ExtractedItem]:
        return self.list_summary_items(limit=limit)


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
                i.metadata,
                a.llm_action_id,
                a.action_key,
                a.action_type,
                a.state AS action_state,
                a.confidence AS action_confidence,
                a.target_item_id,
                a.payload AS action_payload,
                a.source_refs AS action_source_refs,
                a.rationale AS action_rationale,
                a.created_at AS action_created_at,
                a.updated_at AS action_updated_at
            FROM review_queue r
            LEFT JOIN extracted_items i
              ON i.item_id = r.item_id
             AND i.account_id = %(account_id)s
            LEFT JOIN llm_actions a
              ON a.llm_action_id = r.llm_action_id
             AND a.account_id = %(account_id)s
            WHERE r.state = 'pending'
              AND (r.item_id IS NULL OR i.account_id = %(account_id)s)
              AND (r.llm_action_id IS NULL OR a.account_id = %(account_id)s)
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

    def enqueue_action_review(self, action: LLMAction) -> None:
        sql = """
            INSERT INTO review_queue (
                item_id,
                llm_action_id,
                review_type,
                state,
                reason,
                payload
            )
            VALUES (
                %(item_id)s,
                %(llm_action_id)s,
                %(review_type)s,
                %(state)s,
                %(reason)s,
                %(payload)s::jsonb
            )
        """
        params = {
            "item_id": action.target_item_id,
            "llm_action_id": action.llm_action_id,
            "review_type": action.action_type.value,
            "state": "pending",
            "reason": action.rationale,
            "payload": _json_dumps(
                {
                    "confidence": action.confidence,
                    "action_key": action.action_key,
                    "action_type": action.action_type,
                    "target_item_id": action.target_item_id,
                }
            ),
        }
        _execute(self._connection, sql, params)

    def approve_review(self, review_id: int) -> str:
        review = self._get_pending_review_for_update(review_id)
        if review is None:
            return "Review is no longer pending."

        review_type = str(_row_value(review, "review_type", 1))
        llm_action_id = _optional_row_value(review, "llm_action_id", 5, None)
        if llm_action_id is not None:
            self._apply_review_action(review)
            self._mark_action_state(int(llm_action_id), LLMActionState.APPLIED)
        elif review_type == "item":
            self._activate_review_item(str(_row_value(review, "item_id", 2)))
        elif review_type == "status_change":
            self._apply_review_status_change(review)
        else:
            return "Unknown review type."

        self._resolve_review(review_id, "approved")
        return "Review approved."

    def reject_review(self, review_id: int) -> str:
        self._reject_action_for_review(review_id)
        self._resolve_review(review_id, "rejected")
        return "Review rejected."

    def _get_pending_review_for_update(self, review_id: int) -> object | None:
        sql = """
            SELECT
                r.review_id,
                r.review_type,
                r.item_id,
                r.payload,
                r.reason,
                r.llm_action_id,
                a.action_type,
                a.payload AS action_payload,
                a.target_item_id,
                a.rationale AS action_rationale,
                a.action_key,
                a.confidence AS action_confidence,
                a.source_refs AS action_source_refs
            FROM review_queue r
            LEFT JOIN extracted_items i
              ON i.item_id = r.item_id
             AND i.account_id = %(account_id)s
            LEFT JOIN llm_actions a
              ON a.llm_action_id = r.llm_action_id
             AND a.account_id = %(account_id)s
            WHERE r.review_id = %(review_id)s
              AND r.state = 'pending'
              AND (r.item_id IS NULL OR i.account_id = %(account_id)s)
              AND (r.llm_action_id IS NULL OR a.account_id = %(account_id)s)
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

    def _apply_review_action(self, review: object) -> None:
        action_type = str(_optional_row_value(review, "action_type", 6, ""))
        if action_type == LLMActionType.UPDATE_ITEM_STATUS.value:
            payload = _json_object(_optional_row_value(review, "action_payload", 7, {}))
            item_id = str(payload.get("target_item_id", _optional_row_value(review, "target_item_id", 8, "")))
            if not item_id:
                item_id = str(_optional_row_value(review, "item_id", 2))
            change = {
                "item_id": item_id,
                "new_status": payload.get("new_status"),
                "rationale": payload.get("rationale", _optional_row_value(review, "action_rationale", 9, "")),
            }
            self._apply_status_change_payload(change)
            return
        if action_type == LLMActionType.CREATE_ITEM.value:
            payload = _json_object(_optional_row_value(review, "action_payload", 7, {}))
            action_key = str(_optional_row_value(review, "action_key", 10, "") or "")
            item_id = str(payload.get("item_id", "") or "")
            if not item_id:
                item_key = action_key.split(":", 1)[1] if ":" in action_key else action_key
                item_id = f"llm-{item_key}" if item_key else f"llm-action-{_optional_row_value(review, 'llm_action_id', 5, '')}"
            due_at = payload.get("due_at")
            metadata = payload.get("metadata", {})
            item = ExtractedItem(
                item_id=item_id,
                item_type=ItemType(str(payload.get("type"))),
                title=str(payload.get("title", "")),
                description=str(payload.get("description", "")),
                confidence=float(payload.get("confidence", _optional_row_value(review, "action_confidence", 11, 0.0)) or 0.0),
                status=ItemStatus.OPEN,
                sources=_source_refs_from_json(_optional_row_value(review, "action_source_refs", 12, [])),
                rationale=str(_optional_row_value(review, "action_rationale", 9, "") or ""),
                due_at=datetime.fromisoformat(str(due_at)) if due_at else None,
                metadata={str(key): str(value) for key, value in dict(metadata).items()} if isinstance(metadata, Mapping) else {},
            )
            _upsert_item(self._connection, account_id=self._account_id, item=item)
            return
        raise ValueError(f"Unsupported LLM action review type: {action_type}")

    def _apply_status_change_payload(self, change: Mapping[str, object]) -> None:
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

    def _mark_action_state(self, llm_action_id: int, state: LLMActionState) -> None:
        sql = """
            UPDATE llm_actions
            SET
                state = %(state)s,
                applied_at = CASE WHEN %(state)s = 'applied' THEN NOW() ELSE applied_at END,
                rejected_at = CASE WHEN %(state)s = 'rejected' THEN NOW() ELSE rejected_at END,
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND llm_action_id = %(llm_action_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "llm_action_id": llm_action_id,
                "state": state.value,
            },
        )

    def _reject_action_for_review(self, review_id: int) -> None:
        sql = """
            UPDATE llm_actions
            SET
                state = %(state)s,
                rejected_at = NOW(),
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND llm_action_id = (
                  SELECT llm_action_id
                  FROM review_queue
                  WHERE review_id = %(review_id)s
                    AND llm_action_id IS NOT NULL
              )
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "review_id": review_id,
                "state": LLMActionState.REJECTED.value,
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
                chat_id,
                chat_title,
                from_date,
                to_date,
                saved_count,
                next_before_message_id,
                last_error_type,
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


class ChatQueryRepository:
    def __init__(
        self,
        connection: Connection,
        *,
        account_id: str,
        allowed_channel_ids: frozenset[int] = frozenset(),
        denied_chat_ids: frozenset[int] = frozenset(),
        policy_repository: ChatPolicyRepository | None = None,
    ):
        self._connection = connection
        self._account_id = account_id
        self._allowed_channel_ids = allowed_channel_ids
        self._denied_chat_ids = denied_chat_ids
        self._policy_repository = policy_repository

    def list_backfill_chats(self, *, page: int, page_size: int = 6) -> list[BackfillChatChoice]:
        offset = max(page, 0) * page_size
        allowed_channel_ids, denied_chat_ids = self._effective_policy_ids()
        sql = """
            SELECT
                chat_id,
                title,
                chat_type
            FROM chats
            WHERE account_id = %(account_id)s
              AND chat_id <> ALL(%(denied_chat_ids)s)
              AND (
                    chat_type IN ('private', 'group', 'supergroup')
                 OR (chat_type = 'channel' AND chat_id = ANY(%(allowed_channel_ids)s))
                 OR (chat_type = 'broadcast' AND chat_id = ANY(%(allowed_channel_ids)s))
              )
            ORDER BY COALESCE(NULLIF(title, ''), chat_id::TEXT), chat_id
            LIMIT %(limit)s
            OFFSET %(offset)s
        """
        rows = _fetchall(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "allowed_channel_ids": sorted(allowed_channel_ids),
                "denied_chat_ids": sorted(denied_chat_ids),
                "limit": page_size,
                "offset": offset,
            },
        )
        return [_backfill_chat_choice_from_row(row) for row in rows]

    def get_backfill_chat(self, chat_id: int) -> BackfillChatChoice | None:
        allowed_channel_ids, denied_chat_ids = self._effective_policy_ids()
        sql = """
            SELECT
                chat_id,
                title,
                chat_type
            FROM chats
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
              AND chat_id <> ALL(%(denied_chat_ids)s)
              AND (
                    chat_type IN ('private', 'group', 'supergroup')
                 OR (chat_type = 'channel' AND chat_id = ANY(%(allowed_channel_ids)s))
                 OR (chat_type = 'broadcast' AND chat_id = ANY(%(allowed_channel_ids)s))
              )
        """
        row = _fetchone(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "chat_id": chat_id,
                "allowed_channel_ids": sorted(allowed_channel_ids),
                "denied_chat_ids": sorted(denied_chat_ids),
            },
        )
        return None if row is None else _backfill_chat_choice_from_row(row)

    def list_policy_chats(self, *, page: int, page_size: int = 6) -> list[ChatPolicyChoice]:
        offset = max(page, 0) * page_size
        sql = """
            SELECT
                c.chat_id,
                c.title,
                c.chat_type,
                p.policy_state
            FROM chats c
            LEFT JOIN chat_policy_overrides p
              ON p.account_id = c.account_id
             AND p.chat_id = c.chat_id
            WHERE c.account_id = %(account_id)s
            ORDER BY COALESCE(NULLIF(c.title, ''), c.chat_id::TEXT), c.chat_id
            LIMIT %(limit)s
            OFFSET %(offset)s
        """
        rows = _fetchall(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "limit": page_size,
                "offset": offset,
            },
        )
        return [_chat_policy_choice_from_row(row) for row in rows]

    def _effective_policy_ids(self) -> tuple[frozenset[int], frozenset[int]]:
        if self._policy_repository is None:
            return self._allowed_channel_ids, self._denied_chat_ids
        return self._policy_repository.effective_ids(
            base_allowed_channel_ids=self._allowed_channel_ids,
            base_denied_chat_ids=self._denied_chat_ids,
        )


class BackfillJobRepository(BackfillJobQueryRepository):
    def get_job(self, backfill_job_id: int) -> BackfillJobRecord | None:
        sql = f"""
            SELECT {_BACKFILL_JOB_RETURNING_COLUMNS}
            FROM backfill_jobs
            WHERE account_id = %(account_id)s
              AND backfill_job_id = %(backfill_job_id)s
        """
        row = _fetchone(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "backfill_job_id": backfill_job_id,
            },
        )
        return None if row is None else _backfill_job_record_from_row(row)

    def create_job(
        self,
        *,
        chat_id: int,
        chat_title: str,
        from_date: datetime,
        to_date: datetime,
    ) -> BackfillJobRecord:
        sql = f"""
            INSERT INTO backfill_jobs (
                account_id,
                chat_id,
                chat_title,
                status,
                from_date,
                to_date
            )
            VALUES (
                %(account_id)s,
                %(chat_id)s,
                %(chat_title)s,
                'pending',
                %(from_date)s,
                %(to_date)s
            )
            RETURNING {_BACKFILL_JOB_RETURNING_COLUMNS}
        """
        row = _fetchone(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "chat_id": chat_id,
                "chat_title": chat_title,
                "from_date": from_date,
                "to_date": to_date,
            },
        )
        if row is None:
            raise RuntimeError("backfill job was not created")
        return _backfill_job_record_from_row(row)

    def request_cancel(self, backfill_job_id: int) -> None:
        sql = """
            UPDATE backfill_jobs
            SET
                status = 'cancel_requested',
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND backfill_job_id = %(backfill_job_id)s
              AND status IN ('pending', 'running')
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "backfill_job_id": backfill_job_id,
            },
        )

    def claim_next_job(self) -> BackfillJobRecord | None:
        sql = f"""
            UPDATE backfill_jobs
            SET
                status = CASE
                    WHEN status = 'pending' THEN 'running'
                    ELSE status
                END,
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW()
            WHERE backfill_job_id = (
                SELECT backfill_job_id
                FROM backfill_jobs
                WHERE account_id = %(account_id)s
                  AND status IN ('pending', 'running', 'cancel_requested')
                ORDER BY created_at, backfill_job_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING {_BACKFILL_JOB_RETURNING_COLUMNS}
        """
        row = _fetchone(self._connection, sql, {"account_id": self._account_id})
        return None if row is None else _backfill_job_record_from_row(row)

    def record_progress(
        self,
        *,
        backfill_job_id: int,
        saved_count: int,
        next_before_message_id: int | None,
    ) -> None:
        sql = """
            UPDATE backfill_jobs
            SET
                saved_count = saved_count + %(saved_count)s,
                next_before_message_id = %(next_before_message_id)s,
                status = 'running',
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND backfill_job_id = %(backfill_job_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "backfill_job_id": backfill_job_id,
                "saved_count": saved_count,
                "next_before_message_id": next_before_message_id,
            },
        )

    def mark_completed(self, backfill_job_id: int) -> None:
        self._mark_terminal(backfill_job_id, status="completed")

    def mark_cancelled(self, backfill_job_id: int) -> None:
        self._mark_terminal(backfill_job_id, status="cancelled")

    def mark_failed(
        self,
        backfill_job_id: int,
        *,
        error_type: str,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        sql = """
            UPDATE backfill_jobs
            SET
                status = 'failed',
                last_error_type = %(last_error_type)s,
                last_error_metadata = %(last_error_metadata)s::jsonb,
                finished_at = NOW(),
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND backfill_job_id = %(backfill_job_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "backfill_job_id": backfill_job_id,
                "last_error_type": error_type,
                "last_error_metadata": _json_dumps(metadata or {}),
            },
        )

    def _mark_terminal(self, backfill_job_id: int, *, status: str) -> None:
        sql = f"""
            UPDATE backfill_jobs
            SET
                status = '{status}',
                finished_at = NOW(),
                updated_at = NOW()
            WHERE account_id = %(account_id)s
              AND backfill_job_id = %(backfill_job_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": self._account_id,
                "backfill_job_id": backfill_job_id,
            },
        )


_BACKFILL_JOB_RETURNING_COLUMNS = """
    backfill_job_id,
    account_id,
    chat_id,
    chat_title,
    status,
    from_date,
    to_date,
    next_before_message_id,
    saved_count,
    last_error_type,
    last_error_metadata,
    created_at,
    started_at,
    finished_at,
    updated_at
"""


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
