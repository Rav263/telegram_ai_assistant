from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .filtering import score_message


@dataclass(frozen=True)
class WorkerResult:
    scored_messages: int = 0
    queued_candidates: int = 0
    processed_candidates: int = 0
    extracted_items: int = 0
    saved_items: int = 0
    review_items: int = 0
    review_status_changes: int = 0
    failures: int = 0


class Worker:
    def __init__(
        self,
        *,
        message_source: Any | None = None,
        candidate_repository: Any | None = None,
        extraction_service: Any | None = None,
        item_repository: Any | None = None,
        review_repository: Any | None = None,
        llm_run_repository: Any | None = None,
        scorer: Callable[[Any], Any] = score_message,
        item_auto_apply_threshold: float = 0.8,
        status_auto_apply_threshold: float = 0.8,
    ):
        self.message_source = message_source
        self.candidate_repository = candidate_repository
        self.extraction_service = extraction_service
        self.item_repository = item_repository
        self.review_repository = review_repository
        self.llm_run_repository = llm_run_repository
        self.scorer = scorer
        self.item_auto_apply_threshold = item_auto_apply_threshold
        self.status_auto_apply_threshold = status_auto_apply_threshold

    def process_messages(self, *, limit: int) -> WorkerResult:
        messages = tuple(self.message_source.pending_messages(limit))
        scored = 0
        queued = 0
        failures = 0
        for message in messages:
            try:
                candidate = self.scorer(message)
            except Exception as exc:
                self._call_optional(
                    self.message_source,
                    "mark_candidate_filter_failed",
                    message,
                    type(exc).__name__,
                )
                failures += 1
                continue

            scored += 1
            if candidate.score <= 0:
                self._call_optional(self.message_source, "mark_candidate_filter_processed", [message])
                continue
            self.candidate_repository.enqueue_candidate(
                account_id=message.account_id,
                chat_id=message.chat_id,
                telegram_message_id=message.telegram_message_id,
                score=candidate.score,
                reasons=tuple(reason.value for reason in candidate.reasons),
            )
            queued += 1
            self._call_optional(self.message_source, "mark_candidate_filter_processed", [message])

        return WorkerResult(scored_messages=scored, queued_candidates=queued, failures=failures)

    def process_candidates(self, *, limit: int) -> WorkerResult:
        candidate_messages = tuple(self.candidate_repository.pending_candidate_messages(limit))
        if not candidate_messages:
            return WorkerResult()

        try:
            extraction = self.extraction_service.extract_batch(candidate_messages)
        except Exception as exc:
            if self.llm_run_repository is not None:
                self.llm_run_repository.record_failure(exc)
            return WorkerResult(processed_candidates=0, failures=1)

        saved_items = 0
        review_items = 0
        for item in extraction.items:
            if item.confidence >= self.item_auto_apply_threshold:
                self.item_repository.save_item(item)
                saved_items += 1
            else:
                self.review_repository.enqueue_item(item)
                review_items += 1

        review_status_changes = 0
        for status_change in extraction.status_changes:
            confidence = float(status_change.get("confidence", 0.0))
            if confidence >= self.status_auto_apply_threshold:
                self._call_optional(self.item_repository, "apply_status_change", status_change)
            else:
                self.review_repository.enqueue_status_change(status_change)
                review_status_changes += 1

        self._call_optional(self.candidate_repository, "mark_processed", list(candidate_messages))

        return WorkerResult(
            processed_candidates=len(candidate_messages),
            extracted_items=len(extraction.items),
            saved_items=saved_items,
            review_items=review_items,
            review_status_changes=review_status_changes,
        )

    def _call_optional(self, target: Any, method_name: str, *args: Any) -> None:
        method = getattr(target, method_name, None)
        if method is not None:
            method(*args)
