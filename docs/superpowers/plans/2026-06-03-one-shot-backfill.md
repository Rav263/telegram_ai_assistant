# One-Shot Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-shot CLI backfill path for one Telegram chat and explicit date range without moving the live ingestion cursor.

**Architecture:** Extend settings and the read-only ingestion port, then add a `BackfillService` that normalizes and upserts historical messages through existing repositories. Wire it into `AppContext` and `run backfill` with JSON output.

**Tech Stack:** Python 3.11, unittest, Telethon read-only adapter, existing Postgres repository abstractions.

---

### Task 1: Backfill Settings

**Files:**
- Modify: `src/telegram_ai_assistant/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add tests showing `Settings.from_env` reads:

```python
"TELEGRAM_BACKFILL_CHAT_ID": "380453832"
"TELEGRAM_BACKFILL_START_AT": "2022-01-01T00:00:00+00:00"
"TELEGRAM_BACKFILL_END_AT": "2022-02-01T00:00:00+00:00"
"TELEGRAM_BACKFILL_LIMIT": "250"
```

Also add tests rejecting invalid ISO datetimes, `end_at <= start_at`, and non-positive limit.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v`

Expected: fail because backfill settings do not exist.

- [ ] **Step 3: Implement settings**

Add optional fields:

```python
telegram_backfill_chat_id: int = 0
telegram_backfill_start_at: datetime | None = None
telegram_backfill_end_at: datetime | None = None
telegram_backfill_limit: int = 500
```

Implement `_optional_datetime` and positive integer validation.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: add backfill settings`

### Task 2: Read-Only Backfill Port

**Files:**
- Modify: `src/telegram_ai_assistant/ingestion/ports.py`
- Modify: `tests/test_ingestion_ports.py`

- [ ] **Step 1: Write failing tests**

Add a fake Telegram client and test:

```python
messages = await collect(
    client.iter_backfill_messages(
        chat_id=1001,
        start_at=start_at,
        end_at=end_at,
        before_message_id=500,
        limit=100,
    )
)
```

Assert it calls `iter_messages(chat_id, limit=100, offset_date=end_at, max_id=500, reverse=False)` and stops before messages older than `start_at`.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_ports -v`

Expected: fail because `iter_backfill_messages` does not exist.

- [ ] **Step 3: Implement port**

Add `iter_backfill_messages` to `IngestionClient` and `ReadOnlyIngestionClient`.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_ports -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: add read-only backfill history port`

### Task 3: Backfill Service

**Files:**
- Create: `src/telegram_ai_assistant/ingestion/backfill.py`
- Create: `tests/test_backfill_service.py`

- [ ] **Step 1: Write failing tests**

Test that `BackfillService.run_once()`:

- ensures account and chat;
- calls `iter_backfill_messages` with configured dates and limit;
- normalizes raw messages;
- upserts messages;
- returns `saved_count`, date bounds, and `next_before_message_id`;
- never calls `ChatRepository.update_ingestion_cursor`.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_backfill_service -v`

Expected: fail because service file does not exist.

- [ ] **Step 3: Implement service**

Create `BackfillRunResult` and `BackfillService`. Follow `LiveIngestor` dependency injection style.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_backfill_service -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: add one-shot backfill service`

### Task 4: Runtime And CLI Wiring

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `tests/test_app_context.py`
- Modify: `tests/test_runtime.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:

- `PROCESS_NAMES` includes `backfill`;
- CLI parses `run backfill`;
- `AppContext.run_backfill_once()` builds `BackfillService` with settings;
- `run_backfill()` prints JSON without message text.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime tests.test_cli -v`

Expected: fail because runtime wiring does not exist.

- [ ] **Step 3: Implement wiring**

Add `run_backfill` runner and `AppContext.run_backfill_once`.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime tests.test_cli -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: wire one-shot backfill runtime`

### Task 5: Documentation And Verification

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_operations_docs.py`

- [ ] **Step 1: Write failing docs tests**

Assert runbook mentions `TELEGRAM_BACKFILL_CHAT_ID`, `TELEGRAM_BACKFILL_START_AT`, `TELEGRAM_BACKFILL_END_AT`, `TELEGRAM_BACKFILL_LIMIT`, and `run backfill`.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_operations_docs -v`

Expected: fail until docs are updated.

- [ ] **Step 3: Update docs**

Document env variables, command, and the fact that backfill does not move live cursor.

- [ ] **Step 4: Full verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli version
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli health --offline
git diff --check
```

Expected: all commands succeed.

- [ ] **Step 5: Commit**

Commit: `docs: document one-shot backfill`

## Self-Review

- Spec coverage: settings, client port, service, runtime, CLI, and docs are covered.
- Placeholder scan: no TBD/TODO placeholder steps remain.
- Type consistency: plan uses `telegram_backfill_*`, `iter_backfill_messages`, `BackfillService`, and `BackfillRunResult` consistently.
