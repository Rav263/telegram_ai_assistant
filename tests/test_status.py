import unittest

from telegram_ai_assistant.domain import ItemStatus
from telegram_ai_assistant.status import ProposedStatusChange, ReviewDecision, apply_status_policy


class StatusPolicyTests(unittest.TestCase):
    def test_high_confidence_status_change_is_applied(self):
        change = ProposedStatusChange(
            item_id="task-1",
            new_status=ItemStatus.COMPLETED,
            confidence=0.91,
            rationale="Owner wrote that payment was sent.",
        )

        decision = apply_status_policy(change, auto_apply_threshold=0.85)

        self.assertEqual(decision, ReviewDecision.APPLY)

    def test_low_confidence_status_change_goes_to_review(self):
        change = ProposedStatusChange(
            item_id="task-1",
            new_status=ItemStatus.PARTIALLY_COMPLETED,
            confidence=0.62,
            rationale="Owner may have completed one part.",
        )

        decision = apply_status_policy(change, auto_apply_threshold=0.85)

        self.assertEqual(decision, ReviewDecision.REVIEW)


if __name__ == "__main__":
    unittest.main()
