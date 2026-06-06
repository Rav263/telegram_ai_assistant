# LLM Action Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace direct LLM persistence decisions with typed, audited LLM action proposals while keeping current bot and worker commands compatible.

**Architecture:** Add `llm_actions` as the action ledger, route worker extraction through typed actions, auto-apply only high-confidence `create_item`, and queue all other actions for owner review. Keep `review_queue` as the bot-facing review queue and preserve legacy item/status review behavior.

**Tech Stack:** Python 3.11, unittest, Postgres SQL, existing repository pattern, LM Studio OpenAI-compatible JSON schema, Telegram Bot API long-polling runtime.

---

## File Structure

- Modify `src/telegram_ai_assistant/domain.py`: add `LLMAction`, `LLMActionState`, `LLMActionType`, and `LLMActionDecision`.
- Modify `src/telegram_ai_assistant/db/schema.sql`: add `llm_actions`, `review_queue.llm_action_id`, indexes, and compatibility ALTER statements.
- Modify `src/telegram_ai_assistant/db/repositories.py`: add `LLMActionRepository`, action row mapping, item context query, and action-backed review helpers.
- Modify `src/telegram_ai_assistant/llm.py`: add typed action parser and strict validation.
- Modify `src/telegram_ai_assistant/llm_client.py`: switch response schema from `items/status_changes` to `actions`.
- Modify `src/telegram_ai_assistant/extraction.py`: build the action prompt with candidate messages and global open items, return `actions`.
- Modify `src/telegram_ai_assistant/worker.py`: persist actions, apply action policy, and remove legacy direct status-change auto-apply.
- Modify `src/telegram_ai_assistant/app_context.py`: wire `LLMActionRepository` and open-item context into the worker.
- Modify `src/telegram_ai_assistant/bot_services.py`: render action-backed reviews grouped by source message.
- Modify docs and changelog: record LLM action layer behavior and Russian user-facing output rule.
- Add tests in `tests/test_db_schema.py`, `tests/test_repositories.py`, `tests/test_llm.py`, `tests/test_llm_client.py`, `tests/test_extraction.py`, `tests/test_worker.py`, `tests/test_bot_services.py`, and `tests/test_app_context.py`.

## Task 1: Action Ledger Schema And Repository

**Files:**
- Modify: `src/telegram_ai_assistant/domain.py`
- Modify: `src/telegram_ai_assistant/db/schema.sql`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_db_schema.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing schema tests**

Add tests asserting:

- `CREATE TABLE IF NOT EXISTS llm_actions`;
- `action_key TEXT NOT NULL UNIQUE`;
- `action_type TEXT NOT NULL`;
- `state TEXT NOT NULL`;
- `confidence NUMERIC(5, 4) NOT NULL`;
- `target_item_id TEXT`;
- `payload JSONB NOT NULL`;
- `source_refs JSONB NOT NULL`;
- `rationale TEXT NOT NULL DEFAULT ''`;
- `review_queue` has `llm_action_id BIGINT`;
- indexes exist for state and action key.

- [ ] **Step 2: Write failing repository tests**

Add `LLMActionRepositoryTests` covering:

```python
repository.save_action(action)
repository.get_by_key(action.action_key)
repository.list_pending_review_actions(limit=5)
repository.mark_review(action_id)
repository.mark_applied(action_id)
repository.mark_rejected(action_id)
repository.mark_failed(action_id, error_type="ValidationError")
```

Also add a test that the deterministic helper returns the same key for equivalent normalized payloads.

- [ ] **Step 3: Run red tests**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_db_schema.DBSchemaTests tests.test_repositories.LLMActionRepositoryTests -q
```

Expected: fail because `LLMActionRepository`, domain types, and schema are missing.

- [ ] **Step 4: Implement minimal ledger**

Add domain types and repository methods. Follow existing `_json_dumps`, `_json_object`, `_source_refs_from_json`, `_execute`, `_fetchone`, and `_fetchall` patterns.

- [ ] **Step 5: Run green tests**

Run the same command. Expected: pass.

## Task 2: Typed LLM Actions, Prompt, And JSON Schema

**Files:**
- Modify: `src/telegram_ai_assistant/llm.py`
- Modify: `src/telegram_ai_assistant/llm_client.py`
- Modify: `src/telegram_ai_assistant/extraction.py`
- Test: `tests/test_llm.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_extraction.py`

- [ ] **Step 1: Write failing parser tests**

Add tests for valid actions:

- `create_item`;
- `update_item_status`;
- `update_item_field`;
- `merge_duplicate`;
- `schedule_notification`;
- `link_source`.

Add rejection tests for unknown action type, invalid confidence, missing source ids, invalid status, invalid field, and non-Russian user-facing title/description/rationale for `create_item`.

- [ ] **Step 2: Write failing schema/prompt tests**

Assert LM Studio schema requires top-level `actions`, action `type`, `confidence`, `source_message_ids`, `rationale`, and `payload`.

Assert extraction prompt includes:

- `Candidate messages:`;
- `Open items:`;
- `All user-facing generated text must be Russian.`;
- `Propose actions only.`;
- examples for Ozon/irrigator and completion messages.

- [ ] **Step 3: Run red tests**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_llm tests.test_llm_client tests.test_extraction -q
```

