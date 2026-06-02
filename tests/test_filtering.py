from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.filtering import CandidateReason, score_message


def make_message(text: str, direction: MessageDirection = MessageDirection.OUTGOING) -> Message:
    return Message(
        account_id="main",
        chat_id=100,
        telegram_message_id=200,
        sender_id=300,
        direction=direction,
        sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
        text=text,
    )


class CandidateFilterTests(unittest.TestCase):
    def test_flags_implicit_copy_task_without_direct_task_word(self):
        result = score_message(make_message("Если там сейчас есть что-то важное, то скопируйте это оттуда."))

        self.assertGreaterEqual(result.score, 0.6)
        self.assertIn(CandidateReason.IMPLIED_REQUEST, result.reasons)

    def test_flags_owner_time_commitment(self):
        result = score_message(make_message("Через минут 30-40 перезвоню"))

        self.assertGreaterEqual(result.score, 0.7)
        self.assertIn(CandidateReason.TIME_EXPRESSION, result.reasons)
        self.assertIn(CandidateReason.OWNER_COMMITMENT, result.reasons)

    def test_ignores_empty_text(self):
        result = score_message(make_message("   "))

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.reasons, ())


if __name__ == "__main__":
    unittest.main()
