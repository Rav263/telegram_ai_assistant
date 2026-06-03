from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
import inspect
from typing import Any, Protocol

from telegram_ai_assistant.telegram_readonly import ReadOnlyTelegramGuard


class IngestionClient(Protocol):
    async def iter_history(self, chat_id: int, *, limit: int | None = None) -> AsyncIterator[object]:
        pass

    async def iter_new_messages(
        self,
        chat_id: int,
        *,
        min_id: int | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        pass

    async def iter_recent_messages(
        self,
        chat_id: int,
        *,
        since: datetime,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        pass

    async def iter_backfill_messages(
        self,
        chat_id: int,
        *,
        start_at: datetime,
        end_at: datetime,
        before_message_id: int | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        pass

    async def get_latest_message_id(self, chat_id: int) -> int:
        pass

    async def listen_new_messages(self, handler: Callable[[object], Awaitable[None]]) -> None:
        pass

    async def run_until_disconnected(self) -> None:
        pass

    async def close(self) -> None:
        pass


class ReadOnlyIngestionClient:
    def __init__(
        self,
        client: object,
        guard: ReadOnlyTelegramGuard | None = None,
        new_message_event_factory: Callable[[], object] | None = None,
    ):
        self._client = client
        self._guard = guard or ReadOnlyTelegramGuard()
        self._new_message_event_factory = new_message_event_factory

    async def iter_history(self, chat_id: int, *, limit: int | None = None) -> AsyncIterator[object]:
        method = self._allowed_method("iter_messages")
        stream = method(chat_id, limit=limit, reverse=False)
        async for message in await _resolve_async_iterable(stream):
            yield message

    async def iter_new_messages(
        self,
        chat_id: int,
        *,
        min_id: int | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        method = self._allowed_method("iter_messages")
        stream = method(chat_id, limit=limit, min_id=min_id, reverse=True)
        async for message in await _resolve_async_iterable(stream):
            yield message

    async def iter_recent_messages(
        self,
        chat_id: int,
        *,
        since: datetime,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        method = self._allowed_method("iter_messages")
        stream = method(chat_id, limit=limit, offset_date=since, reverse=True)
        async for message in await _resolve_async_iterable(stream):
            yield message

    async def iter_backfill_messages(
        self,
        chat_id: int,
        *,
        start_at: datetime,
        end_at: datetime,
        before_message_id: int | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[object]:
        method = self._allowed_method("iter_messages")
        stream = method(
            chat_id,
            limit=limit,
            max_id=0 if before_message_id is None else before_message_id,
            offset_date=end_at,
            reverse=False,
        )
        async for message in await _resolve_async_iterable(stream):
            message_date = getattr(message, "date", None)
            if isinstance(message_date, datetime) and message_date < start_at:
                break
            yield message

    async def get_latest_message_id(self, chat_id: int) -> int:
        method = self._allowed_method("get_messages")
        messages = method(chat_id, limit=1)
        if inspect.isawaitable(messages):
            messages = await messages
        if not messages:
            return 0
        return int(getattr(messages[0], "id", 0))

    async def listen_new_messages(self, handler: Callable[[object], Awaitable[None]]) -> None:
        method = self._allowed_method("add_event_handler")
        if self._new_message_event_factory is None:
            raise RuntimeError("NewMessage event factory is not configured")
        method(handler, self._new_message_event_factory())

    async def run_until_disconnected(self) -> None:
        await self.call("run_until_disconnected")

    async def call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        method = self._allowed_method(method_name)
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def close(self) -> None:
        method_name = "disconnect" if hasattr(self._client, "disconnect") else "close"
        await self.call(method_name)

    def _allowed_method(self, method_name: str) -> Any:
        self._guard.assert_allowed(method_name)
        return getattr(self._client, method_name)


async def _resolve_async_iterable(value: Any) -> AsyncIterator[object]:
    if inspect.isawaitable(value):
        value = await value
    return value
