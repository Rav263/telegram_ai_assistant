# Bot Command Center Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first bot command center slice: stable shell navigation, callback contract, short-lived bot sessions, and `/cancel`.

**Architecture:** Keep current `BotRouter` as the owner-only dispatcher and `BotServices` as the UI/service boundary. Add `bot_sessions` storage behind a small repository. This slice does not implement assistant views, search, proactive notifications, settings mutation, or ops actions; it prepares the contracts those slices will use.

**Tech Stack:** Python 3.11, unittest, Postgres SQL schema, existing repository pattern, Telegram Bot API long-polling runtime.

---

## File Structure

- Modify `src/telegram_ai_assistant/db/schema.sql`: add `bot_sessions` table and expiry index.
- Modify `src/telegram_ai_assistant/domain.py`: add `BotSession`.
- Modify `src/telegram_ai_assistant/db/repositories.py`: add `BotSessionRepository`.
- Modify `src/telegram_ai_assistant/bot_router.py`: add `/cancel`, active-session text dispatch, and top-level menu callbacks.
- Modify `src/telegram_ai_assistant/bot_services.py`: add shell menus, session methods, persistent nav rows.
- Modify `src/telegram_ai_assistant/app_context.py`: wire `BotSessionRepository`.
- Modify `docs/operations/local-runbook.md` and `CHANGELOG.md`: document shell/session behavior.

## Scope

This plan implements slice 1 only.

Out of scope:

- `/today`, `/reminders`, `/waiting`, `/thoughts`;
- `/search` and `/item`;
- `bot_settings`;
- `scheduled_notifications`;
- `ops_jobs`;
- backup/migrate/restart actions.

## Task 1: Bot Session Storage

**Files:**
- Modify: `src/telegram_ai_assistant/db/schema.sql`
- Modify: `src/telegram_ai_assistant/domain.py`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_db_schema.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing schema tests**

Add tests asserting `bot_sessions` exists with:

- `telegram_user_id`;
- `bot_chat_id`;
- `flow_id`;
- `payload JSONB`;
- `expires_at`;
- primary key `(telegram_user_id, bot_chat_id, flow_id)`;
- index `idx_bot_sessions_expires_at`.

- [ ] **Step 2: Write failing repository tests**

Add `BotSessionRepositoryTests` covering:

- `save_session(...)` upserts a payload and expiry;
- `get_active_session(...)` returns `BotSession` only when `expires_at > now`;
- `clear_session(...)` deletes one flow;
- `clear_user_sessions(...)` deletes all flows for the owner/chat;
- `clear_expired_sessions(...)` deletes old sessions.

- [ ] **Step 3: Run red tests**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_db_schema.DBSchemaTests tests.test_repositories.BotSessionRepositoryTests -q
```

Expected: fail because `BotSessionRepository` and schema are missing.

- [ ] **Step 4: Implement minimal storage**

Add `BotSession` dataclass and repository methods. Use `_json_dumps`, `_json_object`, `_execute`, and `_fetchone` patterns already present in `repositories.py`.

- [ ] **Step 5: Run green tests**

Run the same command.

Expected: pass.

## Task 2: Router Session Contract And `/cancel`

**Files:**
- Modify: `src/telegram_ai_assistant/bot_router.py`
- Test: `tests/test_bot_router.py`

- [ ] **Step 1: Write failing router tests**

Add tests for:

- `/cancel` calls `services.cancel_session(user_id=..., chat_id=...)` and sends its response;
- non-command text with an active session calls `services.handle_session_message(user_id=..., chat_id=..., text=...)`;
- non-command text without an active session is ignored;
- `menu:assistant:0`, `menu:ops:0`, and `menu:settings:0` route to the correct services.

- [ ] **Step 2: Run red tests**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_router.BotRouterTests -q
```

Expected: fail because `/cancel`, session text dispatch, and new menu actions are missing.

- [ ] **Step 3: Implement router behavior**

Add `/cancel` to command handling as a special case because it needs `user_id` and `chat_id`.

For non-command text:

- call `services.has_active_session(user_id=user_id, chat_id=chat_id)`;
- if true, call `services.handle_session_message(user_id=user_id, chat_id=chat_id, text=text)`;
- if false, return without response.

Keep denied-user behavior unchanged.

- [ ] **Step 4: Run green tests**

Run the same command.

Expected: pass.

## Task 3: Persistent Shell Navigation

**Files:**
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Test: `tests/test_bot_services.py`
- Test: `tests/test_bot_router.py`

- [ ] **Step 1: Write failing service tests**

Add tests for:

- `help()` renders top-level Assistant/Ops/Settings/Help buttons;
- `assistant_menu()` renders assistant command buttons;
- `ops_menu()` renders ops command buttons;
- existing rich responses include shell navigation rows;
- `cancel_session(...)` clears sessions through the repository;
- `handle_session_message(...)` returns a safe placeholder when no flow-specific handler exists.

- [ ] **Step 2: Run red tests**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services.BotServicesTests tests.test_bot_router.BotRouterTests -q
```

Expected: fail because shell helpers and session methods are missing.

- [ ] **Step 3: Implement service shell**

Add helpers:

- `_main_menu_markup()`: top-level zones only;
- `_assistant_menu_markup()`;
- `_ops_menu_markup()`;
- `_settings_menu_markup()`;
- `_with_shell_navigation(rows)`.

Existing command-specific markups keep their action rows and append shell navigation rows.

- [ ] **Step 4: Run green tests**

Run the same command.

Expected: pass.

## Task 4: App Wiring, Docs, Changelog

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_app_context.py`
- Test: `tests/test_operations_docs.py`

- [ ] **Step 1: Write failing wiring/docs tests**

Add assertions that `run_bot_forever` wires `BotSessionRepository`, and the runbook documents `/cancel`, Assistant/Ops zones, and expiring sessions.

- [ ] **Step 2: Run red tests**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context.AppContextTests tests.test_operations_docs.OperationsDocsTests -q
```

Expected: fail because repository wiring and docs are missing.

- [ ] **Step 3: Implement wiring/docs**

Pass `BotSessionRepository` into `BotServices`. Update docs and changelog.

- [ ] **Step 4: Run green tests**

Run the same command.

Expected: pass.

## Task 5: Final Verification

- [ ] **Step 1: Run full suite**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run whitespace check**

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/operations/local-runbook.md docs/superpowers/plans/2026-06-06-bot-command-center-shell.md src/telegram_ai_assistant/app_context.py src/telegram_ai_assistant/bot_router.py src/telegram_ai_assistant/bot_services.py src/telegram_ai_assistant/db/repositories.py src/telegram_ai_assistant/db/schema.sql src/telegram_ai_assistant/domain.py tests/test_app_context.py tests/test_bot_router.py tests/test_bot_services.py tests/test_db_schema.py tests/test_operations_docs.py tests/test_repositories.py
git commit -m "feat: add bot command center shell"
```

## Self-Review

- Spec coverage: this plan covers slice 1 from `2026-06-06-bot-command-center-design.md`.
- Deferred spec requirements: assistant views, search, settings mutation, proactive runtime, and ops safe actions each need separate implementation plans.
- Placeholder scan: no placeholder steps.
- Type consistency: `BotSession`, `BotSessionRepository`, `bot_session_repository`, `flow_id`, `telegram_user_id`, and `bot_chat_id` are used consistently.
