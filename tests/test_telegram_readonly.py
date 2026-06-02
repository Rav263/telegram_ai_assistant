import unittest

from telegram_ai_assistant.telegram_readonly import MutatingTelegramMethodError, ReadOnlyTelegramGuard


class ReadOnlyTelegramGuardTests(unittest.TestCase):
    def test_allows_non_mutating_methods(self):
        guard = ReadOnlyTelegramGuard()

        guard.assert_allowed("iter_messages")
        guard.assert_allowed("get_dialogs")

    def test_rejects_mark_read_and_send_methods(self):
        guard = ReadOnlyTelegramGuard()

        with self.assertRaises(MutatingTelegramMethodError):
            guard.assert_allowed("send_message")

        with self.assertRaises(MutatingTelegramMethodError):
            guard.assert_allowed("send_read_acknowledge")


if __name__ == "__main__":
    unittest.main()