Expected: fail because typed actions and prompt/schema are missing.

- [ ] **Step 4: Implement parser/prompt/schema**

Add `ParsedLLMAction`, `ParsedActionResponse`, `parse_action_response`, and `build_action_prompt(candidate_messages, open_items)`. Preserve legacy `parse_extraction_response` only if existing tests still use it.

- [ ] **Step 5: Run green tests**

Run the same command. Expected: pass.

## Task 3: Worker Action Policy Cutover

**Files:**
- Modify: `src/telegram_ai_assistant/worker.py`
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_worker.py`
- Test: `tests/test_app_context.py`

- [ ] **Step 1: Write failing worker tests**

Add tests proving:

- worker passes candidate messages plus global open items to extraction;
- high-confidence `create_item` saves item and marks action applied;
- low-confidence `create_item` queues action review;
- `update_item_status`, `update_item_field`, `merge_duplicate`, `schedule_notification`, and `link_source` always queue action review;
- repeated actions do not duplicate action saves by key;
- malformed action batch records safe runtime event and keeps candidates queued.

- [ ] **Step 2: Write failing app wiring test**

Assert `run_worker_once` passes `LLMActionRepository` and the open-item context provider into `Worker`.

- [ ] **Step 3: Run red tests**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_worker.WorkerTests tests.test_app_context.AppContextTests -q
```

Expected: fail because worker action policy and wiring are missing.

- [ ] **Step 4: Implement worker policy**

Add worker dependencies:

- `llm_action_repository`;
- `open_item_repository` or use `item_query_repository`;
- `open_item_context_limit`, default `200`.

Use action policy:

- auto-apply high-confidence `create_item`;
- enqueue review for every other valid action;
- mark candidates processed after action persistence/policy succeeds.

- [ ] **Step 5: Run green tests**

Run the same command. Expected: pass.

## Task 4: Bot Action Review Rendering

**Files:**
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_bot_services.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing bot service tests**

Add action-backed `ReviewEntry` fixtures. Assert `/review`:

- groups action reviews by primary source message id;
- shows action type, title/target/new value, confidence, and Russian rationale;
- keeps legacy item review rendering;
- sends `review:approve:<id>` and `review:reject:<id>` buttons.

- [ ] **Step 2: Write failing repository approval tests**

Assert `ReviewRepository.approve_review`:

- loads action-backed review;
- applies `create_item`;
- applies `update_item_status`;
- marks action applied and review approved.

Assert `reject_review` marks action rejected and review rejected.

- [ ] **Step 3: Run red tests**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services.BotServicesTests tests.test_repositories.ReviewRepositoryTests -q
```

Expected: fail because action-backed review behavior is missing.

- [ ] **Step 4: Implement bot/review behavior**

Extend review formatting and approval logic while preserving legacy item/status review behavior.

- [ ] **Step 5: Run green tests**

Run the same command. Expected: pass.

## Task 5: Docs, Evaluation Fixtures, Final Verification

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`
- Add: `tests/fixtures/llm_actions_ru.json`
- Add or modify: `tests/test_llm_action_fixtures.py`

- [ ] **Step 1: Write fixture tests**

Add synthetic Russian cases:

- Ozon/irrigator reminder;
- owner says completed;
- repeated duplicate mention;
- source link to existing item.

Assert expected action types and Russian user-facing fields.

- [ ] **Step 2: Run red fixture test**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_llm_action_fixtures -q
```

Expected: fail until fixtures and helper validation exist.

- [ ] **Step 3: Add docs/changelog/fixtures**

Document:

- `llm_actions`;
- review-first policy for non-create actions;
- Russian LLM output rule;
- no raw Telegram text in runtime events.

- [ ] **Step 4: Run full verification**

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -q
git diff --check
```

Expected: all tests pass and whitespace check is clean.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md docs/operations/local-runbook.md docs/superpowers/plans/2026-06-06-llm-action-layer.md src/telegram_ai_assistant tests
git commit -m "feat: add llm action layer"
```

## Self-Review

- Spec coverage: tasks cover schema, typed actions, prompt/schema, worker policy, bot review behavior, docs, and fixtures.
- Deferred spec items: scheduled notification dispatch remains out of scope by design.
- Placeholder scan: no unfinished markers are required to execute this plan.
- Type consistency: `LLMAction`, `LLMActionType`, `LLMActionState`, `action_key`, `source_refs`, and `llm_action_id` are used consistently.
