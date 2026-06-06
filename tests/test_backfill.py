from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
import asyncio

from telegram_ai_assistant.backfill import BackfillJob, BackfillRunner, BackfillStatus, PersistedBackfillJobRunner
from telegram_ai_assistant.domain import BackfillJobRecord


class FakeBackfillJobRepository:
    def __init__(self, job: BackfillJob):
        self.job = job
        self.cursor_updates = []
        self.statuses = []

    def get_job(self, job_id: str) -> BackfillJob:
        self.requested_job_id = job_id
        return self.job

    def mark_running(self, job_id: str) -> None:
        self.statuses.append((job_id, BackfillStatus.RUNNING))

    def update_cursor(self, job_id: str, chat_id: int, before_message_id: int) -> None:
        self.cursor_updates.append((job_id, chat_id, before_message_id))

    def mark_completed(self, job_id: str) -> None:
        self.statuses.append((job_id, BackfillStatus.COMPLETED))


class FakeHistoryClient:
    def __init__(self, batches):
        self.batches = batches
        self.calls = []

    def iter_history(
        self,
        *,
        account_id: str,
        chat_id: int,
        start_at: datetime,
        end_at: datetime,
        before_message_id: int | None,
        limit: int,
    ):
        self.calls.append(
            {
                "account_id": account_id,
                "chat_id": chat_id,
                "start_at": start_at,
                "end_at": end_at,
                "before_message_id": before_message_id,
                "limit": limit,
            }
        )
        return list(self.batches.get(chat_id, ()))


class FakeMessageRepository:
    def __init__(self):
        self.saved_batches = []

    def save_messages(self, messages) -> None:
        self.saved_batches.append(tuple(messages))


def make_persisted_job(
    *,
    status: str = "running",
    next_before_message_id: int | None = 450,
) -> BackfillJobRecord:
    now = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
    return BackfillJobRecord(
        backfill_job_id=7,
        account_id="main",
        chat_id=1001,
        chat_title="Alice",
        status=status,
        from_date=datetime(2026, 5, 7, 9, 0, tzinfo=UTC),
        to_date=now,
        next_before_message_id=next_before_message_id,
        saved_count=10,
        last_error_type="",
        last_error_metadata={},
        created_at=now,
        started_at=now,
        finished_at=None,
        updated_at=now,
    )


class FakePersistedBackfillJobRepository:
    def __init__(self, job=None):
        self.job = job
        self.progress = []
        self.completed = []
        self.cancelled = []
        self.failed = []
        self.claims = 0

    def claim_next_job(self):
        self.claims += 1
        return self.job

    def record_progress(self, *, backfill_job_id, saved_count, next_before_message_id):
        self.progress.append(
            {
                "backfill_job_id": backfill_job_id,
                "saved_count": saved_count,
                "next_before_message_id": next_before_message_id,
            }
        )

    def mark_completed(self, backfill_job_id):
        self.completed.append(backfill_job_id)

    def mark_cancelled(self, backfill_job_id):
        self.cancelled.append(backfill_job_id)

    def mark_failed(self, backfill_job_id, *, error_type, metadata):
        self.failed.append(
            {
                "backfill_job_id": backfill_job_id,
                "error_type": error_type,
                "metadata": metadata,
            }
        )


class FakeBackfillService:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeBackfillService.instances.append(self)

    async def run_once(self):
        return self.kwargs["result"]

    async def run_once_with_client(self, client):
        self.kwargs["client"] = client
        return self.kwargs["result"]


class FailingBackfillService:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FailingBackfillService.instances.append(self)

    async def run_once(self):
        error = RuntimeError("raw private Telegram text")
        error.safe_metadata = {"endpoint_host": "localhost", "raw_message": "secret"}
        raise error

    async def run_once_with_client(self, client):
        return await self.run_once()


class FakeRuntimeEventRepository:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)


