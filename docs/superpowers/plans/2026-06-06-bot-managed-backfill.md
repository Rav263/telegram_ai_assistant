# Bot-Managed Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build bot-managed persisted Telegram backfill jobs with chat selection, period buttons, worker execution, safe status reporting, and Docker-compatible runtime behavior.

**Architecture:** The bot creates and manages `backfill_jobs` rows only; it never opens the Telegram user session. The existing `app-worker` process claims one persisted backfill job per cycle and executes one bounded `BackfillService` batch through the read-only Telegram adapter. Postgres is the coordination boundary between bot and worker.

**Tech Stack:** Python 3, `unittest`, Postgres SQL schema, repository classes in `src/telegram_ai_assistant/db/repositories.py`, Telegram Bot API inline keyboards, existing `BackfillService`, Docker Compose runtime.

---

## File Map

- Modify `src/telegram_ai_assistant/domain.py`: add display/job dataclasses for chat choices and detailed backfill jobs.
- Modify `src/telegram_ai_assistant/backfill.py`: extend `BackfillStatus` and add a persisted job runner that wraps `BackfillService`.
- Modify `src/telegram_ai_assistant/db/schema.sql`: extend `backfill_jobs` for chat id/title, cursor, cumulative counts, sanitized errors, and update timestamp.
- Modify `src/telegram_ai_assistant/db/repositories.py`: add chat pagination and mutable backfill job repository operations.
- Modify `src/telegram_ai_assistant/bot_services.py`: replace MVP `/backfill` callbacks with period picker, chat pages, confirmation, job creation, status, and cancel flows.
- Modify `src/telegram_ai_assistant/bot_router.py`: allow backfill callbacks to return `BotResponse` and send a new bot message with markup.
- Modify `src/telegram_ai_assistant/worker.py`: add optional backfill job runner execution and result counters.
- Modify `src/telegram_ai_assistant/app_context.py`: wire repositories and runner into bot and worker.
- Modify `src/telegram_ai_assistant/runtime.py`: include backfill job counters in `run worker --once` JSON output.
- Modify tests in `tests/test_db_schema.py`, `tests/test_repositories.py`, `tests/test_bot_services.py`, `tests/test_bot_router.py`, `tests/test_worker.py`, `tests/test_app_context.py`, `tests/test_runtime.py`, and `tests/test_operations_docs.py`.
- Modify `docs/operations/local-runbook.md` and `CHANGELOG.md`.

## Task 1: Persisted Backfill Schema And Repository

**Files:**
- Modify: `src/telegram_ai_assistant/domain.py`
- Modify: `src/telegram_ai_assistant/db/schema.sql`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_db_schema.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing schema tests**

Add tests asserting `backfill_jobs` contains `chat_id`, `chat_title`, `next_before_message_id`, `saved_count`, `last_error_type`, `last_error_metadata`, and `updated_at`, plus indexes for account/status and account/chat.

- [ ] **Step 2: Run schema tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_db_schema -v
```

Expected: fail because the new columns and indexes are not present.

- [ ] **Step 3: Write failing repository tests**

Add tests for:

- `ChatQueryRepository.list_backfill_chats(page=0, page_size=6)` returns six eligible chats and filters denied chat ids and non-allowlisted broadcast channels.
- `BackfillJobRepository.create_job(...)` inserts a pending job and returns a detailed job object.
- `BackfillJobRepository.latest_jobs(limit=3)` includes chat title, chat id, saved count, and sanitized error type.
- `BackfillJobRepository.request_cancel(job_id)` updates `pending`/`running` jobs to `cancel_requested`.
- `BackfillJobRepository.claim_next_job()` claims `pending`, `running`, or `cancel_requested` jobs.
- `BackfillJobRepository.record_progress(...)`, `mark_completed(...)`, `mark_cancelled(...)`, and `mark_failed(...)` update only safe fields.

- [ ] **Step 4: Run repository tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories -v
```

Expected: fail because the new repositories, dataclasses, and SQL are missing.

- [ ] **Step 5: Implement minimal schema, domain dataclasses, and repositories**

Add:

- `BackfillChatChoice`
- expanded `BackfillJobSummary`
- `BackfillJobRecord`
- `ChatQueryRepository`
- `BackfillJobRepository`

Keep existing `BackfillJobQueryRepository` as a compatibility alias or wrapper so old callers keep working until bot wiring is updated.

- [ ] **Step 6: Run schema and repository tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_db_schema tests.test_repositories -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/telegram_ai_assistant/domain.py src/telegram_ai_assistant/db/schema.sql src/telegram_ai_assistant/db/repositories.py tests/test_db_schema.py tests/test_repositories.py
git commit -m "feat: add persisted backfill job repository"
```

## Task 2: Bot Backfill UX

**Files:**
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Modify: `src/telegram_ai_assistant/bot_router.py`
- Test: `tests/test_bot_services.py`
- Test: `tests/test_bot_router.py`

- [ ] **Step 1: Write failing bot service tests**

Replace MVP backfill assertions with tests for:

- `/backfill` shows day buttons `1`, `5`, `10`, `15`, `30`, `90`.
- `bf:d:30` opens page 0 of six chats.
- `bf:p:30:1` opens the second chat page and includes previous/next controls.
- `bf:c:30:0:1001` and `bf:confirm:30:1001` show chat, period, and UTC date range.
- `bf:start:30:1001` creates a pending job and returns job id/status.
- `bf:cancel:7` requests cancellation.
- invalid callbacks return safe text without database writes.

- [ ] **Step 2: Write failing router tests**

Add a test that a backfill callback returning `BotResponse` sends a message with inline markup to the callback chat. Keep existing review/status callbacks as toast-only behavior.

- [ ] **Step 3: Run bot tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services tests.test_bot_router -v
```

