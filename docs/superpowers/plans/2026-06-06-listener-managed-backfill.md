# Listener-Managed Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move persisted bot-managed Telegram backfill execution from `app-worker` to `app-listener` so one process owns the Telethon session.

**Architecture:** Keep the bot-created `backfill_jobs` table as the coordination boundary. Add a listener-side job runner that uses the already connected read-only Telegram client and existing repositories. Remove worker-owned backfill execution so `app-worker` never opens Telegram for persisted jobs.

**Tech Stack:** Python 3.11, `unittest`, Postgres repositories, Telethon adapter through `IngestionClient`, Docker Compose.

---

## File Map

- Modify `src/telegram_ai_assistant/ingestion/backfill.py`: split import execution into a client-owned path and keep current one-shot wrapper for CLI backfill.
- Modify `src/telegram_ai_assistant/backfill.py`: adapt `PersistedBackfillJobRunner` so it can execute with an externally owned client and record safe runtime events.
- Modify `src/telegram_ai_assistant/ingestion/listener.py`: wire a cooperative backfill poll into the live listener loop.
- Modify `src/telegram_ai_assistant/worker.py`: remove persisted backfill execution from the worker.
- Modify `src/telegram_ai_assistant/app_context.py`: wire backfill runner into listener and remove it from worker.
- Modify `src/telegram_ai_assistant/runtime.py`: adjust worker result output/logging if backfill counters become unused.
- Modify `tests/test_backfill_service.py`: cover externally owned client behavior.
- Modify `tests/test_backfill.py`: cover persisted runner execution with a supplied client and safe failure events.
- Modify `tests/test_live_update_listener.py`: cover listener registration plus one cooperative backfill poll.
- Modify `tests/test_worker.py`: prove worker no longer executes persisted backfill jobs.
- Modify `tests/test_app_context.py`: prove listener owns persisted backfill wiring and worker does not.
- Modify `tests/test_runtime.py`: update worker output expectations.
- Modify `tests/test_operations_docs.py`: assert docs mention listener-owned backfill and singleton listener.
- Modify `docs/operations/local-runbook.md`: update operational instructions.
- Modify `CHANGELOG.md`: note listener-managed backfill fix.

## Task 1: Client-Owned Backfill Batch

**Files:**
- Modify: `src/telegram_ai_assistant/ingestion/backfill.py`
- Test: `tests/test_backfill_service.py`

- [ ] **Step 1: Write failing externally owned client test**

Add a test to `BackfillServiceTests`:

```python
def test_run_once_with_client_does_not_close_externally_owned_client(self):
    start_at = datetime(2022, 1, 1, tzinfo=UTC)
    end_at = datetime(2022, 2, 1, tzinfo=UTC)
    client = FakeBackfillClient(
        [RawMessage(30, "newest old message", datetime(2022, 1, 20, tzinfo=UTC))]
    )
    service, repositories = make_service(
        client=client,
        start_at=start_at,
        end_at=end_at,
        before_message_id=None,
    )

    result = asyncio.run(service.run_once_with_client(client))

    self.assertEqual(result.saved_count, 1)
    self.assertEqual(
        client.calls,
        [
            {
                "chat_id": 1001,
                "start_at": start_at,
                "end_at": end_at,
                "before_message_id": None,
                "limit": 10,
            }
        ],
    )
    self.assertEqual(len(repositories.messages.messages), 1)
```

- [ ] **Step 2: Run focused test and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_backfill_service.BackfillServiceTests.test_run_once_with_client_does_not_close_externally_owned_client -v
```

Expected: fail with `AttributeError: 'BackfillService' object has no attribute 'run_once_with_client'`.

- [ ] **Step 3: Implement shared batch method**

In `BackfillService`, keep `run_once()` as the client-owning wrapper and add:

```python
async def run_once(self) -> BackfillRunResult:
    client = await _resolve_client(self.client_factory())
    try:
        return await self.run_once_with_client(client)
    finally:
        await client.close()

