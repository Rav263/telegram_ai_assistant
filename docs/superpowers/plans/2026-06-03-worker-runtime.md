# Worker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn stored Telegram messages into candidates, extracted items, review entries, and safe runtime logs through a real worker runtime.

**Architecture:** Keep `Worker` as the domain pipeline and add production adapters around it: worker settings, `run worker --once`, daemon loop, SQL repositories, runtime events, `/logs`, and Docker `app-worker`. All persistence remains idempotent, stdout stays machine-readable JSON, logs/events are sanitized, and TDD is required for every behavior change.

**Tech Stack:** Python 3.11, `unittest`, Postgres SQL through `psycopg`, LM Studio OpenAI-compatible endpoint, Docker Compose.

---

### Task 1: Worker Settings And CLI Shape

**Files:**
- Modify: `src/telegram_ai_assistant/config.py`
- Modify: `src/telegram_ai_assistant/cli.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing config tests**

Add assertions in `tests/test_config.py`:

```python
self.assertEqual(settings.worker_batch_size, 25)
self.assertEqual(settings.worker_poll_interval_seconds, 10)
self.assertEqual(settings.worker_item_auto_apply_threshold, 0.8)
self.assertEqual(settings.worker_status_auto_apply_threshold, 0.8)
```

Add overrides in the optional settings test:

```python
"WORKER_BATCH_SIZE": "50",
"WORKER_POLL_INTERVAL_SECONDS": "3",
"WORKER_ITEM_AUTO_APPLY_THRESHOLD": "0.9",
"WORKER_STATUS_AUTO_APPLY_THRESHOLD": "0.7",
```

Add invalid tests for zero batch size, zero poll interval, non-float threshold, and threshold greater than `1`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v
```

Expected: fails because `Settings` has no worker settings.

- [ ] **Step 3: Implement settings**

Add fields to `Settings`:

```python
worker_batch_size: int = 25
worker_poll_interval_seconds: int = 10
worker_item_auto_apply_threshold: float = 0.8
worker_status_auto_apply_threshold: float = 0.8
```

Parse env names:

```python
WORKER_BATCH_SIZE
WORKER_POLL_INTERVAL_SECONDS
WORKER_ITEM_AUTO_APPLY_THRESHOLD
WORKER_STATUS_AUTO_APPLY_THRESHOLD
```

Add `_optional_probability_float()` that accepts `0.0 <= value <= 1.0`.

- [ ] **Step 4: Write failing CLI tests**

Add tests in `tests/test_cli.py`:

```python
args = build_parser().parse_args(["run", "worker", "--once"])
self.assertEqual(args.command, "run")
self.assertEqual(args.process, "worker")
self.assertTrue(args.once)

args = build_parser().parse_args(["run", "worker"])
self.assertFalse(args.once)

with self.assertRaises(SystemExit):
    build_parser().parse_args(["run", "listener", "--once"])
```

- [ ] **Step 5: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_cli -v
```

Expected: fails because `--once` is unsupported.

- [ ] **Step 6: Implement CLI shape**

Change `run` parser to process-specific subparsers while preserving `args.process`. Add `--once` only to worker.

Update `main()` so:

```python
return run_process(args.process, settings, runners=runners, once=getattr(args, "once", False))
```

Update `run_process()` later in Task 5 to accept runner kwargs. Until then, focused CLI parsing tests should pass.

- [ ] **Step 7: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config tests.test_cli -v
git add src/telegram_ai_assistant/config.py src/telegram_ai_assistant/cli.py tests/test_config.py tests/test_cli.py
git commit -m "feat: add worker runtime settings"
```

### Task 2: Schema Additions

**Files:**
- Modify: `src/telegram_ai_assistant/db/schema.sql`
- Modify: `tests/test_db_schema.py`

- [ ] **Step 1: Write failing schema tests**

Add tests requiring:

```python
"create table if not exists message_processing_state"
"primary key (account_id, chat_id, telegram_message_id, stage)"
"create table if not exists runtime_events"
"alter table review_queue add column if not exists review_type"
"alter table review_queue add column if not exists payload"
"alter table review_queue alter column item_id drop not null"
"idx_runtime_events_severity_created_at"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema -v
```

Expected: fails because the schema does not define the new tables/ALTERs.

- [ ] **Step 3: Implement idempotent schema**

Add `message_processing_state` with composite FK to `messages(account_id, chat_id, telegram_message_id) ON DELETE CASCADE`.

