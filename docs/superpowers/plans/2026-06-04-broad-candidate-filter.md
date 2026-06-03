# Broad Candidate Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden deterministic Russian candidate filtering so casual task-like messages are sent to LM Studio, with higher score/reasons for private chats.

**Architecture:** Add an optional `CandidateScoringContext` to the filtering boundary, keep `Message` unchanged, and let the worker request context from message sources that can provide it. Database context is read from `chats.chat_type`; fake/test sources can omit it and keep current behavior.

**Tech Stack:** Python 3.11, `unittest`, Postgres SQL repository layer, existing virtual environment at `/Users/blda/projects/telegram_ai_assistant/.venv`.

---

### Task 1: Broaden Filter Reasons And Scores

**Files:**
- Modify: `src/telegram_ai_assistant/filtering.py`
- Modify: `tests/test_filtering.py`

- [ ] **Step 1: Write failing tests for broad Russian task filtering**

Add these imports and tests to `tests/test_filtering.py`:

```python
from telegram_ai_assistant.filtering import CandidateScoringContext
```

```python
    def test_flags_private_chat_ozon_pickup_as_strong_task_candidate(self):
        result = score_message(
            make_message("Завтра нужно заехать на озон, забрать ирригатор"),
            CandidateScoringContext(chat_type="private"),
        )

        self.assertGreaterEqual(result.score, 0.8)
        self.assertIn(CandidateReason.TIME_EXPRESSION, result.reasons)
        self.assertIn(CandidateReason.TASK_INTENT, result.reasons)
        self.assertIn(CandidateReason.ERRAND_ACTION, result.reasons)
        self.assertIn(CandidateReason.LOGISTICS_CONTEXT, result.reasons)
        self.assertIn(CandidateReason.PRIVATE_CHAT_PRIORITY, result.reasons)

    def test_group_chat_ozon_pickup_passes_without_private_priority(self):
        private_result = score_message(
            make_message("Завтра нужно заехать на озон, забрать ирригатор"),
            CandidateScoringContext(chat_type="private"),
        )
        group_result = score_message(
            make_message("Завтра нужно заехать на озон, забрать ирригатор"),
            CandidateScoringContext(chat_type="supergroup"),
        )

        self.assertGreaterEqual(group_result.score, 0.6)
        self.assertLess(group_result.score, private_result.score)
        self.assertNotIn(CandidateReason.PRIVATE_CHAT_PRIORITY, group_result.reasons)

    def test_weak_abstract_need_phrase_stays_low_without_errand_reasons(self):
        result = score_message(
            make_message("Нужно понимать контекст"),
            CandidateScoringContext(chat_type="supergroup"),
        )

        self.assertGreater(result.score, 0.0)
        self.assertLess(result.score, 0.6)
        self.assertIn(CandidateReason.TASK_INTENT, result.reasons)
        self.assertNotIn(CandidateReason.ERRAND_ACTION, result.reasons)
        self.assertNotIn(CandidateReason.LOGISTICS_CONTEXT, result.reasons)
        self.assertNotIn(CandidateReason.PRIVATE_CHAT_PRIORITY, result.reasons)

    def test_time_expression_without_action_does_not_create_candidate(self):
        result = score_message(
            make_message("Сегодня хорошая погода"),
            CandidateScoringContext(chat_type="private"),
        )

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.reasons, ())
```

- [ ] **Step 2: Run filter tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_filtering -v
```

Expected: failure because `CandidateScoringContext` and new `CandidateReason` members do not exist.

- [ ] **Step 3: Implement minimal filter changes**

In `src/telegram_ai_assistant/filtering.py`:

- Add `CandidateScoringContext`.
- Add reasons `TASK_INTENT`, `ERRAND_ACTION`, `LOGISTICS_CONTEXT`, `PRIVATE_CHAT_PRIORITY`.
- Add regexes for task intent, errand action, logistics context, and expanded time phrases.
- Change `score_message` to accept optional context.
- Add private-chat priority only when `context.chat_type == "private"` and the message already has at least one non-time content reason.
- Treat `time_expression` as a modifier: it should strengthen task-like messages, but a standalone casual time mention should remain `0.0`.

The intended scoring constants are:

```python
TIME_EXPRESSION_WEIGHT = 0.25
TASK_INTENT_WEIGHT = 0.25
ERRAND_ACTION_WEIGHT = 0.25
LOGISTICS_CONTEXT_WEIGHT = 0.1
PRIVATE_CHAT_PRIORITY_WEIGHT = 0.15
```

- [ ] **Step 4: Run filter tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_filtering -v
```

