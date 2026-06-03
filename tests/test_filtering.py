from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.filtering import CandidateReason, CandidateScoringContext, score_message


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

    def test_flags_private_chat_ozon_pickup_as_strong_task_candidate(self):
        result = score_message(
            make_message("Завтра нужно заехать на озон, забрать ирригатор"),
            CandidateScoringContext(chat_type="private"),
        )

        self.assertGreaterEqual(result.score, 0.8)
        self.assertIn(CandidateReason.TIME_EXPRESSION, result.reasons)
        self.assertIn(CandidateReason.TASK_INTENT, result.reasons)
        self.assertIn(CandidateReason.ERRAND_ACTION, result.reasons)
        self.assertIn(CandidateReason.LOGISTICS_CONTEXT, result.reasons)
        self.assertIn(CandidateReason.PRIVATE_CHAT_PRIORITY, result.reasons)

    def test_group_chat_ozon_pickup_passes_without_private_priority(self):
        private_result = score_message(
            make_message("Завтра нужно заехать на озон, забрать ирригатор"),
            CandidateScoringContext(chat_type="private"),
        )
        group_result = score_message(
            make_message("Завтра нужно заехать на озон, забрать ирригатор"),
            CandidateScoringContext(chat_type="supergroup"),
        )

        self.assertGreaterEqual(group_result.score, 0.6)
        self.assertLess(group_result.score, private_result.score)
        self.assertNotIn(CandidateReason.PRIVATE_CHAT_PRIORITY, group_result.reasons)

    def test_weak_abstract_need_phrase_stays_low_without_errand_reasons(self):
        result = score_message(
            make_message("Нужно понимать контекст"),
            CandidateScoringContext(chat_type="supergroup"),
        )

        self.assertGreater(result.score, 0.0)
        self.assertLess(result.score, 0.6)
        self.assertIn(CandidateReason.TASK_INTENT, result.reasons)
        self.assertNotIn(CandidateReason.ERRAND_ACTION, result.reasons)
        self.assertNotIn(CandidateReason.LOGISTICS_CONTEXT, result.reasons)
        self.assertNotIn(CandidateReason.PRIVATE_CHAT_PRIORITY, result.reasons)

    def test_overlapping_weak_intent_phrase_is_not_double_counted(self):
        result = score_message(
            make_message("надо бы подумать"),
            CandidateScoringContext(chat_type="supergroup"),
        )

        self.assertGreater(result.score, 0.0)
        self.assertLess(result.score, 0.6)
        self.assertIn(CandidateReason.TASK_INTENT, result.reasons)
        self.assertNotIn(CandidateReason.SELF_NOTE, result.reasons)
        self.assertNotIn(CandidateReason.ERRAND_ACTION, result.reasons)

    def test_time_expression_without_action_does_not_create_candidate(self):
        result = score_message(
            make_message("Сегодня хорошая погода"),
            CandidateScoringContext(chat_type="private"),
        )

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.reasons, ())

    def test_ignores_empty_text(self):
        result = score_message(make_message("   "))

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.reasons, ())


if __name__ == "__main__":
    unittest.main()
