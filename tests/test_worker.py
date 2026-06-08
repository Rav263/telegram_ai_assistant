from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import (
    ExtractedItem,
    ItemStatus,
    ItemType,
    LLMActionType,
    Message,
    MessageDirection,
    SourceRef,
)
from telegram_ai_assistant.filtering import CandidateReason, CandidateScore, CandidateScoringContext
from telegram_ai_assistant.llm import LLMValidationError, ParsedLLMAction
from telegram_ai_assistant.llm_client import LMStudioError
from telegram_ai_assistant.worker import Worker, WorkerResult


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


class ContextMessageSource(FakeMessageSource):
    def __init__(self, messages, context):
        super().__init__(messages)
        self.context = context
        self.context_requests = []

    def scoring_context_for(self, message):
        self.context_requests.append(message)
        return self.context


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

    def extract_batch(self, candidate_messages, *, open_items=()):
        self.received_batches.append((tuple(candidate_messages), tuple(open_items)))
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
        self.action_reviews = []

    def enqueue_item(self, item):
        self.items.append(item)

    def enqueue_status_change(self, change):
        self.status_changes.append(change)

    def enqueue_action_review(self, action):
        self.action_reviews.append(action)


class FakeLLMActionRepository:
    def __init__(self):
        self.saved = []
        self.reviewed = []
        self.applied = []

    def save_action(self, action):
        self.saved.append(action)

    def mark_review(self, llm_action_id):
        self.reviewed.append(llm_action_id)

    def mark_applied(self, llm_action_id):
        self.applied.append(llm_action_id)


class FakeOpenItemRepository:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []

    def list_open_items_for_llm(self, *, limit):
        self.calls.append(("list_open_items_for_llm", limit))
        return self.items[:limit]


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


class FakeBackfillJobRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_once(self, *, limit):
        self.calls.append(("run_once", limit))
        return self.result


class ExtractionResult:
    def __init__(self, actions=()):
        self.actions = tuple(actions)


def make_action(
    *,
    action_type=LLMActionType.CREATE_ITEM,
    confidence=0.91,
    target_item_id=None,
    payload=None,
    source_message_ids=(200,),
    rationale="Сообщение содержит задачу.",
):
    return ParsedLLMAction(
        action_type=action_type,
        payload=payload
        or {
            "type": "task",
            "title": "Забрать ирригатор",
            "description": "Заехать на Озон и забрать ирригатор.",
            "due_at": "2026-06-07T09:00:00+00:00",
        },
        confidence=confidence,
        source_message_ids=tuple(source_message_ids),
        rationale=rationale,
        target_item_id=target_item_id,
    )


def make_open_item():
    return ExtractedItem(
        item_id="item-1",
        item_type=ItemType.TASK,
        title="Забрать ирригатор",
        description="Заехать на Озон.",
        confidence=0.91,
        status=ItemStatus.OPEN,
        sources=(SourceRef(chat_id=100, telegram_message_id=150),),
        rationale="Ранее найдено.",
    )


