# Telegram AI Assistant Full MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the tested foundation into a runnable local-first MVP with config, CLI, Postgres persistence, Telegram ingestion ports, LM Studio extraction worker, backfill jobs, owner-only bot routing, health checks, and operational documentation.

**Architecture:** Keep business logic testable and mostly dependency-free. Real external systems sit behind ports/adapters: Postgres repositories, Telegram MTProto ingestion adapter, Bot API client, and OpenAI-compatible LM Studio client. Each process can be run separately through one CLI.

**Tech Stack:** Python 3.11+, project-local `.venv`, standard library for CLI/config/HTTP where practical, Postgres SQL migrations, optional runtime adapters for Telethon and real Postgres, `unittest` TDD tests with fakes for external systems.

---

## File Structure

- Modify `pyproject.toml`: add console script and optional dependency groups for real adapters.
- Modify `CHANGELOG.md`: add one Unreleased bullet per completed task.
- Create `src/telegram_ai_assistant/config.py`: environment-based settings loader and validation.
- Create `src/telegram_ai_assistant/cli.py`: `run`, `migrate`, `health`, and `version` commands.
- Create `src/telegram_ai_assistant/db/schema.sql`: Postgres schema for MVP tables.
- Create `src/telegram_ai_assistant/db/migrations.py`: migration runner around SQL files.
- Create `src/telegram_ai_assistant/db/repositories.py`: repository ports and Postgres-oriented SQL repository methods.
- Create `src/telegram_ai_assistant/ingestion/normalizer.py`: normalize Telegram-like messages into domain `Message`.
- Create `src/telegram_ai_assistant/ingestion/ports.py`: ingestion client protocols and read-only account boundary.
- Create `src/telegram_ai_assistant/ingestion/telethon_adapter.py`: Telethon adapter shell guarded by `ReadOnlyTelegramGuard`.
- Create `src/telegram_ai_assistant/content.py`: `ContentExtractor` interface and MVP text extractor.
- Create `src/telegram_ai_assistant/llm_client.py`: OpenAI-compatible LM Studio HTTP client.
- Create `src/telegram_ai_assistant/extraction.py`: prompt builder, batch extraction service, and conversion to domain objects.
- Create `src/telegram_ai_assistant/worker.py`: candidate processing and status update pipeline.
- Create `src/telegram_ai_assistant/backfill.py`: backfill job model and runner.
- Create `src/telegram_ai_assistant/bot_api.py`: minimal Telegram Bot API HTTP client.
- Create `src/telegram_ai_assistant/bot_router.py`: owner-only command and callback routing.
- Create `src/telegram_ai_assistant/health.py`: component health checks.
- Create `src/telegram_ai_assistant/runtime.py`: process runner functions for `ingestor`, `worker`, `bot`, `scheduler`, `all`.
- Create `docs/operations/manual-unread-smoke-test.md`: manual Telegram unread verification checklist.
- Create tests mirroring each new module under `tests/`.

## Parallel Work Boundaries

After Task 1 and Task 2 are complete, these scopes can run in parallel:

- Storage scope: `src/telegram_ai_assistant/db/*`, `tests/test_db_*.py`.
- Ingestion scope: `src/telegram_ai_assistant/ingestion/*`, `src/telegram_ai_assistant/content.py`, `tests/test_ingestion_*.py`, `tests/test_content.py`.
- LLM/worker scope: `src/telegram_ai_assistant/llm_client.py`, `src/telegram_ai_assistant/extraction.py`, `src/telegram_ai_assistant/worker.py`, `tests/test_llm_client.py`, `tests/test_extraction.py`, `tests/test_worker.py`.
- Bot/backfill/health scope: `src/telegram_ai_assistant/bot_api.py`, `src/telegram_ai_assistant/bot_router.py`, `src/telegram_ai_assistant/backfill.py`, `src/telegram_ai_assistant/health.py`, tests for those modules.

Only the coordinating agent edits `CHANGELOG.md`, `pyproject.toml`, and `src/telegram_ai_assistant/cli.py`.