Expected: all filtering tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/telegram_ai_assistant/filtering.py tests/test_filtering.py
git commit -m "feat: broaden candidate filter rules"
```

### Task 2: Pass Optional Scoring Context Through Worker

**Files:**
- Modify: `src/telegram_ai_assistant/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing worker context tests**

In `tests/test_worker.py`, update imports:

```python
from telegram_ai_assistant.filtering import CandidateReason, CandidateScore, CandidateScoringContext
```

Add this source class after `FakeMessageSource`:

```python
class ContextMessageSource(FakeMessageSource):
    def __init__(self, messages, context):
        super().__init__(messages)
        self.context = context
        self.context_requests = []

    def scoring_context_for(self, message):
        self.context_requests.append(message)
        return self.context
```

Add these tests to `WorkerTests`:

```python
    def test_process_messages_passes_optional_scoring_context_to_scorer(self):
        message = make_message("Завтра нужно заехать на озон, забрать ирригатор")
        source = ContextMessageSource([message], CandidateScoringContext(chat_type="private"))
        received = []

        def scorer(message_arg, context_arg=None):
            received.append((message_arg, context_arg))
            return CandidateScore(score=0.8, reasons=(CandidateReason.PRIVATE_CHAT_PRIORITY,))

        candidate_repository = FakeCandidateRepository()
        worker = Worker(message_source=source, candidate_repository=candidate_repository, scorer=scorer)

        result = worker.process_messages(limit=10)

        self.assertEqual(result.queued_candidates, 1)
        self.assertEqual(source.context_requests, [message])
        self.assertEqual(received, [(message, CandidateScoringContext(chat_type="private"))])
        self.assertIn("private_chat_priority", candidate_repository.enqueued[0]["reasons"])

    def test_process_messages_keeps_legacy_one_argument_scorers_compatible(self):
        message = make_message("надо бы проверить")
        source = ContextMessageSource([message], CandidateScoringContext(chat_type="private"))

        def scorer(message_arg):
            return CandidateScore(score=0.35, reasons=(CandidateReason.SELF_NOTE,))

        candidate_repository = FakeCandidateRepository()
        worker = Worker(message_source=source, candidate_repository=candidate_repository, scorer=scorer)

        result = worker.process_messages(limit=10)

        self.assertEqual(result.queued_candidates, 1)
        self.assertEqual(candidate_repository.enqueued[0]["reasons"], ("self_note",))
```

- [ ] **Step 2: Run worker tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_worker -v
```

Expected: failure because `Worker.process_messages` does not call `scoring_context_for` and always invokes scorers with one argument.

- [ ] **Step 3: Implement worker context pass-through**

In `src/telegram_ai_assistant/worker.py`:

- Add `import inspect`.
- Add a small helper to request optional context:

```python
    def _scoring_context_for(self, message: Any) -> Any | None:
        context_provider = getattr(self.message_source, "scoring_context_for", None)
        if context_provider is None:
            return None
        return context_provider(message)
```

- Add a helper that supports both one-argument test scorers and the new two-argument `score_message`:

```python
    def _score_message(self, message: Any) -> Any:
        context = self._scoring_context_for(message)
        try:
            parameter_count = len(inspect.signature(self.scorer).parameters)
        except (TypeError, ValueError):
            parameter_count = 2
        if parameter_count <= 1:
            return self.scorer(message)
        return self.scorer(message, context)
```

- Replace `candidate = self.scorer(message)` with `candidate = self._score_message(message)`.

- [ ] **Step 4: Run worker tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_worker -v
```