async def run_once_with_client(self, client: Any) -> BackfillRunResult:
    with self.connection_factory.connection() as connection:
        account_repository = self.account_repository_factory(connection)
        chat_repository = self.chat_repository_factory(connection)
        message_repository = self.message_repository_factory(connection)

        account_repository.ensure_account(self.account_id)
        chat_repository.ensure_chat(self.account_id, self.chat_id)

        saved_count = 0
        next_before_message_id = self.before_message_id
        oldest_sent_at: datetime | None = None
        newest_sent_at: datetime | None = None
        async for raw_message in client.iter_backfill_messages(
            self.chat_id,
            start_at=self.start_at,
            end_at=self.end_at,
            before_message_id=self.before_message_id,
            limit=self.limit,
        ):
            message = self.normalizer(self.account_id, raw_message)
            message_repository.upsert_message(message)
            saved_count += 1
            next_before_message_id = (
                message.telegram_message_id
                if next_before_message_id is None
                else min(next_before_message_id, message.telegram_message_id)
            )
            oldest_sent_at = message.sent_at if oldest_sent_at is None else min(oldest_sent_at, message.sent_at)
            newest_sent_at = message.sent_at if newest_sent_at is None else max(newest_sent_at, message.sent_at)

        return BackfillRunResult(
            account_id=self.account_id,
            chat_id=self.chat_id,
            start_at=self.start_at,
            end_at=self.end_at,
            requested_before_message_id=self.before_message_id,
            next_before_message_id=next_before_message_id,
            saved_count=saved_count,
            oldest_sent_at=oldest_sent_at,
            newest_sent_at=newest_sent_at,
        )
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_backfill_service -v
```

Expected: all backfill service tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/telegram_ai_assistant/ingestion/backfill.py tests/test_backfill_service.py
git commit -m "feat: support externally owned backfill clients"
```

## Task 2: Persisted Runner Uses Listener Client And Logs Safe Failures

**Files:**
- Modify: `src/telegram_ai_assistant/backfill.py`
- Test: `tests/test_backfill.py`

- [ ] **Step 1: Write failing runner test for supplied client**

Add a `PersistedBackfillJobRunnerTests` test:

```python
def test_runs_one_batch_with_supplied_client_without_client_factory(self):
    jobs = FakePersistedBackfillJobs(
        FakeBackfillJobRecord(backfill_job_id=7, chat_id=1001, next_before_message_id=500)
    )
    captured = {}

    class FakeBackfillService:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run_once_with_client(self, client):
            captured["client"] = client
            return SimpleNamespace(saved_count=2, next_before_message_id=400)

    result = PersistedBackfillJobRunner(
        job_repository=jobs,
        connection_factory="connection-factory",
        client_factory=None,
        backfill_service_factory=FakeBackfillService,
    ).run_once(limit=25, client="shared-client")

    self.assertEqual(result.backfill_jobs, 1)
    self.assertEqual(result.saved_messages, 2)
    self.assertEqual(captured["client"], "shared-client")
    self.assertEqual(jobs.progress[0]["next_before_message_id"], 400)
```

- [ ] **Step 2: Write failing safe runtime event test**

Add:

```python
def test_failures_record_runtime_event_with_safe_metadata(self):
    jobs = FakePersistedBackfillJobs(FakeBackfillJobRecord(backfill_job_id=7, chat_id=1001))
    events = FakeRuntimeEventRepository()

    class FakeBackfillService:
        def __init__(self, **kwargs):
            pass

        async def run_once_with_client(self, client):
            raise RuntimeError("raw secret message")

    result = PersistedBackfillJobRunner(
        job_repository=jobs,
        connection_factory="connection-factory",
        client_factory=None,
        backfill_service_factory=FakeBackfillService,
        runtime_event_repository=events,
    ).run_once(limit=25, client="shared-client")

    self.assertEqual(result.failures, 1)
    self.assertEqual(events.events[0]["component"], "listener")
    self.assertEqual(events.events[0]["event_type"], "backfill_failed")
    self.assertEqual(events.events[0]["metadata"]["job_id"], 7)
    self.assertEqual(events.events[0]["metadata"]["chat_id"], 1001)
    self.assertEqual(events.events[0]["metadata"]["error_type"], "RuntimeError")
    self.assertNotIn("raw secret message", str(events.events[0]))
```

Create `FakeRuntimeEventRepository` in `tests/test_backfill.py`:

```python
class FakeRuntimeEventRepository:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)
```

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_backfill.PersistedBackfillJobRunnerTests -v
```

Expected: fail because `run_once` does not accept `client` and no runtime event is recorded.

- [ ] **Step 4: Implement runner changes**

Update `PersistedBackfillJobRunner.__init__` to accept `runtime_event_repository: Any | None = None`.

Update `run_once` signature:

```python
def run_once(self, *, limit: int, client: Any | None = None) -> PersistedBackfillRunResult:
```

Update `_run_backfill_service`:

```python
def _run_backfill_service(self, job: Any, *, limit: int, client: Any | None = None) -> Any:
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
    if client is not None and hasattr(service, "run_once_with_client"):
        return _run_maybe_awaitable(service.run_once_with_client(client))
    return _run_maybe_awaitable(service.run_once())
