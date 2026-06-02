from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import (
    ExtractedItem,
    ItemStatus,
    ItemType,
    Message,
    MessageDirection,
    SourceRef,
)


class DomainTests(unittest.TestCase):
    def test_message_requires_text_or_caption_for_text_content(self):
        message = Message(
            account_id="main",
            chat_id=100,
            telegram_message_id=200,
            sender_id=300,
            direction=MessageDirection.INCOMING,
            sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
            text="",
            caption="Перезвоню через 30 минут",
        )

        self.assertEqual(message.content_text, "Перезвоню через 30 минут")

    def test_extracted_item_keeps_source_refs_and_default_open_status(self):
        source = SourceRef(chat_id=100, telegram_message_id=200)
        item = ExtractedItem(
            item_id="item-1",
            item_type=ItemType.COMMITMENT,
            title="Перезвонить",
            description="Автор обещал перезвонить через 30 минут.",
            confidence=0.9,
            sources=(source,),
        )

        self.assertEqual(item.status, ItemStatus.OPEN)
        self.assertEqual(item.sources, (source,))


if __name__ == "__main__":
    unittest.main()