Expected: all worker tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/telegram_ai_assistant/worker.py tests/test_worker.py
git commit -m "feat: pass scoring context through worker"
```

### Task 3: Expose Chat Type Context From Repository

**Files:**
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Modify: `tests/test_repositories.py`

- [ ] **Step 1: Write failing repository tests**

In `tests/test_repositories.py`, update imports:

```python
from telegram_ai_assistant.filtering import CandidateScoringContext
```

Extend `MessageProcessingRepositoryTests.test_pending_messages_skips_processed_candidate_filter_stage`:

```python
        self.assertIn("left join chats c", normalized_sql)
```

Add this test to `MessageProcessingRepositoryTests`:

```python
    def test_scoring_context_for_reads_chat_type_for_message(self):
        connection = RecordingConnection()
        connection.cursor_obj.fetchone_result = {"chat_type": "private"}
        message = make_message()

        context = MessageProcessingRepository(connection).scoring_context_for(message)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("select chat_type", normalized_sql)
        self.assertIn("from chats", normalized_sql)
        self.assertEqual(params["account_id"], "main")
        self.assertEqual(params["chat_id"], 100)
        self.assertEqual(context, CandidateScoringContext(chat_type="private"))
```

- [ ] **Step 2: Run repository tests and verify RED**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories.MessageProcessingRepositoryTests -v
```

Expected: failure because pending message SQL does not join `chats` and `scoring_context_for` does not exist.

- [ ] **Step 3: Implement repository context lookup**

In `src/telegram_ai_assistant/db/repositories.py`:

- Import `CandidateScoringContext`.
- Add a `LEFT JOIN chats c` to `pending_messages` so pending reads are explicitly tied to available chat metadata. Continue returning `Message` only.
- Add:

```python
    def scoring_context_for(self, message: Message) -> CandidateScoringContext:
        sql = """
            SELECT chat_type
            FROM chats
            WHERE account_id = %(account_id)s
              AND chat_id = %(chat_id)s
        """
        row = _fetchone(
            self._connection,
            sql,
            {"account_id": message.account_id, "chat_id": message.chat_id},
        )
        if row is None:
            return CandidateScoringContext()
        return CandidateScoringContext(chat_type=str(_row_value(row, "chat_type", 0) or ""))
```

- [ ] **Step 4: Run repository tests and verify GREEN**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories.MessageProcessingRepositoryTests -v
```

Expected: all message processing repository tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/telegram_ai_assistant/db/repositories.py tests/test_repositories.py
git commit -m "feat: expose chat type scoring context"
```

### Task 4: Integration Checks And Documentation

**Files:**
- Modify: `CHANGELOG.md`
- Optionally modify: `docs/superpowers/specs/2026-06-04-broad-candidate-filter-design.md` only if implementation differs from design.

- [ ] **Step 1: Update changelog implementation entry**

Change the existing design-only changelog line to:

```markdown
- Added broad Russian candidate filtering with private-chat score priority for task-like messages.
```

- [ ] **Step 2: Run focused integration smoke check**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python - <<'PY'
from datetime import UTC, datetime
from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.filtering import CandidateScoringContext, score_message

message = Message(
    account_id="main",
    chat_id=100,
    telegram_message_id=200,
    sender_id=300,
    direction=MessageDirection.OUTGOING,
    sent_at=datetime(2026, 6, 4, 8, 0, tzinfo=UTC),
    text="Завтра нужно заехать на озон, забрать ирригатор",
)
print(score_message(message, CandidateScoringContext(chat_type="private")))
PY
```

Expected: score at least `0.8` and reasons include `private_chat_priority`.

- [ ] **Step 3: Run full verification**

Run:

```bash
env PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected: `232+` tests pass and no whitespace errors.

- [ ] **Step 4: Commit final docs/checklist changes**

Run:

```bash
git add CHANGELOG.md docs/superpowers/plans/2026-06-04-broad-candidate-filter.md
git commit -m "docs: plan broad candidate filter"
```

If the plan was committed before implementation, commit only changed implementation docs with:

```bash
git add CHANGELOG.md
git commit -m "docs: update broad candidate filter changelog"
```
