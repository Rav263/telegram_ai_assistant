from __future__ import annotations

import asyncio
from contextlib import suppress
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
        policy_provider: Callable[[], ChatIngestionPolicy] | None = None,
        backfill_job_runner: Any | None = None,
        backfill_batch_size: int = 25,
        backfill_poll_interval_seconds: float = 10.0,
        startup_catch_up_limit: int | None = None,
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
        self.policy_provider = policy_provider
        self.backfill_job_runner = backfill_job_runner
        self.backfill_batch_size = backfill_batch_size
        self.backfill_poll_interval_seconds = backfill_poll_interval_seconds
        self.startup_catch_up_limit = startup_catch_up_limit

    async def run_forever(self) -> ListenerRunResult:
        client = await _resolve_client(self.client_factory())
        backfill_task: asyncio.Task[None] | None = None
        try:
            logger.info("live listener starting account_id=%s", self.account_id)
            await client.listen_new_messages(self.handle_update)
            await self._run_startup_catch_up(client)
            await self._run_backfill_once(client)
            backfill_task = self._start_backfill_loop(client)
            await client.run_until_disconnected()
        finally:
            if backfill_task is not None:
                backfill_task.cancel()
                with suppress(asyncio.CancelledError):
                    await backfill_task
            await client.close()
            logger.info("live listener stopped account_id=%s", self.account_id)
        return ListenerRunResult(account_id=self.account_id, status="stopped")

    def _start_backfill_loop(self, client: Any) -> asyncio.Task[None] | None:
        if self.backfill_job_runner is None:
            return None
        return asyncio.create_task(self._run_backfill_loop(client))

    async def _run_backfill_loop(self, client: Any) -> None:
        while True:
            await asyncio.sleep(self.backfill_poll_interval_seconds)
            await self._run_backfill_once(client)

    async def _run_backfill_once(self, client: Any) -> None:
        if self.backfill_job_runner is None:
            return
        result = self.backfill_job_runner.run_once_with_client(
            limit=self.backfill_batch_size,
            client=client,
        )
        if inspect.isawaitable(result):
            await result

    async def handle_update(self, event: object) -> None:
        chat_metadata = self.chat_metadata_extractor(event)
        if not self._effective_policy().can_read(chat_metadata):
            logger.debug(
                "skipped live update account_id=%s chat_id=%s chat_type=%s",
                self.account_id,
                chat_metadata.chat_id,
                chat_metadata.chat_type,
            )
            return

        raw_message = self.message_extractor(event)
        message = self._save_message(raw_message, chat_metadata)
        logger.info(
            "saved live update account_id=%s chat_id=%s telegram_message_id=%s sender_id=%s direction=%s",
            self.account_id,
            chat_metadata.chat_id,
            message.telegram_message_id,
            message.sender_id,
            message.direction.value,
        )

    async def _run_startup_catch_up(self, client: Any) -> None:
        with self.connection_factory.connection() as connection:
            chat_repository = self.chat_repository_factory(connection)
            chats = chat_repository.list_catch_up_chats(self.account_id)

        if not chats:
            return

        policy = self._effective_policy()
        for chat in chats:
            cursor = _chat_value(chat, "last_ingested_message_id", 0)
            if cursor <= 0:
                continue
            chat_metadata = _chat_metadata_from_cursor(chat)
            if not policy.can_read(chat_metadata):
                logger.debug(
                    "skipped startup catch-up account_id=%s chat_id=%s chat_type=%s",
                    self.account_id,
                    chat_metadata.chat_id,
                    chat_metadata.chat_type,
                )
                continue

            saved_count = 0
            latest_message_id = cursor
            while True:
                batch_saved = 0
                batch_latest_message_id = latest_message_id
                async for raw_message in client.iter_new_messages(
                    chat_metadata.chat_id,
                    min_id=latest_message_id,
                    limit=self.startup_catch_up_limit,
                ):
                    message = self._save_message(raw_message, chat_metadata)
                    batch_latest_message_id = max(batch_latest_message_id, message.telegram_message_id)
                    batch_saved += 1
                    saved_count += 1
                if batch_saved == 0 or batch_latest_message_id <= latest_message_id:
                    break
                latest_message_id = batch_latest_message_id

            if saved_count:
                logger.info(
                    "startup catch-up saved messages account_id=%s chat_id=%s saved_count=%s latest_message_id=%s",
                    self.account_id,
                    chat_metadata.chat_id,
                    saved_count,
                    latest_message_id,
                )

    def _effective_policy(self) -> ChatIngestionPolicy:
        if self.policy_provider is None:
            return self.policy
        return self.policy_provider()

    def _save_message(self, raw_message: object, chat_metadata: ChatMetadata):
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
                "advanced ingestion cursor account_id=%s chat_id=%s latest_message_id=%s",
                self.account_id,
                chat_metadata.chat_id,
                max(current_cursor, message.telegram_message_id),
            )
        return message


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


def _chat_metadata_from_cursor(chat: object) -> ChatMetadata:
    chat_id = _chat_value(chat, "chat_id", 0)
    chat_type = str(_chat_value(chat, "chat_type", "") or "")
    return ChatMetadata(
        chat_id=chat_id,
        chat_type=chat_type,
        title=str(_chat_value(chat, "title", "") or ""),
        is_megagroup=chat_type == "supergroup",
        is_broadcast=chat_type in {"channel", "broadcast"},
    )


def _chat_value(chat: object, key: str, default: object) -> Any:
    if isinstance(chat, dict):
        return chat.get(key, default)
    return getattr(chat, key, default)
