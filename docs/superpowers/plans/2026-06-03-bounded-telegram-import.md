# Bounded Telegram Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent first live ingestion runs from importing a whole chat by default, while preserving explicit start-from-now and cursor-based modes.

**Architecture:** Add bootstrap settings, extend the read-only ingestion client with bounded retrieval helpers, and make `LiveIngestor` choose bootstrap behavior only when the chat cursor is empty. Existing repository cursor persistence remains the source of truth.

**Tech Stack:** Python 3.11, unittest, Telethon through the existing read-only adapter, Postgres repository fakes for unit tests.

---

### Task 1: Client Port Support

**Files:**
- Modify: `src/telegram_ai_assistant/ingestion/ports.py`
- Modify: `tests/test_ingestion_ports.py`

- [ ] **Step 1: Write failing tests**

Add tests proving `iter_recent_messages` calls `iter_messages` with `offset_date` and `reverse=True`, and `get_latest_message_id` calls `get_messages(limit=1)`.

- [ ] **Step 2: Run failing tests**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_ports -v`

Expected: fail because methods do not exist.

- [ ] **Step 3: Implement minimal port methods**

Add methods to `IngestionClient` and `ReadOnlyIngestionClient`. Keep methods retrieval-only and routed through `_allowed_method`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_ports -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: add bounded ingestion client methods`

### Task 2: Bootstrap Settings

**Files:**
- Modify: `src/telegram_ai_assistant/config.py`
- Modify: `tests/test_config.py`
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `tests/test_app_context.py`

- [ ] **Step 1: Write failing tests**

Add tests for default `telegram_ingest_bootstrap_mode == "recent"`, default `telegram_ingest_bootstrap_days == 30`, optional values, invalid mode, and non-positive days. Add an app context test asserting the ingestor receives both values.

- [ ] **Step 2: Run failing tests**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_config tests.test_app_context -v`

Expected: fail because settings and app wiring do not exist.

- [ ] **Step 3: Implement minimal settings**

Add dataclass fields, parsing, validation, and pass them from `AppContext.run_ingestor_once` into `LiveIngestor`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_config tests.test_app_context -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: add ingestion bootstrap settings`

### Task 3: Live Ingestor Bootstrap Modes

**Files:**
- Modify: `src/telegram_ai_assistant/ingestion/live.py`
- Modify: `tests/test_live_ingestor.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

- cursor `0` with `recent` calls `iter_recent_messages` with `now - bootstrap_days`;
- cursor `0` with `start_now` calls `get_latest_message_id`, saves nothing, and updates cursor;
- cursor `200` ignores bootstrap and calls `iter_new_messages(min_id=200)`;
- result includes `bootstrap_mode`, `oldest_sent_at`, and `newest_sent_at`.

- [ ] **Step 2: Run failing tests**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_ingestor -v`

Expected: fail because bootstrap behavior does not exist.

- [ ] **Step 3: Implement minimal bootstrap behavior**

Add bootstrap fields to `LiveIngestor`, branch only when cursor is empty, and compute date bounds while saving messages. Close the client in all paths.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_ingestor -v`

Expected: pass.

- [ ] **Step 5: Commit**

Commit: `feat: bound initial live ingestion`

### Task 4: Runtime Output And Docs

**Files:**
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `tests/test_runtime.py`
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing runtime/doc tests**

Add runtime assertions for `bootstrap_mode`, `oldest_sent_at`, and `newest_sent_at`. Update operations doc tests if they assert env coverage.

- [ ] **Step 2: Run failing tests**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_runtime tests.test_operations_docs -v`

Expected: fail because payload/docs do not include the new fields/settings.

- [ ] **Step 3: Implement runtime/docs**

Serialize the new optional result fields and document `TELEGRAM_INGEST_BOOTSTRAP_MODE` and `TELEGRAM_INGEST_BOOTSTRAP_DAYS`.

- [ ] **Step 4: Verify focused tests**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_runtime tests.test_operations_docs -v`

Expected: pass.

- [ ] **Step 5: Full verification**

Run: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

Commit: `docs: document bounded live ingestion`

## Self-Review

- Spec coverage: all settings, client port, ingestor modes, runtime output, and docs requirements are mapped to tasks.
- Placeholder scan: no placeholder steps remain.
- Type consistency: the plan consistently uses `telegram_ingest_bootstrap_mode`, `telegram_ingest_bootstrap_days`, `iter_recent_messages`, and `get_latest_message_id`.
