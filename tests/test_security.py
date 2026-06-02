import unittest

from telegram_ai_assistant.security import BotAccessController


class BotAccessTests(unittest.TestCase):
    def test_allows_configured_owner(self):
        controller = BotAccessController(allowed_user_id=123)

        self.assertTrue(controller.is_allowed(123))

    def test_rejects_other_users(self):
        controller = BotAccessController(allowed_user_id=123)

        self.assertFalse(controller.is_allowed(456))


if __name__ == "__main__":
    unittest.main()