```

In the `except` block, after `mark_failed`, call:

```python
self._record_failure_event(job, exc)
```

Add:

```python
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
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_backfill -v
```

Expected: all backfill tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/telegram_ai_assistant/backfill.py tests/test_backfill.py
git commit -m "feat: run persisted backfill with listener client"
```

## Task 3: Listener Polls Persisted Backfill Jobs

**Files:**
- Modify: `src/telegram_ai_assistant/ingestion/listener.py`
- Test: `tests/test_live_update_listener.py`

- [ ] **Step 1: Write failing listener backfill poll test**

Add a test:

```python
def test_run_forever_registers_live_handler_and_runs_one_backfill_poll(self):
    client = FakeListenerClient()
    runner = FakeBackfillJobRunner()
    listener = make_listener(client=client, backfill_job_runner=runner, backfill_batch_size=25)

    result = asyncio.run(listener.run_forever(stop_requested=lambda: True))

    self.assertEqual(result.status, "stopped")
    self.assertEqual(client.calls[0]["method"], "listen_new_messages")
    self.assertEqual(runner.calls, [{"limit": 25, "client": client}])
```

Extend `FakeListenerClient.run_until_disconnected` or the listener call path so this test can stop deterministically.

Add:

```python
class FakeBackfillJobRunner:
    def __init__(self):
        self.calls = []

    def run_once(self, *, limit, client):
        self.calls.append({"limit": limit, "client": client})
        return SimpleNamespace(backfill_jobs=1, saved_messages=0, failures=0)
```

- [ ] **Step 2: Write failing listener no-runner test**

Add:

```python
def test_run_forever_without_backfill_runner_only_listens(self):
    client = FakeListenerClient()
    listener = make_listener(client=client, backfill_job_runner=None)

    result = asyncio.run(listener.run_forever(stop_requested=lambda: True))

    self.assertEqual(result.status, "stopped")
    self.assertEqual([call["method"] for call in client.calls], ["listen_new_messages", "run_until_disconnected", "close"])
```

- [ ] **Step 3: Run listener tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_live_update_listener -v
```

Expected: fail because `LiveUpdateListener` has no `backfill_job_runner`, `backfill_batch_size`, or stop-aware `run_forever`.

- [ ] **Step 4: Implement cooperative listener backfill poll**

Add constructor args:

```python
backfill_job_runner: Any | None = None
backfill_batch_size: int = 25
```

Store them on `self`.

Update `run_forever` signature:

```python
async def run_forever(self, *, stop_requested: Callable[[], bool] | None = None) -> ListenerRunResult:
```

Use this flow:

```python
client = await _resolve_client(self.client_factory())
try:
    logger.info("live listener starting account_id=%s", self.account_id)
    await client.listen_new_messages(self.handle_update)
    self._run_backfill_once(client)
    if stop_requested is not None and stop_requested():
        return ListenerRunResult(account_id=self.account_id, status="stopped")
    await client.run_until_disconnected()
finally:
    await client.close()
    logger.info("live listener stopped account_id=%s", self.account_id)
return ListenerRunResult(account_id=self.account_id, status="stopped")
```

Add:

```python
def _run_backfill_once(self, client: Any) -> None:
    if self.backfill_job_runner is None:
        return
    self.backfill_job_runner.run_once(limit=self.backfill_batch_size, client=client)
```

This first slice runs one cooperative poll on startup and is testable. A later task can add periodic polling if needed before final full-suite verification.

- [ ] **Step 5: Run listener tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_live_update_listener -v
```