## Task 1: Config Loader And CLI Skeleton

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/config.py`
- Create: `src/telegram_ai_assistant/cli.py`
- Create: `src/telegram_ai_assistant/runtime.py`
- Test: `tests/test_config.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py` with tests that call `Settings.from_env()` and assert it reads `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `DATABASE_URL`, and `LM_STUDIO_BASE_URL`, and raises `ConfigError` when a required value is missing.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'telegram_ai_assistant.config'`.

- [ ] **Step 3: Implement config**

Create `ConfigError`, immutable `Settings`, and `Settings.from_env(env: Mapping[str, str]) -> Settings`. Parse `TELEGRAM_API_ID` and `TELEGRAM_ALLOWED_USER_ID` as integers. Default `LM_STUDIO_BASE_URL` to `http://127.0.0.1:1234/v1` and default `BACKFILL_DAYS` to `30`.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v`

Expected: PASS.

- [ ] **Step 5: Write failing CLI tests**

Create `tests/test_cli.py` with tests that `build_parser().parse_args(["version"])` returns command `version`, and `build_parser().parse_args(["run", "worker"])` returns command `run` and process `worker`.

- [ ] **Step 6: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_cli -v`

Expected: FAIL because `telegram_ai_assistant.cli` does not exist or lacks `build_parser`.

- [ ] **Step 7: Implement CLI skeleton**

Create `build_parser()`, `main(argv: Sequence[str] | None = None) -> int`, and runtime stubs in `runtime.py` that return exit code `0` for `version` and raise `NotImplementedError` for real process runners. Task 8 replaces these stubs with dispatchable runner functions.

- [ ] **Step 8: Verify CLI GREEN and full suite**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config tests.test_cli -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

- [ ] **Step 9: Update changelog and commit**

Add `- Added environment config loading and CLI skeleton.` to `CHANGELOG.md`, update `pyproject.toml` with a `telegram-ai-assistant = "telegram_ai_assistant.cli:main"` console script, then commit:

```bash
git add CHANGELOG.md pyproject.toml src/telegram_ai_assistant/config.py src/telegram_ai_assistant/cli.py src/telegram_ai_assistant/runtime.py tests/test_config.py tests/test_cli.py
git commit -m "feat: add config loader and CLI skeleton"
```

## Task 2: Postgres Schema And Repository Ports

**Files:**
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/db/__init__.py`
- Create: `src/telegram_ai_assistant/db/schema.sql`
- Create: `src/telegram_ai_assistant/db/migrations.py`
- Create: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_db_schema.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing schema tests**

Create tests that read `schema.sql` and assert it defines `accounts`, `chats`, `messages`, `raw_updates`, `message_candidates`, `extracted_items`, `item_status_events`, `review_queue`, `llm_runs`, `backfill_jobs`, `bot_actions`, and `settings`.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema -v`

Expected: FAIL because schema file is missing.

- [ ] **Step 3: Implement schema**

Write idempotent Postgres DDL with `CREATE TABLE IF NOT EXISTS` for all required tables. Include unique constraint on `(account_id, chat_id, telegram_message_id)` for `messages`.

- [ ] **Step 4: Verify schema GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema -v`

- [ ] **Step 5: Write failing repository SQL tests**

Create repository tests using a fake connection/cursor that records SQL and parameters. Assert `MessageRepository.upsert_message(message)` emits an insert with `ON CONFLICT`, and `CandidateRepository.enqueue_candidate(...)` writes score and reasons.

- [ ] **Step 6: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_repositories -v`

Expected: FAIL because repositories do not exist.

- [ ] **Step 7: Implement repository ports**

Implement repository classes with small methods and no global connection. Accept a DB-API-like connection in constructors. Keep SQL in repository methods and expose `apply_schema(connection)` in `migrations.py`.

- [ ] **Step 8: Verify GREEN and commit**

Run full suite, update changelog with `- Added Postgres schema and repository ports.`, and commit:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git add CHANGELOG.md src/telegram_ai_assistant/db tests/test_db_schema.py tests/test_repositories.py
git commit -m "feat: add Postgres schema and repositories"
```

## Task 3: Ingestion Normalization And Content Extraction

