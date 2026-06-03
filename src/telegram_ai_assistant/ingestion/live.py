from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telegram_ai_assistant.db.repositories import AccountRepository, ChatRepository, MessageRepository
from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.ingestion.normalizer import normalize_telegram_message
from telegram_ai_assistant.ingestion.ports import IngestionClient


@dataclass(frozen=True)
class IngestedMessageDebug:
    telegram_message_id: int
    sender_id: int
    direction: MessageDirection
    sent_at: datetime
    text: str
    caption: str


@dataclass(frozen=True)
class IngestionRunResult:
    account_id: str
    chat_id: int
    requested_min_id: int
    saved_count: int
    latest_message_id: int
    debug_messages: tuple[IngestedMessageDebug, ...] = ()


class LiveIngestor:
    def __init__(
        self,
        *,
        account_id: str,
        chat_id: int,
        limit: int,
        connection_factory: Any,
        client_factory: Callable[[], Any],
        normalizer: Callable[[str, object], Any] = normalize_telegram_message,
        account_repository_factory: Callable[[Any], Any] = AccountRepository,
        chat_repository_factory: Callable[[Any], Any] = ChatRepository,
        message_repository_factory: Callable[[Any], Any] = MessageRepository,
        now: Callable[[], datetime] | None = None,
        debug_messages: bool = False,
    ):
        self.account_id = account_id
        self.chat_id = chat_id
        self.limit = limit
        self.connection_factory = connection_factory
        self.client_factory = client_factory
        self.normalizer = normalizer
        self.account_repository_factory = account_repository_factory
        self.chat_repository_factory = chat_repository_factory
        self.message_repository_factory = message_repository_factory
        self.now = now or (lambda: datetime.now(UTC))
        self.debug_messages = debug_messages

    async def run_once(self) -> IngestionRunResult:
        with self.connection_factory.connection() as connection:
            account_repository = self.account_repository_factory(connection)
            chat_repository = self.chat_repository_factory(connection)
            message_repository = self.message_repository_factory(connection)

            account_repository.ensure_account(self.account_id)
            chat_repository.ensure_chat(self.account_id, self.chat_id)
            requested_min_id = chat_repository.get_last_ingested_message_id(self.account_id, self.chat_id)

            client = await _resolve_client(self.client_factory())
            saved_count = 0
            latest_message_id = requested_min_id
            debug_messages: list[IngestedMessageDebug] = []
            try:
                async for raw_message in client.iter_new_messages(
                    self.chat_id,
                    min_id=requested_min_id,
                    limit=self.limit,
                ):
                    message = self.normalizer(self.account_id, raw_message)
                    message_repository.upsert_message(message)
                    saved_count += 1
                    latest_message_id = max(latest_message_id, message.telegram_message_id)
                    if self.debug_messages:
                        debug_messages.append(_debug_message(message))
            finally:
                await client.close()

            if saved_count:
                chat_repository.update_ingestion_cursor(
                    self.account_id,
                    self.chat_id,
                    latest_message_id,
                    self.now(),
                )

            return IngestionRunResult(
                account_id=self.account_id,
                chat_id=self.chat_id,
                requested_min_id=requested_min_id,
                saved_count=saved_count,
                latest_message_id=latest_message_id,
                debug_messages=tuple(debug_messages),
            )


async def _resolve_client(value: Any) -> IngestionClient:
    if inspect.isawaitable(value):
        return await value
    return value


def _debug_message(message: Message) -> IngestedMessageDebug:
    return IngestedMessageDebug(
        telegram_message_id=message.telegram_message_id,
        sender_id=message.sender_id,
        direction=message.direction,
        sent_at=message.sent_at,
        text=message.text,
        caption=message.caption,
    )