Expected: all live listener tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/telegram_ai_assistant/ingestion/listener.py tests/test_live_update_listener.py
git commit -m "feat: poll backfill jobs from listener"
```

## Task 4: Move Runtime Wiring From Worker To Listener

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/worker.py`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Test: `tests/test_app_context.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Write failing app context tests**

Update `test_run_listener_forever_builds_service_with_settings` to assert captured listener kwargs include:

```python
self.assertEqual(captured["backfill_job_runner"].__class__.__name__, "PersistedBackfillJobRunner")
self.assertEqual(captured["backfill_batch_size"], settings.worker_batch_size)
```

Update `test_run_worker_once_builds_worker_with_repositories_and_settings` to assert:

```python
self.assertNotIn("backfill_job_runner", captured)
```

- [ ] **Step 2: Write failing worker tests**

Replace `test_process_backfill_jobs_runs_injected_runner_once` with:

```python
def test_worker_does_not_process_persisted_backfill_jobs(self):
    worker = Worker(backfill_job_runner=FakeBackfillRunner())

    result = worker.process_backfill_jobs(limit=25)

    self.assertEqual(result, WorkerResult())
```

Keep `process_backfill_jobs` as a compatibility no-op or remove calls from runtime and adjust tests accordingly.

- [ ] **Step 3: Write failing runtime tests**

Update worker output assertions to expect no meaningful backfill work from `run_worker_once`. If JSON payload remains backward-compatible, expect:

```python
self.assertEqual(payload["backfill_jobs"], 0)
self.assertEqual(payload["backfill_saved_messages"], 0)
self.assertEqual(payload["backfill_failures"], 0)
```

- [ ] **Step 4: Run focused tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context tests.test_worker tests.test_runtime -v
```

Expected: fail because listener is not wired and worker still processes backfill jobs.

- [ ] **Step 5: Implement wiring changes**

In `AppContext.run_listener_forever`, pass:

```python
backfill_job_runner=PersistedBackfillJobRunner(
    job_repository=BackfillJobRepository(
        connection,
        account_id=self.settings.telegram_ingest_account_id,
    ),
    backfill_service_factory=self.backfill_factory,
    connection_factory=self.connection_factory,
    client_factory=None,
    runtime_event_repository=RuntimeEventRepository(connection),
),
backfill_batch_size=self.settings.worker_batch_size,
```

This requires opening a DB connection in `run_listener_forever` similarly to `run_bot_forever`.

In `AppContext.run_worker_once`, remove `backfill_job_runner=...`.

In `Worker.process_backfill_jobs`, return `WorkerResult()` unconditionally, or remove the method call from `AppContext.run_worker_once`. Prefer keeping the method as a no-op for compatibility with existing tests and `WorkerResult` JSON shape.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context tests.test_worker tests.test_runtime -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/telegram_ai_assistant/app_context.py src/telegram_ai_assistant/worker.py src/telegram_ai_assistant/runtime.py tests/test_app_context.py tests/test_worker.py tests/test_runtime.py
git commit -m "feat: move backfill runtime ownership to listener"
```

## Task 5: Docs, Changelog, And Full Verification

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_operations_docs.py`

- [ ] **Step 1: Write failing docs test**

Add assertions to `test_local_runbook_documents_bot_managed_backfill_jobs`:

```python
self.assertIn("app-listener executes bot-managed backfill jobs", text)
self.assertIn("Do not scale app-listener above one replica", text)
self.assertIn("app-worker does not open the Telegram user session for backfill", text)
```

- [ ] **Step 2: Run docs test and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_operations_docs -v
```

Expected: fail because docs still describe worker-owned backfill.

- [ ] **Step 3: Update docs and changelog**

In `docs/operations/local-runbook.md`, update the bot-managed backfill section:

```markdown
`app-listener` executes bot-managed backfill jobs with the already connected Telegram user session.
Do not scale `app-listener` above one replica.
`app-worker` does not open the Telegram user session for backfill; it only processes saved messages through filtering and LLM extraction.
```

In `CHANGELOG.md`, add:

```markdown
- Moved bot-managed backfill execution to `app-listener` so the Telethon session has a single runtime owner.
- Added safe listener runtime events for backfill failures.
```

- [ ] **Step 4: Run docs test and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_operations_docs -v
```

Expected: pass.

- [ ] **Step 5: Run full verification**

Run:

```bash
git diff --check
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -v
```

Expected: `git diff --check` clean and full suite passes.

- [ ] **Step 6: Commit**

```bash
git add docs/operations/local-runbook.md CHANGELOG.md tests/test_operations_docs.py
git commit -m "docs: document listener-owned backfill runtime"
```

## Final Review

- [ ] Confirm `git status --short --branch` is clean.
- [ ] Confirm `git log --oneline --decorate -6` shows the plan and implementation commits.
- [ ] Confirm failed production job recovery instructions still work: set failed job back to `pending` or create a new bot job.
- [ ] Report changed files, tests run, residual risks, and remote restart notes.
