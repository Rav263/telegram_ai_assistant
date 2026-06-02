from __future__ import annotations

from typing import Any

from telegram_ai_assistant.ingestion.ports import ReadOnlyIngestionClient
from telegram_ai_assistant.telegram_readonly import ReadOnlyTelegramGuard


class TelethonAdapterError(RuntimeError):
    pass


class TelethonIngestionAdapter(ReadOnlyIngestionClient):
    """Read-only Telethon adapter shell.

    Unit tests cover the guard boundary. Real-account unread/read-state behavior
    still needs the manual smoke test before using this adapter against Telegram.
    """

    @classmethod
    async def connect(
        cls,
        session: str,
        api_id: int,
        api_hash: str,
        *,
        guard: ReadOnlyTelegramGuard | None = None,
        **client_kwargs: Any,
    ) -> TelethonIngestionAdapter:
        telegram_client_class = _load_telegram_client()
        client = telegram_client_class(session, api_id, api_hash, **client_kwargs)
        connect_result = client.connect()
        if hasattr(connect_result, "__await__"):
            await connect_result
        return cls(client, guard=guard or ReadOnlyTelegramGuard())


def _load_telegram_client() -> type[Any]:
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise TelethonAdapterError("Telethon is required to use TelethonIngestionAdapter") from exc
    return TelegramClient
