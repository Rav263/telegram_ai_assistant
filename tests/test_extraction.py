from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.domain import ItemStatus, ItemType, Message, MessageDirection, SourceRef
from telegram_ai_assistant.extraction import ExtractionService, build_extraction_prompt


def make_message(message_id=200, text="I will call Alice back in 30 minutes."):
    return Message(
        account_id="main",
        chat_id=100,
        telegram_message_id=message_id,
        sender_id=300,
        direction=MessageDirection.OUTGOING,
        sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
        text=text,
    )


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def extract_json(self, *, messages):
        self.calls.append(messages)
        return self.response


class ExtractionServiceTests(unittest.TestCase):
    def test_build_extraction_prompt_includes_source_message_ids(self):
        prompt = build_extraction_prompt([make_message(message_id=200)])

        user_message = next(message for message in prompt if message["role"] == "user")
        self.assertIn('"telegram_message_id": 200', user_message["content"])
        self.assertIn("I will call Alice back", user_message["content"])

    def test_extract_batch_returns_domain_items_and_status_changes(self):
        llm_payload = json.dumps(
            {
                "items": [
                    {
                        "type": "commitment",
                        "title": "Call Alice",
                        "description": "The sender promised to call Alice back soon.",
                        "confidence": 0.91,
                        "source_message_ids": [200],
                        "rationale": "The message contains an explicit promise.",
                    }
                ],
                "status_changes": [
                    {
                        "item_id": "existing-1",
                        "new_status": "completed",
                        "source_message_ids": [200],
                    }
                ],
            }
        )
        llm_client = FakeLLMClient(llm_payload)
        service = ExtractionService(llm_client=llm_client)

        result = service.extract_batch([make_message(message_id=200)])

        self.assertEqual(len(llm_client.calls), 1)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.item_type, ItemType.COMMITMENT)
        self.assertEqual(item.status, ItemStatus.OPEN)
        self.assertEqual(item.sources, (SourceRef(chat_id=100, telegram_message_id=200),))
        self.assertEqual(result.status_changes[0]["item_id"], "existing-1")


if __name__ == "__main__":
    unittest.main()
