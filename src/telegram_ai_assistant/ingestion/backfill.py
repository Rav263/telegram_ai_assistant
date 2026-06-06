from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from telegram_ai_assistant.db.repositories import AccountRepository, ChatRepository, MessageRepository
from telegram_ai_assistant.ingestion.normalizer import normalize_telegram_message
from telegram_ai_assistant.ingestion.ports import IngestionClient


@dataclass(frozen=True)
class BackfillRunResult:
    account_id: str
    chat_id: int
    start_at: datetime
    end_at: datetime
    requested_before_message_id: int | None
    next_before_message_id: int | None
    saved_count: int
    oldest_sent_at: datetime | None = None
    newest_sent_at: datetime | None = None


class BackfillService:
    def __init__(
        self,
        *,
        account_id: str,
        chat_id: int,
        start_at: datetime,
        end_at: datetime,
        before_message_id: int | None,
        limit: int,
        connection_factory: Any,
        client_factory: Callable[[], Any],
        normalizer: Callable[[str, object], Any] = normalize_telegram_message,
        account_repository_factory: Callable[[Any], Any] = AccountRepository,
        chat_repository_factory: Callable[[Any], Any] = ChatRepository,
        message_repository_factory: Callable[[Any], Any] = MessageRepository,
    ):
        self.account_id = account_id
        self.chat_id = chat_id
        self.start_at = start_at
        self.end_at = end_at
        self.before_message_id = before_message_id
        self.limit = limit
        self.connection_factory = connection_factory
        self.client_factory = client_factory
        self.normalizer = normalizer
        self.account_repository_factory = account_repository_factory
        self.chat_repository_factory = chat_repository_factory
        self.message_repository_factory = message_repository_factory

    async def run_once(self) -> BackfillRunResult:
        client = await _resolve_client(self.client_factory())
        try:
            return await self.run_once_with_client(client)
        finally:
            await client.close()

    async def run_once_with_client(self, client: Any) -> BackfillRunResult:
        with self.connection_factory.connection() as connection:
            account_repository = self.account_repository_factory(connection)
            chat_repository = self.chat_repository_factory(connection)
            message_repository = self.message_repository_factory(connection)

            account_repository.ensure_account(self.account_id)
            chat_repository.ensure_chat(self.account_id, self.chat_id)

            saved_count = 0
            next_before_message_id = self.before_message_id
            oldest_sent_at: datetime | None = None
            newest_sent_at: datetime | None = None
            async for raw_message in client.iter_backfill_messages(
                self.chat_id,
                start_at=self.start_at,
                end_at=self.end_at,
                before_message_id=self.before_message_id,
                limit=self.limit,
            ):
                message = self.normalizer(self.account_id, raw_message)
                message_repository.upsert_message(message)
                saved_count += 1
                next_before_message_id = (
                    message.telegram_message_id
                    if next_before_message_id is None
                    else min(next_before_message_id, message.telegram_message_id)
                )
                oldest_sent_at = (
                    message.sent_at if oldest_sent_at is None else min(oldest_sent_at, message.sent_at)
                )
                newest_sent_at = (
                    message.sent_at if newest_sent_at is None else max(newest_sent_at, message.sent_at)
                )

            return BackfillRunResult(
                account_id=self.account_id,
                chat_id=self.chat_id,
                start_at=self.start_at,
                end_at=self.end_at,
                requested_before_message_id=self.before_message_id,
                next_before_message_id=next_before_message_id,
                saved_count=saved_count,
                oldest_sent_at=oldest_sent_at,
                newest_sent_at=newest_sent_at,
            )


async def _resolve_client(value: Any) -> IngestionClient:
    if inspect.isawaitable(value):
        return await value
    return value
