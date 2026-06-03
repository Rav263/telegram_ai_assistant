from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telegram_ai_assistant.db.repositories import AccountRepository, ChatRepository, MessageRepository
from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy, ChatMetadata
from telegram_ai_assistant.ingestion.normalizer import normalize_telegram_message
from telegram_ai_assistant.ingestion.ports import IngestionClient


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ListenerRunResult:
    account_id: str
    status: str


class LiveUpdateListener:
    def __init__(
        self,
        *,
        account_id: str,
        connection_factory: Any,
        client_factory: Callable[[], Any],
        policy: ChatIngestionPolicy,
        normalizer: Callable[[str, object], Any] = normalize_telegram_message,
        account_repository_factory: Callable[[Any], Any] = AccountRepository,
        chat_repository_factory: Callable[[Any], Any] = ChatRepository,
        message_repository_factory: Callable[[Any], Any] = MessageRepository,
        now: Callable[[], datetime] | None = None,
        chat_metadata_extractor: Callable[[object], ChatMetadata] | None = None,
        message_extractor: Callable[[object], object] | None = None,
    ):
        self.account_id = account_id
        self.connection_factory = connection_factory
        self.client_factory = client_factory
        self.policy = policy
        self.normalizer = normalizer
        self.account_repository_factory = account_repository_factory
        self.chat_repository_factory = chat_repository_factory
        self.message_repository_factory = message_repository_factory
        self.now = now or (lambda: datetime.now(UTC))
        self.chat_metadata_extractor = chat_metadata_extractor or extract_chat_metadata
        self.message_extractor = message_extractor or extract_event_message

    async def run_forever(self) -> ListenerRunResult:
        client = await _resolve_client(self.client_factory())
        try:
            logger.info("live listener starting account_id=%s", self.account_id)
            await client.listen_new_messages(self.handle_update)
            await client.run_until_disconnected()
        finally:
            await client.close()
            logger.info("live listener stopped account_id=%s", self.account_id)
        return ListenerRunResult(account_id=self.account_id, status="stopped")

    async def handle_update(self, event: object) -> None:
        chat_metadata = self.chat_metadata_extractor(event)
        if not self.policy.can_read(chat_metadata):
            logger.debug(
                "skipped live update account_id=%s chat_id=%s chat_type=%s",
                self.account_id,
                chat_metadata.chat_id,
                chat_metadata.chat_type,
            )
            return

        raw_message = self.message_extractor(event)
        message = self.normalizer(self.account_id, raw_message)

        with self.connection_factory.connection() as connection:
            account_repository = self.account_repository_factory(connection)
            chat_repository = self.chat_repository_factory(connection)
            message_repository = self.message_repository_factory(connection)

            account_repository.ensure_account(self.account_id)
            chat_repository.ensure_chat(
                self.account_id,
                chat_metadata.chat_id,
                chat_metadata.title,
                chat_metadata.chat_type,
            )
            message_repository.upsert_message(message)
            current_cursor = chat_repository.get_last_ingested_message_id(
                self.account_id,
                chat_metadata.chat_id,
            )
            chat_repository.update_ingestion_cursor(
                self.account_id,
                chat_metadata.chat_id,
                max(current_cursor, message.telegram_message_id),
                self.now(),
            )
            logger.info(
                "saved live update account_id=%s chat_id=%s telegram_message_id=%s sender_id=%s direction=%s",
                self.account_id,
                chat_metadata.chat_id,
                message.telegram_message_id,
                message.sender_id,
                message.direction.value,
            )


async def _resolve_client(value: Any) -> IngestionClient:
    if inspect.isawaitable(value):
        return await value
    return value


def extract_event_message(event: object) -> object:
    return getattr(event, "message")


def extract_chat_metadata(event: object) -> ChatMetadata:
    chat = getattr(event, "chat", None)
    message = extract_event_message(event)
    chat_id = int(getattr(message, "chat_id"))
    is_megagroup = bool(getattr(chat, "megagroup", False))
    is_broadcast = bool(getattr(chat, "broadcast", False))
    title = str(getattr(chat, "title", "") or getattr(chat, "first_name", "") or "")
    chat_type = _chat_type(chat, is_megagroup, is_broadcast)
    return ChatMetadata(
        chat_id=chat_id,
        chat_type=chat_type,
        title=title,
        is_megagroup=is_megagroup,
        is_broadcast=is_broadcast,
    )


def _chat_type(chat: object, is_megagroup: bool, is_broadcast: bool) -> str:
    if is_broadcast:
        return "channel"
    if is_megagroup:
        return "supergroup"
    class_name = chat.__class__.__name__.lower() if chat is not None else ""
    if "chat" in class_name:
        return "group"
    if "user" in class_name:
        return "private"
    return "unknown"
