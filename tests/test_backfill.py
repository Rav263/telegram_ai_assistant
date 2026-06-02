from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from telegram_ai_assistant.backfill import BackfillJob, BackfillRunner, BackfillStatus


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