class WorkerTests(unittest.TestCase):
    def test_process_backfill_jobs_is_noop_without_runner(self):
        worker = Worker()

        result = worker.process_backfill_jobs(limit=10)

        self.assertEqual(result, WorkerResult())

    def test_process_backfill_jobs_does_not_run_injected_runner(self):
        runner = FakeBackfillJobRunner(
            result=type(
                "BackfillResult",
                (),
                {
                    "backfill_jobs": 1,
                    "saved_messages": 12,
                    "failures": 0,
                },
            )()
        )
        worker = Worker(backfill_job_runner=runner)

        result = worker.process_backfill_jobs(limit=25)

        self.assertEqual(runner.calls, [])
        self.assertEqual(result, WorkerResult())

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

    def test_process_messages_passes_optional_scoring_context_to_scorer(self):
        message = make_message("Завтра нужно заехать на озон, забрать ирригатор")
        source = ContextMessageSource([message], CandidateScoringContext(chat_type="private"))
        received = []

        def scorer(message_arg, context_arg=None):
            received.append((message_arg, context_arg))
            return CandidateScore(score=0.8, reasons=(CandidateReason.PRIVATE_CHAT_PRIORITY,))

        candidate_repository = FakeCandidateRepository()
        worker = Worker(message_source=source, candidate_repository=candidate_repository, scorer=scorer)

        result = worker.process_messages(limit=10)

        self.assertEqual(result.queued_candidates, 1)
        self.assertEqual(source.context_requests, [message])
        self.assertEqual(received, [(message, CandidateScoringContext(chat_type="private"))])
        self.assertIn("private_chat_priority", candidate_repository.enqueued[0]["reasons"])

    def test_process_messages_keeps_legacy_one_argument_scorers_compatible(self):
        message = make_message("надо бы проверить")
        source = ContextMessageSource([message], CandidateScoringContext(chat_type="private"))

        def scorer(message_arg):
            return CandidateScore(score=0.35, reasons=(CandidateReason.SELF_NOTE,))

        candidate_repository = FakeCandidateRepository()
        worker = Worker(message_source=source, candidate_repository=candidate_repository, scorer=scorer)

        result = worker.process_messages(limit=10)

        self.assertEqual(result.queued_candidates, 1)
        self.assertEqual(candidate_repository.enqueued[0]["reasons"], ("self_note",))

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

    def test_process_candidates_persists_actions_and_applies_policy(self):
        item_repository = FakeItemRepository()
        review_repository = FakeReviewRepository()
        action_repository = FakeLLMActionRepository()
        open_item_repository = FakeOpenItemRepository([make_open_item()])
        candidate_message = make_message("Завтра нужно заехать на озон, забрать ирригатор")
        candidate_repository = FakeCandidateRepository(candidate_messages=[candidate_message])
        extraction_service = FakeExtractionService(
            result=ExtractionResult(
                actions=(
                    make_action(confidence=0.91),
                    make_action(confidence=0.5, payload={
                        "type": "thought",
                        "title": "Возможно важно",
                        "description": "Слабый сигнал.",
                    }),
                    make_action(
                        action_type=LLMActionType.UPDATE_ITEM_STATUS,
                        target_item_id="item-1",
                        payload={"new_status": "completed"},
                        confidence=0.95,
                        rationale="Пользователь сообщил, что задача выполнена.",
                    ),
                )
            )
        )
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=extraction_service,
            item_repository=item_repository,
            review_repository=review_repository,
            llm_action_repository=action_repository,
            open_item_repository=open_item_repository,
            open_item_context_limit=200,
            item_auto_apply_threshold=0.8,
            status_auto_apply_threshold=0.8,
        )

        result = worker.process_candidates(limit=10)

        self.assertEqual(result.extracted_items, 2)
        self.assertEqual(len(item_repository.saved), 1)
        self.assertEqual(item_repository.saved[0].title, "Забрать ирригатор")
        self.assertEqual(len(action_repository.saved), 3)
        self.assertEqual(len(action_repository.applied), 1)
        self.assertEqual(len(action_repository.reviewed), 2)
        self.assertEqual(len(review_repository.action_reviews), 2)
        self.assertEqual(review_repository.action_reviews[1].action_type, LLMActionType.UPDATE_ITEM_STATUS)
        self.assertEqual(candidate_repository.acknowledged, [candidate_message])
        self.assertEqual(extraction_service.received_batches, [((candidate_message,), (make_open_item(),))])
        self.assertEqual(open_item_repository.calls, [("list_open_items_for_llm", 200)])

    def test_process_candidates_records_malformed_action_source_without_crashing(self):
        item_repository = FakeItemRepository()
        action_repository = FakeLLMActionRepository()
        runtime_events = FakeRuntimeEventRepository()
        candidate_message = make_message("Завтра нужно заехать на озон, забрать ирригатор")
        candidate_repository = FakeCandidateRepository(candidate_messages=[candidate_message])
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=FakeExtractionService(
                result=ExtractionResult(actions=(make_action(source_message_ids=(999,)),))
            ),
            item_repository=item_repository,
            llm_action_repository=action_repository,
            runtime_event_repository=runtime_events,
        )

        result = worker.process_candidates(limit=10)

        self.assertEqual(result.processed_candidates, 1)
        self.assertEqual(result.failures, 1)
        self.assertEqual(item_repository.saved, [])
        self.assertEqual(action_repository.saved, [])
        self.assertEqual(candidate_repository.acknowledged, [candidate_message])
        self.assertEqual(runtime_events.events[0]["event_type"], "llm_action_failure")
        self.assertEqual(runtime_events.events[0]["metadata"]["error_type"], "KeyError")
        self.assertNotIn("Завтра", str(runtime_events.events))

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

    def test_records_llm_validation_failure_reason_without_raw_response(self):
        candidate_repository = FakeCandidateRepository(candidate_messages=[make_message("перезвоню")])
        runtime_events = FakeRuntimeEventRepository()
        worker = Worker(
            candidate_repository=candidate_repository,
            extraction_service=FakeExtractionService(
                error=LLMValidationError("actions must be a list")
            ),
            runtime_event_repository=runtime_events,
        )

        result = worker.process_candidates(limit=10)

        metadata = runtime_events.events[0]["metadata"]
        self.assertEqual(result.failures, 1)
        self.assertEqual(metadata["error_type"], "LLMValidationError")
        self.assertEqual(metadata["validation_error"], "actions must be a list")
        self.assertNotIn("перезвоню", str(runtime_events.events))
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
