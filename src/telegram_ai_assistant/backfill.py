from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


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