class PersistedBackfillJobRunnerTests(unittest.TestCase):
    def setUp(self):
        FakeBackfillService.instances = []
        FailingBackfillService.instances = []

    def test_returns_idle_when_no_job_is_claimed(self):
        jobs = FakePersistedBackfillJobRepository(job=None)

        result = PersistedBackfillJobRunner(
            job_repository=jobs,
            backfill_service_factory=FakeBackfillService,
            connection_factory="connection-factory",
            client_factory="client-factory",
        ).run_once(limit=100)

        self.assertEqual(result.backfill_jobs, 0)
        self.assertEqual(result.saved_messages, 0)
        self.assertEqual(FakeBackfillService.instances, [])

    def test_cancel_requested_job_is_cancelled_without_opening_telegram(self):
        jobs = FakePersistedBackfillJobRepository(job=make_persisted_job(status="cancel_requested"))

        result = PersistedBackfillJobRunner(
            job_repository=jobs,
            backfill_service_factory=FakeBackfillService,
            connection_factory="connection-factory",
            client_factory="client-factory",
        ).run_once(limit=100)

        self.assertEqual(result.backfill_jobs, 1)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(jobs.cancelled, [7])
        self.assertEqual(FakeBackfillService.instances, [])

    def test_runs_one_batch_and_records_progress_cursor(self):
        job = make_persisted_job(next_before_message_id=450)
        service_result = SimpleNamespace(saved_count=12, next_before_message_id=400)
        jobs = FakePersistedBackfillJobRepository(job=job)

        result = PersistedBackfillJobRunner(
            job_repository=jobs,
            backfill_service_factory=FakeBackfillService,
            connection_factory="connection-factory",
            client_factory="client-factory",
            result=service_result,
        ).run_once(limit=100)

        self.assertEqual(result.backfill_jobs, 1)
        self.assertEqual(result.saved_messages, 12)
        self.assertEqual(result.status, "running")
        self.assertEqual(jobs.progress, [{"backfill_job_id": 7, "saved_count": 12, "next_before_message_id": 400}])
        self.assertEqual(jobs.completed, [])
        self.assertEqual(FakeBackfillService.instances[0].kwargs["chat_id"], 1001)
        self.assertEqual(FakeBackfillService.instances[0].kwargs["before_message_id"], 450)
        self.assertEqual(FakeBackfillService.instances[0].kwargs["limit"], 100)

    def test_runs_one_batch_with_supplied_client_without_client_factory(self):
        job = make_persisted_job(next_before_message_id=450)
        service_result = SimpleNamespace(saved_count=2, next_before_message_id=400)
        jobs = FakePersistedBackfillJobRepository(job=job)

        result = asyncio.run(
            PersistedBackfillJobRunner(
                job_repository=jobs,
                backfill_service_factory=FakeBackfillService,
                connection_factory="connection-factory",
                client_factory=None,
                result=service_result,
            ).run_once_with_client(limit=25, client="shared-client")
        )

        self.assertEqual(result.backfill_jobs, 1)
        self.assertEqual(result.saved_messages, 2)
        self.assertEqual(result.status, "running")
        self.assertEqual(FakeBackfillService.instances[0].kwargs["client"], "shared-client")
        self.assertEqual(jobs.progress, [{"backfill_job_id": 7, "saved_count": 2, "next_before_message_id": 400}])

    def test_empty_batch_marks_job_completed(self):
        service_result = SimpleNamespace(saved_count=0, next_before_message_id=450)
        jobs = FakePersistedBackfillJobRepository(job=make_persisted_job(next_before_message_id=450))

        result = PersistedBackfillJobRunner(
            job_repository=jobs,
            backfill_service_factory=FakeBackfillService,
            connection_factory="connection-factory",
            client_factory="client-factory",
            result=service_result,
        ).run_once(limit=100)

        self.assertEqual(result.status, "completed")
        self.assertEqual(jobs.completed, [7])
        self.assertEqual(jobs.progress, [])

    def test_failures_are_marked_with_sanitized_metadata(self):
        jobs = FakePersistedBackfillJobRepository(job=make_persisted_job())

        result = PersistedBackfillJobRunner(
            job_repository=jobs,
            backfill_service_factory=FailingBackfillService,
            connection_factory="connection-factory",
            client_factory="client-factory",
        ).run_once(limit=100)

        self.assertEqual(result.failures, 1)
        self.assertEqual(result.status, "failed")
        self.assertEqual(jobs.failed[0]["error_type"], "RuntimeError")
        self.assertEqual(jobs.failed[0]["metadata"], {"endpoint_host": "localhost"})

    def test_failures_record_runtime_event_with_safe_metadata(self):
        jobs = FakePersistedBackfillJobRepository(job=make_persisted_job())
        events = FakeRuntimeEventRepository()

        result = asyncio.run(
            PersistedBackfillJobRunner(
                job_repository=jobs,
                backfill_service_factory=FailingBackfillService,
                connection_factory="connection-factory",
                client_factory=None,
                runtime_event_repository=events,
            ).run_once_with_client(limit=25, client="shared-client")
        )

        self.assertEqual(result.failures, 1)
        self.assertEqual(result.status, "failed")
        self.assertEqual(events.events[0]["component"], "listener")
        self.assertEqual(events.events[0]["severity"], "warning")
        self.assertEqual(events.events[0]["event_type"], "backfill_failed")
        self.assertEqual(events.events[0]["metadata"]["job_id"], 7)
        self.assertEqual(events.events[0]["metadata"]["chat_id"], 1001)
        self.assertEqual(events.events[0]["metadata"]["error_type"], "RuntimeError")
        self.assertEqual(events.events[0]["metadata"]["endpoint_host"], "localhost")
        self.assertNotIn("raw private Telegram text", str(events.events[0]))


