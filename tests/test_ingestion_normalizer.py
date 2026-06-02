from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import MessageDirection
from telegram_ai_assistant.ingestion.normalizer import normalize_telegram_message


@dataclass
class TelegramLikeMessage:
    id: int
    chat_id: int
    sender_id: int
    date: datetime
    message: str = ""
    text: str = ""
    raw_text: str = ""
    reply_to_msg_id: int | None = None
    out: bool = False
    caption: str = ""


class TelegramMessageNormalizerTests(unittest.TestCase):
    def test_normalizes_incoming_text_message(self):
        sent_at = datetime(2026, 6, 2, 9, 15, tzinfo=UTC)
        raw_message = TelegramLikeMessage(
            id=42,
            chat_id=1001,
            sender_id=5001,
            date=sent_at,
            message="  Need the invoice today  ",
            reply_to_msg_id=41,
        )

        message = normalize_telegram_message("primary", raw_message)

        self.assertEqual(message.account_id, "primary")
        self.assertEqual(message.chat_id, 1001)
        self.assertEqual(message.telegram_message_id, 42)
        self.assertEqual(message.sender_id, 5001)
        self.assertEqual(message.direction, MessageDirection.INCOMING)
        self.assertEqual(message.sent_at, sent_at)
        self.assertEqual(message.text, "  Need the invoice today  ")
        self.assertEqual(message.caption, "")
        self.assertEqual(message.reply_to_message_id, 41)

    def test_normalizes_outgoing_caption_message(self):
        sent_at = datetime(2026, 6, 2, 10, 30, tzinfo=UTC)
        raw_message = TelegramLikeMessage(
            id=43,
            chat_id=1001,
            sender_id=7001,
            date=sent_at,
            message="",
            text="",
            raw_text="ignored fallback",
            out=True,
            caption="Receipt attached",
        )

        message = normalize_telegram_message("primary", raw_message)

        self.assertEqual(message.direction, MessageDirection.OUTGOING)
        self.assertEqual(message.text, "")
        self.assertEqual(message.caption, "Receipt attached")
        self.assertEqual(message.content_text, "Receipt attached")


if __name__ == "__main__":
    unittest.main()
