from __future__ import annotations

from collections.abc import AsyncIterator
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

    async def close(self) -> None:
        pass


class ReadOnlyIngestionClient:
    def __init__(self, client: object, guard: ReadOnlyTelegramGuard | None = None):
        self._client = client
        self._guard = guard or ReadOnlyTelegramGuard()

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