Make fresh `review_queue.item_id` nullable and add `review_type`/`payload` columns. Add compatible ALTER statements for existing DBs.

Add `runtime_events` and index:

```sql
CREATE INDEX IF NOT EXISTS idx_runtime_events_severity_created_at
    ON runtime_events(severity, created_at DESC, runtime_event_id DESC);
```

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema -v
git add src/telegram_ai_assistant/db/schema.sql tests/test_db_schema.py
git commit -m "feat: add worker runtime schema"
```

### Task 3: Repository Adapters

**Files:**
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Modify: `src/telegram_ai_assistant/domain.py`
- Modify: `tests/test_repositories.py`

- [ ] **Step 1: Write failing repository tests**

Add tests for:

- `MessageProcessingRepository.pending_messages(limit)` selecting messages without processed `candidate_filter`.
- `mark_candidate_filter_processed(messages)` upserting processing state.
- `mark_candidate_filter_failed(message, error_type)` upserting failed state with sanitized error type.
- `CandidateRepository.pending_candidate_messages(limit)` joining queued candidates to `messages`.
- `CandidateRepository.mark_processed(messages)` updating queued rows to processed.
- `ItemRepository(account_id).save_item(item)` upserting `extracted_items` with JSON source refs and metadata.
- `ItemRepository(account_id).apply_status_change(change)` updating item status and inserting `item_status_events`.
- `ReviewRepository(account_id).enqueue_item(item)` saving item as `candidate` and queueing `review_type='item'`.
- `ReviewRepository.enqueue_status_change(change)` inserting nullable `item_id` and JSON payload.
- `RuntimeEventRepository.record_event(...)` and `latest_events(...)`.
- `LLMRunRepository.record_failure(error)` storing `type(error).__name__`, not `str(error)`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_repositories -v
```

Expected: fails on missing repository classes/methods.

- [ ] **Step 3: Implement repository support**

Add `RuntimeEvent` dataclass to `domain.py` if useful for `latest_events()`.

In `repositories.py`, add:

```python
def _fetchall(connection, sql, params=None): ...
def _message_from_row(row): ...
```

Keep SQL parameterized. Never put message text, prompts, secrets, or raw exception strings into `runtime_events` or `llm_runs`.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_repositories -v
git add src/telegram_ai_assistant/db/repositories.py src/telegram_ai_assistant/domain.py tests/test_repositories.py
git commit -m "feat: add worker persistence repositories"
```

### Task 4: Worker Domain Pipeline Updates

**Files:**
- Modify: `src/telegram_ai_assistant/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing worker tests**

Add tests for:

- zero-score messages still call `mark_candidate_filter_processed`;
- positive-score messages enqueue candidates and mark processed;
- a scorer exception calls `mark_candidate_filter_failed` and continues with the next message;
- LLM failure records failure but does not mark candidates processed;
- result counts include failures.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_worker -v
```

Expected: fails because `Worker.process_messages()` does not mark processing state or catch per-message scoring failures.

- [ ] **Step 3: Implement minimal Worker changes**

Add optional `scorer` dependency defaulting to `score_message`.

After each successful score, call optional:

```python
self._call_optional(self.message_source, "mark_candidate_filter_processed", [message])
```

On exception, call optional:

```python
self._call_optional(self.message_source, "mark_candidate_filter_failed", message, type(exc).__name__)
```

Do not include `str(exc)` in results or logs.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_worker -v
git add src/telegram_ai_assistant/worker.py tests/test_worker.py
git commit -m "feat: track worker message processing"
```

### Task 5: Worker Service, AppContext, Runtime, And Loop

**Files:**
- Create: `src/telegram_ai_assistant/worker_runtime.py`
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `tests/test_app_context.py`
- Modify: `tests/test_runtime.py`

- [ ] **Step 1: Write failing AppContext tests**

Add test that `AppContext.run_worker_once()` constructs a worker service with:

- `batch_size=settings.worker_batch_size`;
- thresholds from settings;
- `LMStudioClient(base_url=settings.lm_studio_base_url)`;
- repositories bound to a DB connection.

- [ ] **Step 2: Write failing runtime tests**

Add tests:

```python
run_worker(settings, once=True, context_factory=...)
```

prints JSON payload with all `WorkerResult` fields and returns `0`.

Daemon test injects `sleep` and `stop_after_cycle` so no real sleep occurs.

