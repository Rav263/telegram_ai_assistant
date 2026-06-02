from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import ExtractedItem, ItemType, Message, MessageDirection, SourceRef
from telegram_ai_assistant.worker import Worker


def make_message(text: str, telegram_message_id: int = 200) -> Message:
    return Message(
        account_id="main",
        chat_id=100,
        telegram_message_id=telegram_message_id,
        sender_id=300,
        direction=MessageDirection.OUTGOING,
        sent_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
        text=text,
    )


class FakeMessageSource:
    def __init__(self, messages):
        self.messages = list(messages)

    def pending_messages(self, limit):
        return self.messages[:limit]


class FakeCandidateRepository:
    def __init__(self, candidate_messages=()):
        self.enqueued = []
        self.candidate_messages = list(candidate_messages)
        self.acknowledged = []

    def enqueue_candidate(self, **kwargs):
        self.enqueued.append(kwargs)

    def pending_candidate_messages(self, limit):
        return self.candidate_messages[:limit]

    def mark_processed(self, messages):
        self.acknowledged.extend(messages)


class FakeExtractionService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.received_batches = []

    def extract_batch(self, candidate_messages):
        self.received_batches.append(tuple(candidate_messages))
        if self.error is not None:
            raise self.error
        return self.result


class FakeItemRepository:
    def __init__(self):
        self.saved = []

    def save_item(self, item):
        self.saved.append(item)


class FakeReviewRepository:
    def __init__(self):
        self.items = []
        self.status_changes = []

    def enqueue_item(self, item):
        self.items.append(item)

    def enqueue_status_change(self, change):
        self.status_changes.append(change)


class FakeLLMRunRepository:
    def __init__(self):
        self.failures = []

    def record_failure(self, error):
        self.failures.append(str(error))


class ExtractionResult:
    def __init__(self, items=(), status_changes=()):
        self.items = tuple(items)
        self.status_changes = tuple(status_changes)


class WorkerTests(unittest.TestCase):
    def test_scores_messages_and_enqueues_broad_candidates(self):
        candidate_repository = FakeCandidateRepository()
        worker = Worker(
            message_source=FakeMessageSource([make_message("Через минут 30-40 перезвоню")]),
            candidate_repository=candidate_repository,
        )

        result = worker.process_messages(limit=10)

        self.assertEqual(result.scored_messages, 1)
        self.assertEqual(len(candidate_repository.enqueued), 1)
        self.assertEqual(candidate_repository.enqueued[0]["telegram_message_id"], 200)
        self.assertIn("owner_commitment", candidate_repository.enqueued[0]["reasons"])

    def test_extracts_high_confidence_items_and_routes_low_confidence_to_review(self):
        high_confidence = ExtractedItem(
            item_id="high",
            item_type=ItemType.COMMITMENT,
            title="Перезвонить",
            description="Перезвонить через 30 минут",
            confidence=0.91,
            sources=(SourceRef(chat_id=100, telegram_message_id=200),),
        )
        low_confidence = ExtractedItem(
            item_id="low",
            item_type=ItemType.THOUGHT,
            title="Возможно важно",
            description="Слабый сигнал",
            confidence=0.5,
            sources=(SourceRef(chat_id=100, telegram_message_id=200),),
        )
        item_repository = FakeItemRepository()
        review_repository = FakeReviewRepository()
        candidate_repository = FakeCandidateRepository(candidate_messages=[make_message("перезвоню")])
        extraction_service = FakeExtractionService(
            result=ExtractionResult(
                items=(high_confidence, low_confidence),
                status_changes=({"item_id": "task-1", "confidence": 0.4},),
            )
        )
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=extraction_service,
            item_repository=item_repository,
            review_repository=review_repository,
            item_auto_apply_threshold=0.8,
            status_auto_apply_threshold=0.8,
        )

        result = worker.process_candidates(limit=10)

        self.assertEqual(result.extracted_items, 2)
        self.assertEqual(item_repository.saved, [high_confidence])
        self.assertEqual(review_repository.items, [low_confidence])
        self.assertEqual(len(review_repository.status_changes), 1)
        self.assertEqual(candidate_repository.acknowledged, [make_message("перезвоню")])

    def test_records_lm_failure_without_acknowledging_candidate(self):
        candidate_repository = FakeCandidateRepository(candidate_messages=[make_message("перезвоню")])
        llm_runs = FakeLLMRunRepository()
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=FakeExtractionService(error=RuntimeError("LM Studio unavailable")),
            llm_run_repository=llm_runs,
        )

        result = worker.process_candidates(limit=10)

        self.assertEqual(result.failures, 1)
        self.assertEqual(llm_runs.failures, ["LM Studio unavailable"])
        self.assertEqual(candidate_repository.acknowledged, [])


if __name__ == "__main__":
    unittest.main()
