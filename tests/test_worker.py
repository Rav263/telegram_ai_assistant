from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import ExtractedItem, ItemType, Message, MessageDirection, SourceRef
from telegram_ai_assistant.filtering import CandidateReason, CandidateScore
from telegram_ai_assistant.llm_client import LMStudioError
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
        self.processed = []
        self.failed = []

    def pending_messages(self, limit):
        return self.messages[:limit]

    def mark_candidate_filter_processed(self, messages):
        self.processed.extend(messages)

    def mark_candidate_filter_failed(self, message, error_type):
        self.failed.append((message, error_type))


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
        self.failures.append(type(error).__name__)


class FakeRuntimeEventRepository:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)


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

    def test_marks_positive_score_messages_processed_after_enqueue(self):
        message = make_message("Через минут 30-40 перезвоню")
        message_source = FakeMessageSource([message])
        worker = Worker(
            message_source=message_source,
            candidate_repository=FakeCandidateRepository(),
        )

        result = worker.process_messages(limit=10)

        self.assertEqual(result.scored_messages, 1)
        self.assertEqual(message_source.processed, [message])
        self.assertEqual(message_source.failed, [])

    def test_marks_zero_score_messages_processed_without_enqueue(self):
        message = make_message("Привет")
        message_source = FakeMessageSource([message])
        candidate_repository = FakeCandidateRepository()
        worker = Worker(
            message_source=message_source,
            candidate_repository=candidate_repository,
        )

        result = worker.process_messages(limit=10)

        self.assertEqual(result.scored_messages, 1)
        self.assertEqual(candidate_repository.enqueued, [])
        self.assertEqual(message_source.processed, [message])

    def test_marks_scorer_failures_and_continues_without_raw_error_text(self):
        failed_message = make_message("secret text", telegram_message_id=201)
        good_message = make_message("надо бы проверить", telegram_message_id=202)
        message_source = FakeMessageSource([failed_message, good_message])
        candidate_repository = FakeCandidateRepository()

        def scorer(message):
            if message.telegram_message_id == 201:
                raise RuntimeError("private message text")
            return CandidateScore(score=0.35, reasons=(CandidateReason.SELF_NOTE,))

        worker = Worker(
            message_source=message_source,
            candidate_repository=candidate_repository,
            scorer=scorer,
        )

        result = worker.process_messages(limit=10)

        self.assertEqual(result.scored_messages, 1)
        self.assertEqual(result.queued_candidates, 1)
        self.assertEqual(result.failures, 1)
        self.assertEqual(message_source.failed, [(failed_message, "RuntimeError")])
        self.assertNotIn("private message text", str(message_source.failed))
        self.assertEqual(message_source.processed, [good_message])

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
        runtime_events = FakeRuntimeEventRepository()
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=FakeExtractionService(error=RuntimeError("LM Studio unavailable")),
            llm_run_repository=llm_runs,
            runtime_event_repository=runtime_events,
        )

        result = worker.process_candidates(limit=10)

        self.assertEqual(result.failures, 1)
        self.assertEqual(llm_runs.failures, ["RuntimeError"])
        self.assertEqual(runtime_events.events[0]["component"], "worker")
        self.assertEqual(runtime_events.events[0]["severity"], "warning")
        self.assertEqual(runtime_events.events[0]["event_type"], "llm_failure")
        self.assertEqual(runtime_events.events[0]["metadata"]["error_type"], "RuntimeError")
        self.assertNotIn("LM Studio unavailable", str(runtime_events.events))
        self.assertEqual(candidate_repository.acknowledged, [])

    def test_records_lm_failure_safe_diagnostics_without_raw_details(self):
        candidate_repository = FakeCandidateRepository(candidate_messages=[make_message("перезвоню")])
        runtime_events = FakeRuntimeEventRepository()
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=FakeExtractionService(
                error=LMStudioError(
                    "failed with private details",
                    safe_metadata={
                        "endpoint_scheme": "http",
                        "endpoint_host": "127.0.0.1",
                        "endpoint_path": "/v1/chat/completions",
                        "transport_error_type": "URLError",
                        "timeout_seconds": 300.0,
                        "max_tokens": 8192,
                        "max_completion_tokens": 8192,
                        "failure_stage": "response_schema",
                        "response_keys": ["error", "object"],
                        "choices_count": 0,
                        "choice_keys": ["finish_reason", "message"],
                        "finish_reason": "length",
                        "message_keys": ["content", "role"],
                        "content_type": "str",
                        "content_length": 0,
                        "reasoning_content_length": 120,
                        "raw": "secret",
                    },
                )
            ),
            runtime_event_repository=runtime_events,
        )

        result = worker.process_candidates(limit=10)

        metadata = runtime_events.events[0]["metadata"]
        self.assertEqual(result.failures, 1)
        self.assertEqual(metadata["error_type"], "LMStudioError")
        self.assertEqual(metadata["endpoint_host"], "127.0.0.1")
        self.assertEqual(metadata["transport_error_type"], "URLError")
        self.assertEqual(metadata["timeout_seconds"], 300.0)
        self.assertEqual(metadata["max_tokens"], 8192)
        self.assertEqual(metadata["max_completion_tokens"], 8192)
        self.assertEqual(metadata["failure_stage"], "response_schema")
        self.assertEqual(metadata["response_keys"], ["error", "object"])
        self.assertEqual(metadata["choices_count"], 0)
        self.assertEqual(metadata["choice_keys"], ["finish_reason", "message"])
        self.assertEqual(metadata["finish_reason"], "length")
        self.assertEqual(metadata["message_keys"], ["content", "role"])
        self.assertEqual(metadata["content_type"], "str")
        self.assertEqual(metadata["content_length"], 0)
        self.assertEqual(metadata["reasoning_content_length"], 120)
        self.assertNotIn("raw", metadata)
        self.assertNotIn("private details", str(runtime_events.events))


if __name__ == "__main__":
    unittest.main()
