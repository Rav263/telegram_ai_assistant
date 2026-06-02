from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.content import ContentExtractor, TextContentExtractor
from telegram_ai_assistant.domain import Message, MessageDirection


class TextContentExtractorTests(unittest.TestCase):
    def test_extracts_message_content_text(self):
        message = Message(
            account_id="primary",
            chat_id=1001,
            telegram_message_id=42,
            sender_id=5001,
            direction=MessageDirection.INCOMING,
            sent_at=datetime(2026, 6, 2, 9, 15, tzinfo=UTC),
            text="  Need the invoice today  ",
            caption="ignored caption",
            reply_to_message_id=41,
        )
        extractor: ContentExtractor = TextContentExtractor()

        self.assertEqual(extractor.extract(message), "Need the invoice today")

    def test_extracts_caption_when_text_is_empty(self):
        message = Message(
            account_id="primary",
            chat_id=1001,
            telegram_message_id=43,
            sender_id=7001,
            direction=MessageDirection.OUTGOING,
            sent_at=datetime(2026, 6, 2, 10, 30, tzinfo=UTC),
            caption="Receipt attached",
            reply_to_message_id=42,
        )

        self.assertEqual(TextContentExtractor().extract(message), "Receipt attached")


if __name__ == "__main__":
    unittest.main()
