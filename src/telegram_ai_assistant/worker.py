from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import inspect
from typing import Any

from .domain import ExtractedItem, ItemStatus, ItemType, LLMAction, LLMActionState, LLMActionType, SourceRef
from .db.repositories import llm_action_key
from .filtering import score_message
from .llm import LLMValidationError

SAFE_LLM_FAILURE_METADATA_KEYS = (
    "endpoint_scheme",
    "endpoint_host",
    "endpoint_path",
    "http_status",
    "transport_error_type",
    "timeout_seconds",
    "max_tokens",
    "max_completion_tokens",
    "context_length",
    "applied_context_length",
    "configured_model_key",
    "request_body_bytes",
    "message_count",
    "prompt_characters",
    "response_format_name",
    "observed_model_count",
    "observed_instance_count",
    "mismatched_instance_count",
    "instance_id",
    "failure_stage",
    "response_keys",
    "choices_count",
    "choice_keys",
    "finish_reason",
    "message_keys",
    "content_type",
    "content_length",
    "reasoning_content_length",
    "validation_error",
)


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
    backfill_jobs: int = 0
    backfill_saved_messages: int = 0
    backfill_failures: int = 0


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
        runtime_event_repository: Any | None = None,
        llm_action_repository: Any | None = None,
        open_item_repository: Any | None = None,
        open_item_context_limit: int = 200,
        backfill_job_runner: Any | None = None,
        scorer: Callable[..., Any] = score_message,
        item_auto_apply_threshold: float = 0.8,
        status_auto_apply_threshold: float = 0.8,
    ):
        self.message_source = message_source
        self.candidate_repository = candidate_repository
        self.extraction_service = extraction_service
        self.item_repository = item_repository
        self.review_repository = review_repository
        self.llm_run_repository = llm_run_repository
        self.runtime_event_repository = runtime_event_repository
        self.llm_action_repository = llm_action_repository
        self.open_item_repository = open_item_repository
        self.open_item_context_limit = open_item_context_limit
        self.backfill_job_runner = backfill_job_runner
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
                candidate = self._score_message(message)
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
            open_items = tuple(self._open_items_for_llm())
            extraction = self.extraction_service.extract_batch(candidate_messages, open_items=open_items)
        except Exception as exc:
            if self.llm_run_repository is not None:
                self.llm_run_repository.record_failure(exc)
            if self.runtime_event_repository is not None:
                self.runtime_event_repository.record_event(
                    component="worker",
                    severity="warning",
                    event_type="llm_failure",
                    message="LLM batch failed",
                    metadata=self._llm_failure_metadata(exc, candidate_count=len(candidate_messages)),
                )
            return WorkerResult(processed_candidates=0, failures=1)

        saved_items = 0
        review_items = 0
        review_status_changes = 0
        extracted_items = 0
        failures = 0
        for parsed_action in extraction.actions:
            try:
                action = self._domain_action(parsed_action, candidate_messages)
            except Exception as exc:
                failures += 1
                self._record_action_failure(exc, parsed_action)
                continue
            self._call_optional(self.llm_action_repository, "save_action", action)
            persisted_action = self._persisted_action(action)
            if parsed_action.action_type == LLMActionType.CREATE_ITEM:
                extracted_items += 1
                if parsed_action.confidence >= self.item_auto_apply_threshold:
                    self.item_repository.save_item(self._item_from_create_action(persisted_action))
                    self._call_optional(self.llm_action_repository, "mark_applied", persisted_action.llm_action_id)
                    saved_items += 1
                    continue
                review_items += 1
            elif parsed_action.action_type == LLMActionType.UPDATE_ITEM_STATUS:
                review_status_changes += 1
            else:
                review_items += 1
            self._call_optional(self.llm_action_repository, "mark_review", persisted_action.llm_action_id)
            self._call_optional(self.review_repository, "enqueue_action_review", persisted_action)

        self._call_optional(self.candidate_repository, "mark_processed", list(candidate_messages))

        return WorkerResult(
            processed_candidates=len(candidate_messages),
            extracted_items=extracted_items,
            saved_items=saved_items,
            review_items=review_items,
            review_status_changes=review_status_changes,
            failures=failures,
        )

    def process_backfill_jobs(self, *, limit: int) -> WorkerResult:
        return WorkerResult()

    def _call_optional(self, target: Any, method_name: str, *args: Any) -> None:
        if target is None:
            return
        method = getattr(target, method_name, None)
        if method is not None:
            method(*args)

    def _open_items_for_llm(self) -> tuple[ExtractedItem, ...]:
        if self.open_item_repository is None:
            return ()
        lister = getattr(self.open_item_repository, "list_open_items_for_llm", None)
        if lister is None:
            lister = getattr(self.open_item_repository, "list_summary_items", None)
        if lister is None:
            return ()
        return tuple(lister(limit=self.open_item_context_limit))

    def _domain_action(self, parsed_action: Any, candidate_messages: tuple[Any, ...]) -> LLMAction:
        source_refs = self._source_refs(parsed_action.source_message_ids, candidate_messages)
        action_key = llm_action_key(
            action_type=parsed_action.action_type,
            source_refs=source_refs,
            target_item_id=parsed_action.target_item_id,
            payload=parsed_action.payload,
        )
        return LLMAction(
            action_key=action_key,
            action_type=parsed_action.action_type,
            state=LLMActionState.PENDING,
            confidence=parsed_action.confidence,
            target_item_id=parsed_action.target_item_id,
            payload=dict(parsed_action.payload),
            source_refs=source_refs,
            rationale=parsed_action.rationale,
        )

    def _persisted_action(self, action: LLMAction) -> LLMAction:
        getter = getattr(self.llm_action_repository, "get_by_key", None)
        if getter is None:
            return action
        persisted = getter(action.action_key)
        return persisted if persisted is not None else action

    def _source_refs(self, source_message_ids: tuple[int, ...], candidate_messages: tuple[Any, ...]) -> tuple[SourceRef, ...]:
        messages_by_id = {message.telegram_message_id: message for message in candidate_messages}
        refs = []
        for message_id in source_message_ids:
            message = messages_by_id[message_id]
            refs.append(SourceRef(chat_id=message.chat_id, telegram_message_id=message.telegram_message_id))
        return tuple(refs)

    def _item_from_create_action(self, action: LLMAction) -> ExtractedItem:
        item_type = ItemType(str(action.payload["type"]))
        due_at = action.payload.get("due_at")
        return ExtractedItem(
            item_id=f"llm-{action.action_key.split(':', 1)[1]}",
            item_type=item_type,
            title=str(action.payload["title"]),
            description=str(action.payload.get("description", "")),
            confidence=action.confidence,
            sources=action.source_refs,
            status=ItemStatus.OPEN,
            rationale=action.rationale,
            due_at=datetime.fromisoformat(str(due_at)) if due_at else None,
            metadata={str(key): str(value) for key, value in dict(action.payload.get("metadata", {})).items()},
        )

    def _score_message(self, message: Any) -> Any:
        if not self._scorer_accepts_context():
            return self.scorer(message)
        return self.scorer(message, self._scoring_context_for(message))

    def _scorer_accepts_context(self) -> bool:
        try:
            return len(inspect.signature(self.scorer).parameters) > 1
        except (TypeError, ValueError):
            return True

    def _scoring_context_for(self, message: Any) -> Any | None:
        context_provider = getattr(self.message_source, "scoring_context_for", None)
        if context_provider is None:
            return None
        return context_provider(message)

    def _llm_failure_metadata(self, error: BaseException, *, candidate_count: int) -> dict[str, object]:
        metadata: dict[str, object] = {
            "error_type": type(error).__name__,
            "candidate_count": candidate_count,
        }
        safe_metadata = getattr(error, "safe_metadata", {})
        if isinstance(safe_metadata, dict):
            for key in SAFE_LLM_FAILURE_METADATA_KEYS:
                if key in safe_metadata:
                    metadata[key] = safe_metadata[key]
        if isinstance(error, LLMValidationError):
            metadata["validation_error"] = str(error)
        return metadata

    def _record_action_failure(self, error: BaseException, parsed_action: Any) -> None:
        if self.runtime_event_repository is None:
            return
        action_type = getattr(parsed_action, "action_type", "")
        action_type_value = action_type.value if hasattr(action_type, "value") else str(action_type)
        source_message_ids = getattr(parsed_action, "source_message_ids", ())
        self.runtime_event_repository.record_event(
            component="worker",
            severity="warning",
            event_type="llm_action_failure",
            message="LLM action could not be converted",
            metadata={
                "error_type": type(error).__name__,
                "action_type": action_type_value,
                "source_message_count": len(tuple(source_message_ids)),
            },
        )
