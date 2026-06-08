import json
import unittest

from telegram_ai_assistant.domain import ItemStatus, ItemType, LLMActionType
from telegram_ai_assistant.llm import (
    ALLOWED_UPDATE_FIELDS,
    LLMValidationError,
    action_response_format,
    parse_action_response,
)


class LLMParsingTests(unittest.TestCase):
    def test_action_response_format_provides_strict_json_schema(self):
        response_format = action_response_format()

        self.assertEqual(response_format["type"], "json_schema")
        json_schema = response_format["json_schema"]
        self.assertEqual(json_schema["name"], "telegram_action_response")
        self.assertTrue(json_schema["strict"])
        schema = json_schema["schema"]
        self.assertEqual(schema["required"], ["actions"])
        branches = schema["properties"]["actions"]["items"]["oneOf"]
        action_schema = next(
            branch for branch in branches if branch["properties"]["type"]["enum"] == ["create_item"]
        )
        self.assertEqual(
            action_schema["required"],
            ["type", "target_item_id", "payload", "confidence", "source_message_ids", "rationale"],
        )
        self.assertFalse(action_schema["additionalProperties"])

    def test_action_response_format_has_one_branch_per_action_type(self):
        response_format = action_response_format()

        action_schema = response_format["json_schema"]["schema"]["properties"]["actions"]["items"]
        branches = action_schema["oneOf"]
        branch_types = {branch["properties"]["type"]["enum"][0] for branch in branches}

        self.assertEqual(branch_types, {action_type.value for action_type in LLMActionType})

    def test_action_response_format_uses_domain_enums(self):
        response_format = action_response_format()
        branches = response_format["json_schema"]["schema"]["properties"]["actions"]["items"]["oneOf"]
        create_item = next(
            branch for branch in branches if branch["properties"]["type"]["enum"] == ["create_item"]
        )
        update_status = next(
            branch for branch in branches if branch["properties"]["type"]["enum"] == ["update_item_status"]
        )
        update_field = next(
            branch for branch in branches if branch["properties"]["type"]["enum"] == ["update_item_field"]
        )

        self.assertEqual(
            set(create_item["properties"]["payload"]["properties"]["type"]["enum"]),
            {item_type.value for item_type in ItemType},
        )
        self.assertEqual(
            set(update_status["properties"]["payload"]["properties"]["new_status"]["enum"]),
            {status.value for status in ItemStatus},
        )
        self.assertEqual(
            set(update_field["properties"]["payload"]["properties"]["field"]["enum"]),
            set(ALLOWED_UPDATE_FIELDS),
        )

    def test_action_response_format_rejects_empty_required_strings(self):
        response_format = action_response_format()
        branches = response_format["json_schema"]["schema"]["properties"]["actions"]["items"]["oneOf"]
        create_item = next(
            branch for branch in branches if branch["properties"]["type"]["enum"] == ["create_item"]
        )

        payload_properties = create_item["properties"]["payload"]["properties"]

        self.assertEqual(payload_properties["title"]["minLength"], 1)
        self.assertEqual(payload_properties["description"]["minLength"], 1)
        self.assertEqual(create_item["properties"]["rationale"]["minLength"], 1)

    def test_action_response_format_returns_fresh_dict(self):
        first = action_response_format()
        second = action_response_format()

        first["json_schema"]["name"] = "mutated"

        self.assertEqual(second["json_schema"]["name"], "telegram_action_response")

    def test_parse_valid_action_response(self):
        payload = json.dumps({
            "actions": [
                {
                    "type": "create_item",
                    "payload": {
                        "type": "reminder",
                        "title": "Забрать ирригатор",
                        "description": "Завтра заехать на Озон и забрать ирригатор.",
                        "due_at": "2026-06-07T09:00:00+00:00",
                    },
                    "confidence": 0.93,
                    "source_message_ids": [200],
                    "rationale": "Сообщение содержит задачу и срок.",
                },
                {
                    "type": "update_item_status",
                    "target_item_id": "item-1",
                    "payload": {"new_status": "completed"},
                    "confidence": 0.84,
                    "source_message_ids": [201],
                    "rationale": "Пользователь написал, что задача выполнена.",
                },
                {
                    "type": "update_item_field",
                    "target_item_id": "item-2",
                    "payload": {"field": "title", "new_value": "Позвонить врачу"},
                    "confidence": 0.75,
                    "source_message_ids": [202],
                    "rationale": "Пользователь уточнил название задачи.",
                },
                {
                    "type": "merge_duplicate",
                    "target_item_id": "item-3",
                    "payload": {"duplicate_item_id": "item-4"},
                    "confidence": 0.7,
                    "source_message_ids": [203],
                    "rationale": "Сообщение повторяет существующую задачу.",
                },
                {
                    "type": "schedule_notification",
                    "target_item_id": "item-5",
                    "payload": {
                        "due_at": "2026-06-07T09:00:00+00:00",
                        "notification_type": "reminder",
                    },
                    "confidence": 0.9,
                    "source_message_ids": [204],
                    "rationale": "Есть явный срок напоминания.",
                },
                {
                    "type": "link_source",
                    "target_item_id": "item-6",
                    "payload": {"source_message_ids": [205]},
                    "confidence": 0.81,
                    "source_message_ids": [205],
                    "rationale": "Сообщение добавляет источник к задаче.",
                },
            ],
        })

        result = parse_action_response(payload)

        self.assertEqual(len(result.actions), 6)
        self.assertEqual(result.actions[0].action_type, LLMActionType.CREATE_ITEM)
        self.assertEqual(result.actions[0].payload["title"], "Забрать ирригатор")
        self.assertEqual(result.actions[0].source_message_ids, (200,))
        self.assertEqual(result.actions[1].target_item_id, "item-1")
        self.assertEqual(result.actions[1].payload["new_status"], ItemStatus.COMPLETED.value)

    def test_rejects_invalid_action_confidence(self):
        payload = json.dumps({
            "actions": [
                {
                    "type": "create_item",
                    "payload": {
                        "type": "task",
                        "title": "Плохая задача",
                        "description": "Плохая задача",
                    },
                    "confidence": 2.0,
                    "source_message_ids": [200],
                    "rationale": "Плохая уверенность.",
                }
            ]
        })

        with self.assertRaises(LLMValidationError):
            parse_action_response(payload)

    def test_rejects_unknown_action_type(self):
        payload = json.dumps({
            "actions": [
                {
                    "type": "delete_database",
                    "payload": {},
                    "confidence": 0.9,
                    "source_message_ids": [200],
                    "rationale": "Опасное действие.",
                }
            ]
        })

        with self.assertRaises(LLMValidationError):
            parse_action_response(payload)

    def test_rejects_invalid_status_and_field_actions(self):
        invalid_status = json.dumps({
            "actions": [
                {
                    "type": "update_item_status",
                    "target_item_id": "item-1",
                    "payload": {"new_status": "done-ish"},
                    "confidence": 0.9,
                    "source_message_ids": [200],
                    "rationale": "Неверный статус.",
                }
            ]
        })
        invalid_field = json.dumps({
            "actions": [
                {
                    "type": "update_item_field",
                    "target_item_id": "item-1",
                    "payload": {"field": "secret", "new_value": "x"},
                    "confidence": 0.9,
                    "source_message_ids": [200],
                    "rationale": "Неверное поле.",
                }
            ]
        })

        with self.assertRaises(LLMValidationError):
            parse_action_response(invalid_status)
        with self.assertRaises(LLMValidationError):
            parse_action_response(invalid_field)

    def test_rejects_naive_due_at_and_empty_source_ids(self):
        naive_due_at = json.dumps({
            "actions": [
                {
                    "type": "schedule_notification",
                    "payload": {"due_at": "2026-06-07T09:00:00", "notification_type": "reminder"},
                    "confidence": 0.9,
                    "source_message_ids": [200],
                    "rationale": "Нет часового пояса.",
                }
            ]
        })
        missing_sources = json.dumps({
            "actions": [
                {
                    "type": "link_source",
                    "target_item_id": "item-1",
                    "payload": {"source_message_ids": []},
                    "confidence": 0.9,
                    "source_message_ids": [],
                    "rationale": "Нет источников.",
                }
            ]
        })

        with self.assertRaises(LLMValidationError):
            parse_action_response(naive_due_at)
        with self.assertRaises(LLMValidationError):
            parse_action_response(missing_sources)

    def test_rejects_non_russian_create_item_user_facing_text(self):
        payload = json.dumps({
            "actions": [
                {
                    "type": "create_item",
                    "payload": {
                        "type": "task",
                        "title": "Call Alice",
                        "description": "Call Alice tomorrow",
                    },
                    "confidence": 0.91,
                    "source_message_ids": [200],
                    "rationale": "Message is English.",
                }
            ]
        })

        with self.assertRaises(LLMValidationError):
            parse_action_response(payload)


if __name__ == "__main__":
    unittest.main()