**Files:**
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/ingestion/__init__.py`
- Create: `src/telegram_ai_assistant/ingestion/normalizer.py`
- Create: `src/telegram_ai_assistant/ingestion/ports.py`
- Create: `src/telegram_ai_assistant/ingestion/telethon_adapter.py`
- Create: `src/telegram_ai_assistant/content.py`
- Test: `tests/test_ingestion_normalizer.py`
- Test: `tests/test_ingestion_ports.py`
- Test: `tests/test_content.py`

- [ ] **Step 1: Write failing normalizer and content tests**

Tests should build simple Telegram-like objects with attributes `id`, `chat_id`, `sender_id`, `date`, `message`, `text`, `raw_text`, `reply_to_msg_id`, and `out`. Assert normalization produces domain `Message` with direction, text/caption, ids, and timestamp. Test `TextContentExtractor.extract(message)` returns `message.content_text` and ignores non-text metadata.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_normalizer tests.test_content -v`

- [ ] **Step 3: Implement normalizer and content extractor**

Implement `normalize_telegram_message(account_id, raw_message) -> Message`, `ContentExtractor` protocol, and `TextContentExtractor`.

- [ ] **Step 4: Write failing read-only ingestion port tests**

Tests should instantiate `ReadOnlyIngestionClient` with a fake client and assert allowed methods call through while mutating methods are rejected by `ReadOnlyTelegramGuard`.

- [ ] **Step 5: Implement ports and adapter shell**

Create protocols for `iter_new_messages`, `iter_history`, and `close`. Implement a Telethon adapter shell that imports Telethon lazily and documents that unread behavior still needs manual smoke test.

- [ ] **Step 6: Verify GREEN and commit**

Run full suite, update changelog with `- Added Telegram ingestion normalization and content extractor ports.`, and commit:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git add CHANGELOG.md src/telegram_ai_assistant/ingestion src/telegram_ai_assistant/content.py tests/test_ingestion_normalizer.py tests/test_ingestion_ports.py tests/test_content.py
git commit -m "feat: add ingestion normalization ports"
```

## Task 4: LM Studio Client And Extraction Service

**Files:**
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/llm_client.py`
- Create: `src/telegram_ai_assistant/extraction.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_extraction.py`

- [ ] **Step 1: Write failing LM Studio client tests**

Use fake opener/callable transport. Assert `LMStudioClient.extract_json(messages=[...])` posts to `/chat/completions`, includes model and messages, and returns assistant content. Assert transport failures raise `LMStudioError`.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_llm_client -v`

- [ ] **Step 3: Implement LM Studio client**

Use standard library `urllib.request` or injectable transport. Do not require network in tests.

- [ ] **Step 4: Write failing extraction service tests**

Tests should pass candidate messages and a fake LLM returning valid JSON, assert `ExtractionService.extract_batch(...)` returns parsed items and status changes, and includes source message ids in prompts.

- [ ] **Step 5: Implement extraction service**

Build prompts, call `LMStudioClient`, reuse `parse_extraction_response`, and expose pure conversion helpers.

- [ ] **Step 6: Verify GREEN and commit**

Run full suite, update changelog with `- Added LM Studio client and extraction service.`, and commit:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git add CHANGELOG.md src/telegram_ai_assistant/llm_client.py src/telegram_ai_assistant/extraction.py tests/test_llm_client.py tests/test_extraction.py
git commit -m "feat: add LM Studio extraction service"
```

## Task 5: Worker Pipeline

**Files:**
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write failing worker tests**

Use fake message, candidate, item, review, and LLM repositories. Assert worker scores unprocessed messages, enqueues broad candidates, extracts high-confidence items, routes low-confidence items to review, and records LM failures without blocking ingestion state.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_worker -v`

- [ ] **Step 3: Implement worker**

Create `Worker.process_candidates(limit: int) -> WorkerResult` and small dataclasses for counts. Keep repository methods injected so tests use fakes.

- [ ] **Step 4: Verify GREEN and commit**

Run full suite, update changelog with `- Added worker pipeline for candidates, extraction, and review routing.`, and commit.

## Task 6: Backfill Jobs

**Files:**
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/backfill.py`
- Test: `tests/test_backfill.py`