Failure test raises `RuntimeError("secret text")` and asserts stdout/logs include only `RuntimeError`, not `secret text`.

- [ ] **Step 3: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime -v
```

Expected: fails because `run_worker_once()` and worker runtime kwargs do not exist.

- [ ] **Step 4: Implement WorkerCycleService**

`WorkerCycleService.run_once()` opens a DB connection, builds:

```python
MessageProcessingRepository
CandidateRepository
ItemRepository(account_id)
ReviewRepository(account_id)
LLMRunRepository
RuntimeEventRepository
ExtractionService(llm_client=LMStudioClient(...))
Worker(...)
```

It calls `process_messages(limit=batch_size)` and `process_candidates(limit=batch_size)`, combines counts, and records a `runtime_events` warning/error when failures are non-zero.

- [ ] **Step 5: Implement runtime `run_worker`**

Change runner type to accept kwargs:

```python
Runner = Callable[..., int]
```

`run_process(..., **runner_kwargs)` passes kwargs only to selected runner.

`run_worker(settings, once=False, context_factory=..., sleep=time.sleep, stop_after_cycle=None)`:

- if `once`, run one cycle and print JSON;
- otherwise loop until interrupted or `stop_after_cycle(result)` is true;
- log counts at INFO;
- sanitize unexpected failures.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime -v
git add src/telegram_ai_assistant/worker_runtime.py src/telegram_ai_assistant/app_context.py src/telegram_ai_assistant/runtime.py tests/test_app_context.py tests/test_runtime.py
git commit -m "feat: add worker runtime loop"
```

### Task 6: Bot `/logs`

**Files:**
- Modify: `src/telegram_ai_assistant/bot_router.py`
- Create: `src/telegram_ai_assistant/bot_services.py`
- Modify: `tests/test_bot_router.py`
- Create: `tests/test_bot_services.py`

- [ ] **Step 1: Write failing bot router test**

Add `/logs` to `command_to_call` in `tests/test_bot_router.py` and add `FakeBotServices.logs()`.

- [ ] **Step 2: Write failing bot service tests**

Create `BotServices.logs()` test using fake `RuntimeEventRepository.latest_events()`.

Assert output includes component/event/error type/counts but excludes:

```python
"secret message text"
"bot-token"
"api_hash"
"Traceback"
```

- [ ] **Step 3: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_bot_router tests.test_bot_services -v
```

Expected: fails because `/logs` and `BotServices` do not exist.

- [ ] **Step 4: Implement `/logs`**

Add:

```python
COMMANDS["/logs"] = "logs"
```

Add `BotServices.logs()` that formats latest 10 warning/error events. Keep formatting compact and safe.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_bot_router tests.test_bot_services -v
git add src/telegram_ai_assistant/bot_router.py src/telegram_ai_assistant/bot_services.py tests/test_bot_router.py tests/test_bot_services.py
git commit -m "feat: add bot runtime logs command"
```

### Task 7: Docker, Docs, And Changelog

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_docker_packaging.py`
- Modify: `tests/test_operations_docs.py`

- [ ] **Step 1: Write failing docs/Docker tests**

Update tests to require:

- `app-worker:`;
- `telegram-ai-assistant run worker`;
- `WORKER_BATCH_SIZE`;
- `WORKER_POLL_INTERVAL_SECONDS`;
- `WORKER_ITEM_AUTO_APPLY_THRESHOLD`;
- `WORKER_STATUS_AUTO_APPLY_THRESHOLD`;
- `/logs`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_docker_packaging tests.test_operations_docs -v
```

Expected: fails because docs/compose lack worker service and settings.

- [ ] **Step 3: Implement docs/Docker**

Add `app-worker` service mirroring `app-listener` with:

```yaml
command: telegram-ai-assistant run worker
```

Add worker env examples and `/logs` usage to the runbook. Add changelog entry.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_docker_packaging tests.test_operations_docs -v
git add docker-compose.yml docs/operations/local-runbook.md CHANGELOG.md tests/test_docker_packaging.py tests/test_operations_docs.py
git commit -m "docs: document worker runtime"
```

### Task 8: Final Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run full test suite**

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI smoke checks**

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli version
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli --log-level debug health --offline
```

Expected: both exit `0`.

- [ ] **Step 3: Validate Docker Compose and whitespace**

```bash
docker compose config --quiet
git diff --check
git status --short --branch
```

Expected: compose and diff check exit `0`; status has only expected untracked generated files.
