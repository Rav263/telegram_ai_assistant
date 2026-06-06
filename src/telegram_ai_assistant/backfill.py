from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import inspect
from typing import Any

from .ingestion.backfill import BackfillService


SAFE_BACKFILL_FAILURE_METADATA_KEYS = (
    "endpoint_scheme",
    "endpoint_host",
    "endpoint_path",
    "http_status",
    "transport_error_type",
    "timeout_seconds",
)


class BackfillStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BackfillJob:
    job_id: str
    account_id: str
    chat_ids: tuple[int, ...]
    start_at: datetime
    end_at: datetime
    status: BackfillStatus = BackfillStatus.PENDING
    cursor_by_chat: dict[int, int] = field(default_factory=dict)

    @classmethod
    def default(
        cls,
        *,
        job_id: str,
        account_id: str,
        chat_ids: tuple[int, ...],
        now: datetime,
        days: int = 30,
    ) -> "BackfillJob":
        return cls.for_date_range(
            job_id=job_id,
            account_id=account_id,
            chat_ids=chat_ids,
            start_at=now - timedelta(days=days),
            end_at=now,
        )

    @classmethod
    def for_date_range(
        cls,
        *,
        job_id: str,
        account_id: str,
        chat_ids: tuple[int, ...],
        start_at: datetime,
        end_at: datetime,
        status: BackfillStatus = BackfillStatus.PENDING,
        cursor_by_chat: dict[int, int] | None = None,
    ) -> "BackfillJob":
        return cls(
            job_id=job_id,
            account_id=account_id,
            chat_ids=tuple(chat_ids),
            start_at=start_at,
            end_at=end_at,
            status=status,
            cursor_by_chat=dict(cursor_by_chat or {}),
        )


@dataclass(frozen=True)
class BackfillRunResult:
    job_id: str
    status: BackfillStatus
    fetched_count: int


@dataclass(frozen=True)
class PersistedBackfillRunResult:
    backfill_jobs: int = 0
    saved_messages: int = 0
    failures: int = 0
    job_id: int | None = None
    status: str = ""


class BackfillRunner:
    def __init__(
        self,
        *,
        job_repository: Any,
        ingestion_client: Any,
        message_repository: Any,
        batch_size: int = 100,
    ):
        self.job_repository = job_repository
        self.ingestion_client = ingestion_client
        self.message_repository = message_repository
        self.batch_size = batch_size

    def run_once(self, job_id: str) -> BackfillRunResult:
        job = self.job_repository.get_job(job_id)
        if job.status == BackfillStatus.CANCELLED:
            return BackfillRunResult(job_id=job_id, status=BackfillStatus.CANCELLED, fetched_count=0)
        if job.status == BackfillStatus.COMPLETED:
            return BackfillRunResult(job_id=job_id, status=BackfillStatus.COMPLETED, fetched_count=0)

        self._call_optional("mark_running", job_id)
        fetched_count = 0

        for chat_id in job.chat_ids:
            if self._is_cancelled(job_id):
                return BackfillRunResult(
                    job_id=job_id,
                    status=BackfillStatus.CANCELLED,
                    fetched_count=fetched_count,
                )

            messages = tuple(
                self.ingestion_client.iter_history(
                    account_id=job.account_id,
                    chat_id=chat_id,
                    start_at=job.start_at,
                    end_at=job.end_at,
                    before_message_id=job.cursor_by_chat.get(chat_id),
                    limit=self.batch_size,
                )
            )
            if not messages:
                continue

            self.message_repository.save_messages(messages)
            fetched_count += len(messages)
            before_message_id = min(message.telegram_message_id for message in messages)
            self.job_repository.update_cursor(job_id, chat_id, before_message_id)

        if fetched_count == 0:
            self._call_optional("mark_completed", job_id)
            return BackfillRunResult(job_id=job_id, status=BackfillStatus.COMPLETED, fetched_count=0)

        return BackfillRunResult(job_id=job_id, status=BackfillStatus.RUNNING, fetched_count=fetched_count)

    def _is_cancelled(self, job_id: str) -> bool:
        checker = getattr(self.job_repository, "is_cancelled", None)
        return bool(checker and checker(job_id))

    def _call_optional(self, method_name: str, *args: Any) -> None:
        method = getattr(self.job_repository, method_name, None)
        if method is not None:
            method(*args)