Expected: fail because callbacks still use `backfill:*:*` MVP behavior and router string-only handling.

- [ ] **Step 4: Implement bot UX**

Update `BotServices` to accept `chat_query_repository`, `backfill_job_repository`, `clock`, and `settings_snapshot`. Use callback data:

- `bf:d:{days}`
- `bf:p:{days}:{page}`
- `bf:c:{days}:{page}:{chat_id}`
- `bf:confirm:{days}:{chat_id}`
- `bf:start:{days}:{chat_id}`
- `bf:cancel:{job_id}`
- `bf:status:{job_id}`

Keep callback data compact and reload chat/job details from repositories.

- [ ] **Step 5: Implement router response handling**

Let `handle_backfill_callback(...)` return either `str` or `BotResponse`. When it returns `BotResponse`, answer the callback query with a short acknowledgement and send the response to the callback chat with markup.

- [ ] **Step 6: Run bot tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services tests.test_bot_router -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/telegram_ai_assistant/bot_services.py src/telegram_ai_assistant/bot_router.py tests/test_bot_services.py tests/test_bot_router.py
git commit -m "feat: add bot-managed backfill controls"
```

## Task 3: Worker Backfill Execution

**Files:**
- Modify: `src/telegram_ai_assistant/backfill.py`
- Modify: `src/telegram_ai_assistant/worker.py`
- Test: `tests/test_backfill.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write failing persisted runner tests**

Add tests proving one claimed job:

- runs one `BackfillService` batch with `chat_id`, `from_date`, `to_date`, and `next_before_message_id`;
- records progress and keeps status `running` when a next cursor remains;
- marks completed when there is no next cursor;
- marks cancelled without opening Telegram when status is `cancel_requested`;
- marks failed with sanitized error type and metadata.

- [ ] **Step 2: Write failing worker tests**

Add tests proving `Worker.process_backfill_jobs(limit=...)` executes the optional runner once, records counters, and does nothing when the runner is not configured.

- [ ] **Step 3: Run backfill/worker tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_backfill tests.test_worker -v
```

Expected: fail because persisted runner and worker hook are missing.

- [ ] **Step 4: Implement persisted runner and worker hook**

Add a runner that takes `job_repository`, `backfill_service_factory`, `connection_factory`, `client_factory`, and `limit`. Keep `BackfillRunner` legacy tests passing. Extend `WorkerResult` with `backfill_jobs`, `backfill_saved_messages`, and `backfill_failures`.

- [ ] **Step 5: Run backfill/worker tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_backfill tests.test_worker -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/telegram_ai_assistant/backfill.py src/telegram_ai_assistant/worker.py tests/test_backfill.py tests/test_worker.py
git commit -m "feat: run persisted backfill jobs in worker"
```

## Task 4: App Context And Runtime Wiring

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Test: `tests/test_app_context.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Write failing app context tests**

Assert:

- `run_worker_once()` injects `backfill_job_runner` into `Worker`.
- worker result merge includes backfill counters.
- `run_bot_forever()` passes both chat and backfill job repositories to `BotServices`.
- repositories receive account id and listener policy settings.

- [ ] **Step 2: Write failing runtime test**

Assert `run_worker(..., once=True)` prints JSON containing backfill counters and still prints no stdout in daemon mode.

- [ ] **Step 3: Run wiring tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context tests.test_runtime -v
```

Expected: fail because app context and runtime do not know about persisted backfill jobs.

- [ ] **Step 4: Implement wiring**

Wire `BackfillJobRepository`, `ChatQueryRepository`, and the persisted backfill runner into `AppContext`. Extend `merge_worker_results` and runtime worker payload.

- [ ] **Step 5: Run wiring tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context tests.test_runtime -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/telegram_ai_assistant/app_context.py src/telegram_ai_assistant/runtime.py tests/test_app_context.py tests/test_runtime.py
git commit -m "feat: wire bot-managed backfill runtime"
```

## Task 5: Operations Docs, Changelog, And Full Verification

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `tests/test_operations_docs.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing docs tests**

Assert the runbook mentions:

- `/backfill` creates persisted jobs;
- period buttons `1`, `5`, `10`, `15`, `30`, `90`;
- six chats per page;
- `app-worker` executes persisted jobs;
- database remains under `~/.telegram/telegram_ai_assistant/postgres`.

- [ ] **Step 2: Run docs tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_operations_docs -v
```

Expected: fail until docs are updated.

- [ ] **Step 3: Update docs and changelog**

Document the bot flow, worker execution model, safe logs, and Docker commands. Add an `Unreleased` changelog entry for bot-managed persisted backfill jobs.

- [ ] **Step 4: Run docs tests and full suite**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: all tests pass and diff check is clean.

- [ ] **Step 5: Commit**

```bash
git add docs/operations/local-runbook.md tests/test_operations_docs.py CHANGELOG.md
git commit -m "docs: document bot-managed backfill jobs"
```

## Parallelization Notes

Read-only explorers can run in parallel for repository, bot, and runtime architecture. Code edits should be integrated in the task order above because later layers depend on repository/domain contracts from Task 1.

## Final Verification

Before merge or handoff:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -v
git status --short --branch
```

Expected: full suite green and feature worktree clean after commits.
