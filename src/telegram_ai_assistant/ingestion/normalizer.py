from __future__ import annotations

from datetime import datetime
from typing import Any

from telegram_ai_assistant.domain import Message, MessageDirection


def normalize_telegram_message(account_id: str, raw_message: object) -> Message:
    caption = _coerce_text(getattr(raw_message, "caption", ""))
    text = "" if caption else _first_text(raw_message, ("message", "text", "raw_text"))

    return Message(
        account_id=account_id,
        chat_id=int(getattr(raw_message, "chat_id")),
        telegram_message_id=int(getattr(raw_message, "id")),
        sender_id=int(getattr(raw_message, "sender_id")),
        direction=MessageDirection.OUTGOING if bool(getattr(raw_message, "out", False)) else MessageDirection.INCOMING,
        sent_at=_message_date(raw_message),
        text=text,
        caption=caption,
        reply_to_message_id=_reply_to_message_id(raw_message),
    )


def _first_text(raw_message: object, attribute_names: tuple[str, ...]) -> str:
    for attribute_name in attribute_names:
        value = _coerce_text(getattr(raw_message, attribute_name, ""))
        if value:
            return value
    return ""


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _message_date(raw_message: object) -> datetime:
    value = getattr(raw_message, "date")
    if not isinstance(value, datetime):
        raise TypeError("Telegram message date must be a datetime")
    return value


def _reply_to_message_id(raw_message: object) -> int | None:
    direct_value = getattr(raw_message, "reply_to_msg_id", None)
    if direct_value is not None:
        return int(direct_value)

    reply_to = getattr(raw_message, "reply_to", None)
    nested_value = getattr(reply_to, "reply_to_msg_id", None)
    if nested_value is not None:
        return int(nested_value)

    return None
