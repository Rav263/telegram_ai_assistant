import json
import unittest

from telegram_ai_assistant.domain import ItemType
from telegram_ai_assistant.llm import LLMValidationError, parse_extraction_response


class LLMParsingTests(unittest.TestCase):
    def test_parse_valid_extraction_response(self):
        payload = json.dumps({
            "items": [
                {
                    "type": "commitment",
                    "title": "Перезвонить",
                    "description": "Автор обещал перезвонить через 30-40 минут.",
                    "confidence": 0.93,
                    "source_message_ids": [200],
                    "rationale": "Фраза содержит личное обещание и время.",
                }
            ],
            "status_changes": [],
        })

        result = parse_extraction_response(payload)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].item_type, ItemType.COMMITMENT)
        self.assertEqual(result.items[0].source_message_ids, (200,))

    def test_rejects_invalid_confidence(self):
        payload = json.dumps({
            "items": [
                {
                    "type": "task",
                    "title": "Bad",
                    "description": "Bad",
                    "confidence": 2.0,
                    "source_message_ids": [200],
                    "rationale": "Bad",
                }
            ],
            "status_changes": [],
        })

        with self.assertRaises(LLMValidationError):
            parse_extraction_response(payload)


if __name__ == "__main__":
    unittest.main()