class BackfillJobTests(unittest.TestCase):
    def test_default_job_covers_last_thirty_days(self):
        now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

        job = BackfillJob.default(
            job_id="job-1",
            account_id="main",
            chat_ids=(100, 200),
            now=now,
        )

        self.assertEqual(job.start_at, now - timedelta(days=30))
        self.assertEqual(job.end_at, now)
        self.assertEqual(job.status, BackfillStatus.PENDING)
        self.assertEqual(job.chat_ids, (100, 200))

    def test_job_can_request_older_history_by_date_range(self):
        start_at = datetime(2025, 1, 1, tzinfo=UTC)
        end_at = datetime(2025, 2, 1, tzinfo=UTC)

        job = BackfillJob.for_date_range(
            job_id="job-old",
            account_id="main",
            chat_ids=(300,),
            start_at=start_at,
            end_at=end_at,
        )

        self.assertEqual(job.start_at, start_at)
        self.assertEqual(job.end_at, end_at)

    def test_runner_updates_progress_cursor_after_each_batch(self):
        start_at = datetime(2026, 5, 1, tzinfo=UTC)
        end_at = datetime(2026, 6, 1, tzinfo=UTC)
        job = BackfillJob.for_date_range(
            job_id="job-1",
            account_id="main",
            chat_ids=(100,),
            start_at=start_at,
            end_at=end_at,
        )
        history = FakeHistoryClient(
            {
                100: (
                    SimpleNamespace(telegram_message_id=30),
                    SimpleNamespace(telegram_message_id=25),
                )
            }
        )
        messages = FakeMessageRepository()
        jobs = FakeBackfillJobRepository(job)

        result = BackfillRunner(
            job_repository=jobs,
            ingestion_client=history,
            message_repository=messages,
            batch_size=2,
        ).run_once("job-1")

        self.assertEqual(result.fetched_count, 2)
        self.assertEqual(jobs.cursor_updates, [("job-1", 100, 25)])
        self.assertEqual(len(messages.saved_batches), 1)
        self.assertEqual(history.calls[0]["limit"], 2)

    def test_cancelled_job_stops_before_fetching_more_history(self):
        job = BackfillJob.for_date_range(
            job_id="job-1",
            account_id="main",
            chat_ids=(100,),
            start_at=datetime(2026, 5, 1, tzinfo=UTC),
            end_at=datetime(2026, 6, 1, tzinfo=UTC),
            status=BackfillStatus.CANCELLED,
        )
        history = FakeHistoryClient({100: (SimpleNamespace(telegram_message_id=1),)})

        result = BackfillRunner(
            job_repository=FakeBackfillJobRepository(job),
            ingestion_client=history,
            message_repository=FakeMessageRepository(),
        ).run_once("job-1")

        self.assertEqual(result.status, BackfillStatus.CANCELLED)
        self.assertEqual(result.fetched_count, 0)
        self.assertEqual(history.calls, [])


if __name__ == "__main__":
    unittest.main()