- [ ] **Step 1: Write failing backfill tests**

Tests should assert default jobs cover the last 30 days, older jobs can be requested by date range, progress cursor is updated after each batch, and cancelled jobs stop before fetching more history.

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_backfill -v`

- [ ] **Step 3: Implement backfill**

Create `BackfillJob`, `BackfillStatus`, and `BackfillRunner.run_once(job_id)` with injected repositories and ingestion client.

- [ ] **Step 4: Verify GREEN and commit**

Run full suite, update changelog with `- Added configurable Telegram history backfill jobs.`, and commit.

## Task 7: Owner-Only Bot Router And Bot API Client

**Files:**
- Modify: `CHANGELOG.md`
- Create: `src/telegram_ai_assistant/bot_api.py`
- Create: `src/telegram_ai_assistant/bot_router.py`
- Test: `tests/test_bot_api.py`
- Test: `tests/test_bot_router.py`

- [ ] **Step 1: Write failing bot API client tests**

Use fake transport. Assert `send_message`, `answer_callback_query`, and `edit_message_reply_markup` call the right Bot API endpoints with expected JSON.

- [ ] **Step 2: Implement Bot API client**

Use injectable transport and standard-library JSON encoding.

- [ ] **Step 3: Write failing bot router tests**

Assert denied users are ignored or denied and logged, `/summary`, `/tasks`, `/review`, `/backfill`, `/blacklist`, `/settings`, and `/health` dispatch to injected services, and inline callbacks map to review/status/backfill actions.

- [ ] **Step 4: Implement bot router**

Create update dataclasses or accept dict updates, enforce `BotAccessController`, keep command handlers small.

- [ ] **Step 5: Verify GREEN and commit**

Run full suite, update changelog with `- Added owner-only summary bot routing and Bot API client.`, and commit.

## Task 8: Health Checks And Runtime Runners

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `src/telegram_ai_assistant/cli.py`
- Create: `src/telegram_ai_assistant/health.py`
- Test: `tests/test_health.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Write failing health tests**

Use fake components for Postgres, LM Studio, ingestion, worker, and bot. Assert health reports `ok`, `degraded`, or `down` with component details.

- [ ] **Step 2: Implement health checks**

Create `HealthStatus`, `ComponentHealth`, `HealthReport`, and `HealthChecker`.

- [ ] **Step 3: Write failing runtime tests**

Assert `run worker`, `run bot`, `run scheduler`, `run ingestor`, and `run all` dispatch through `runtime.run_process(process_name, settings)`.

- [ ] **Step 4: Implement runtime dispatch**

Wire CLI to settings loader and process dispatch. Keep real infinite loops behind functions that can be injected/mocked.

- [ ] **Step 5: Verify GREEN and commit**

Run full suite, update changelog with `- Added health checks and runtime process dispatch.`, and commit.

## Task 9: Operations Documentation And Manual Unread Smoke Test

**Files:**
- Modify: `CHANGELOG.md`
- Create: `docs/operations/manual-unread-smoke-test.md`
- Create: `docs/operations/local-runbook.md`
- Test: `tests/test_operations_docs.py`

- [ ] **Step 1: Write failing docs tests**

Tests should assert the manual unread smoke test document mentions a controlled chat, unread badge verification, no `mark_read`, no `send_read_acknowledge`, and expected rollback if unread behavior fails.

- [ ] **Step 2: Implement docs**

Write concise runbooks for local setup, `.env`, Postgres, LM Studio endpoint, test commands, and manual unread verification.

- [ ] **Step 3: Verify GREEN and commit**

Run full suite, update changelog with `- Added local operations runbooks and manual unread smoke test checklist.`, and commit.

## Final Verification

- [ ] Run: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`
- [ ] Run: `.venv/bin/python -m telegram_ai_assistant.cli version`
- [ ] Run: `.venv/bin/python -m telegram_ai_assistant.cli health --offline`
- [ ] Run: `git status --short`
- [ ] Confirm worktree branch contains focused commits and changelog entries.