class PersistedBackfillJobRunner:
    def __init__(
        self,
        *,
        job_repository: Any,
        connection_factory: Any,
        client_factory: Any,
        backfill_service_factory: Any = BackfillService,
        runtime_event_repository: Any | None = None,
        **service_kwargs: Any,
    ):
        self.job_repository = job_repository
        self.connection_factory = connection_factory
        self.client_factory = client_factory
        self.backfill_service_factory = backfill_service_factory
        self.runtime_event_repository = runtime_event_repository
        self.service_kwargs = dict(service_kwargs)

    def run_once(self, *, limit: int) -> PersistedBackfillRunResult:
        return _run_maybe_awaitable(self._run_once(limit=limit, client=None))

    async def run_once_with_client(self, *, limit: int, client: Any) -> PersistedBackfillRunResult:
        return await self._run_once(limit=limit, client=client)

    async def _run_once(self, *, limit: int, client: Any | None) -> PersistedBackfillRunResult:
        job = self.job_repository.claim_next_job()
        if job is None:
            return PersistedBackfillRunResult()
        if job.status == "cancel_requested":
            self.job_repository.mark_cancelled(job.backfill_job_id)
            return PersistedBackfillRunResult(backfill_jobs=1, job_id=job.backfill_job_id, status="cancelled")

        try:
            service_result = await self._run_backfill_service(job, limit=limit, client=client)
        except Exception as exc:
            self.job_repository.mark_failed(
                job.backfill_job_id,
                error_type=type(exc).__name__,
                metadata=_safe_backfill_failure_metadata(exc),
            )
            self._record_failure_event(job, exc)
            return PersistedBackfillRunResult(
                backfill_jobs=1,
                failures=1,
                job_id=job.backfill_job_id,
                status="failed",
            )

        saved_count = int(getattr(service_result, "saved_count", 0) or 0)
        next_before_message_id = getattr(service_result, "next_before_message_id", None)
        if saved_count <= 0:
            self.job_repository.mark_completed(job.backfill_job_id)
            return PersistedBackfillRunResult(
                backfill_jobs=1,
                saved_messages=0,
                job_id=job.backfill_job_id,
                status="completed",
            )

        self.job_repository.record_progress(
            backfill_job_id=job.backfill_job_id,
            saved_count=saved_count,
            next_before_message_id=next_before_message_id,
        )
        if next_before_message_id is None:
            self.job_repository.mark_completed(job.backfill_job_id)
            status = "completed"
        else:
            status = "running"
        return PersistedBackfillRunResult(
            backfill_jobs=1,
            saved_messages=saved_count,
            job_id=job.backfill_job_id,
            status=status,
        )

    async def _run_backfill_service(self, job: Any, *, limit: int, client: Any | None) -> Any:
        service = self.backfill_service_factory(
            account_id=job.account_id,
            chat_id=job.chat_id,
            start_at=job.from_date,
            end_at=job.to_date,
            before_message_id=job.next_before_message_id,
            limit=limit,
            connection_factory=self.connection_factory,
            client_factory=self.client_factory,
            **self.service_kwargs,
        )
        if client is not None:
            return await _await_maybe(service.run_once_with_client(client))
        return await _await_maybe(service.run_once())

    def _record_failure_event(self, job: Any, error: BaseException) -> None:
        if self.runtime_event_repository is None:
            return
        metadata = {
            "job_id": int(job.backfill_job_id),
            "chat_id": int(job.chat_id),
            "error_type": type(error).__name__,
        }
        metadata.update(_safe_backfill_failure_metadata(error))
        self.runtime_event_repository.record_event(
            component="listener",
            severity="warning",
            event_type="backfill_failed",
            message="Backfill job failed",
            metadata=metadata,
        )


class ConnectionScopedBackfillJobRunner:
    def __init__(
        self,
        *,
        connection_factory: Any,
        job_repository_factory: Any,
        runtime_event_repository_factory: Any,
        client_factory: Any,
        backfill_service_factory: Any = BackfillService,
        **service_kwargs: Any,
    ):
        self.connection_factory = connection_factory
        self.job_repository_factory = job_repository_factory
        self.runtime_event_repository_factory = runtime_event_repository_factory
        self.client_factory = client_factory
        self.backfill_service_factory = backfill_service_factory
        self.service_kwargs = dict(service_kwargs)

    async def run_once_with_client(self, *, limit: int, client: Any) -> PersistedBackfillRunResult:
        with self.connection_factory.connection() as connection:
            runner = PersistedBackfillJobRunner(
                job_repository=self.job_repository_factory(connection),
                connection_factory=self.connection_factory,
                client_factory=self.client_factory,
                backfill_service_factory=self.backfill_service_factory,
                runtime_event_repository=self.runtime_event_repository_factory(connection),
                **self.service_kwargs,
            )
            return await runner.run_once_with_client(limit=limit, client=client)


def _run_maybe_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _safe_backfill_failure_metadata(error: BaseException) -> dict[str, object]:
    metadata: dict[str, object] = {}
    safe_metadata = getattr(error, "safe_metadata", {})
    if isinstance(safe_metadata, dict):
        for key in SAFE_BACKFILL_FAILURE_METADATA_KEYS:
            if key in safe_metadata:
                metadata[key] = safe_metadata[key]
    return metadata
