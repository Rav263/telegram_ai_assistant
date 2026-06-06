from datetime import UTC, datetime
import json
import unittest

from telegram_ai_assistant.domain import ExtractedItem, ItemStatus, ItemType, LLMActionType, Message, MessageDirection, SourceRef
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


def make_open_item() -> ExtractedItem:
    return ExtractedItem(
        item_id="item-1",
        item_type=ItemType.TASK,
        title="Забрать ирригатор",
        description="Заехать на Озон и забрать заказ.",
        confidence=0.91,
        status=ItemStatus.OPEN,
        sources=(SourceRef(chat_id=100, telegram_message_id=150),),
        rationale="Ранее найденная задача.",
    )


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def extract_json(self, *, messages):
        self.calls.append(messages)
        return self.response


class ExtractionServiceTests(unittest.TestCase):
    def test_build_extraction_prompt_includes_candidate_messages_and_open_items(self):
        prompt = build_extraction_prompt([make_message(message_id=200)], open_items=[make_open_item()])

        system_message = next(message for message in prompt if message["role"] == "system")
        user_message = next(message for message in prompt if message["role"] == "user")
        self.assertIn("All user-facing generated text must be Russian.", system_message["content"])
        self.assertIn("Propose actions only.", system_message["content"])
        self.assertIn("Завтра нужно заехать на озон, забрать ирригатор", system_message["content"])
        self.assertIn("Candidate messages:", user_message["content"])
        self.assertIn("Open items:", user_message["content"])
        self.assertIn('"telegram_message_id": 200', user_message["content"])
        self.assertIn("I will call Alice back", user_message["content"])
        self.assertIn('"item_id": "item-1"', user_message["content"])

    def test_extract_batch_returns_typed_actions(self):
        llm_payload = json.dumps(
            {
                "actions": [
                    {
                        "type": "create_item",
                        "payload": {
                            "type": "commitment",
                            "title": "Перезвонить Алисе",
                            "description": "Автор обещал перезвонить Алисе в течение 30 минут.",
                        },
                        "confidence": 0.91,
                        "source_message_ids": [200],
                        "rationale": "Сообщение содержит явное обещание.",
                    },
                    {
                        "type": "update_item_status",
                        "target_item_id": "item-1",
                        "payload": {"new_status": "completed"},
                        "confidence": 0.82,
                        "source_message_ids": [200],
                        "rationale": "Сообщение указывает на выполнение.",
                    },
                ],
            }
        )
        llm_client = FakeLLMClient(llm_payload)
        service = ExtractionService(llm_client=llm_client)

        result = service.extract_batch([make_message(message_id=200)], open_items=[make_open_item()])

        self.assertEqual(len(llm_client.calls), 1)
        self.assertEqual(len(result.actions), 2)
        self.assertEqual(result.actions[0].action_type, LLMActionType.CREATE_ITEM)
        self.assertEqual(result.actions[0].payload["title"], "Перезвонить Алисе")
        self.assertEqual(result.actions[1].target_item_id, "item-1")


if __name__ == "__main__":
    unittest.main()
