from pathlib import Path
import json
import unittest

from telegram_ai_assistant.domain import LLMActionType
from telegram_ai_assistant.llm import parse_action_response


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "llm_actions_ru.json"


class LLMActionFixtureTests(unittest.TestCase):
    def test_synthetic_russian_action_fixtures_parse_to_expected_actions(self):
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["name"]):
                result = parse_action_response(json.dumps(case["response"], ensure_ascii=False))
                action_types = [action.action_type for action in result.actions]

                self.assertEqual(
                    action_types,
                    [LLMActionType(action_type) for action_type in case["expected_action_types"]],
                )
                for action in result.actions:
                    self.assertTrue(action.rationale)
                    if action.action_type == LLMActionType.CREATE_ITEM:
                        self.assertRegex(str(action.payload["title"]), r"[А-Яа-яЁё]")
                        self.assertRegex(str(action.payload["description"]), r"[А-Яа-яЁё]")


if __name__ == "__main__":
    unittest.main()
