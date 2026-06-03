# Bot Command Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete owner-only bot command surface with `/start`, `/help`, `/summary`, `/review`, `/backfill`, `/blacklist`, `/settings`, and inline menu/action buttons.

**Architecture:** Keep `BotRouter` as the update/callback dispatcher and `BotServices` as the product orchestration layer. Add small bot-facing data models plus repository query/action methods for summary and review; keep SQL out of formatting code and keep secret-safe output allowlisted. Use the existing Docker/runtime process and wire the new dependencies through `AppContext.run_bot_forever`.

**Tech Stack:** Python 3.11, unittest, Postgres SQL through existing repository helpers, Telegram Bot API inline keyboards, Docker Compose.

---

## File Structure

- Modify `src/telegram_ai_assistant/bot_router.py`: add `/start`, `/help`, menu callbacks, and safe callback failure handling.
- Modify `src/telegram_ai_assistant/bot_services.py`: implement help/menu, summary, review, MVP backfill/blacklist/settings, and callback handlers.
- Modify `src/telegram_ai_assistant/db/repositories.py`: extend `ItemQueryRepository` and `ReviewRepository`; add `BackfillJobQueryRepository`.
- Modify `src/telegram_ai_assistant/app_context.py`: wire new repositories and a safe settings snapshot into `BotServices`.
- Modify `tests/test_bot_router.py`: command dispatch and menu callback tests.
- Modify `tests/test_bot_services.py`: service formatting, callbacks, settings safety, and MVP command tests.
- Modify `tests/test_repositories.py`: SQL/repository tests for summary, review query/actions, and backfill job lookup.
- Modify `tests/test_app_context.py`: production bot wiring test expectations.
- Modify `tests/test_db_schema.py`: assert review state columns are already present and no unsafe schema gap exists.
- Modify `tests/test_operations_docs.py`, `docs/operations/local-runbook.md`, and `CHANGELOG.md`: document implemented commands and verification.

No new database migration is expected because `review_queue.state`, `review_queue.payload`, and `review_queue.resolved_at` already exist. If tests show a missing compatibility column, extend `src/telegram_ai_assistant/db/schema.sql` with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`.

## Task 1: Router Commands And Menu Callbacks

**Files:**
- Modify: `src/telegram_ai_assistant/bot_router.py`
- Test: `tests/test_bot_router.py`

- [ ] **Step 1: Write failing router tests for `/start`, `/help`, and menu callbacks**

Add tests like this to `BotRouterTests`:

```python
def test_start_and_help_dispatch_to_help_service(self):
    for command in ("/start", "/help"):
        with self.subTest(command=command):
            services = FakeBotServices()
            bot = FakeBotApi()
            router = BotRouter(
                access=BotAccessController(allowed_user_id=100),
                bot_api=bot,
                services=services,
            )

            router.handle_update(
                {
                    "message": {
                        "from": {"id": 100},
                        "chat": {"id": 123},
                        "text": command,
                    }
                }
            )

            self.assertEqual(services.calls, [("help",)])
            self.assertEqual(bot.sent_messages[0], (123, "help response", None))

def test_menu_callbacks_dispatch_to_command_services_and_send_message(self):
    callback_cases = {
        "menu:summary:0": ("summary", "summary response"),
        "menu:tasks:0": ("tasks", "tasks response"),
        "menu:review:0": ("review", "review response"),
        "menu:backfill:0": ("backfill", "backfill response"),
        "menu:health:0": ("health", "health response"),
        "menu:logs:0": ("logs", "logs response"),
        "menu:settings:0": ("settings", "settings response"),
        "menu:help:0": ("help", "help response"),
    }

    for callback_data, (expected_method, expected_text) in callback_cases.items():
        with self.subTest(callback_data=callback_data):
            services = FakeBotServices()
            bot = FakeBotApi()
            router = BotRouter(
                access=BotAccessController(allowed_user_id=100),
                bot_api=bot,
                services=services,
            )

            router.handle_update(
                {
                    "callback_query": {
                        "id": "callback-1",
                        "from": {"id": 100},
                        "message": {"chat": {"id": 123}, "message_id": 456},
                        "data": callback_data,
                    }
                }
            )

            self.assertEqual(services.calls, [(expected_method,)])
            self.assertEqual(bot.answered_callbacks[0], ("callback-1", "Opened.", False))
            self.assertEqual(bot.sent_messages[0][1], expected_text)
```

Also add `help()` to `FakeBotServices`:

```python
def help(self) -> str:
    self.calls.append(("help",))
    return "help response"
```

- [ ] **Step 2: Run router tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_router -v
```

Expected: fails because `/start`, `/help`, and `menu:*` callbacks are not implemented.

- [ ] **Step 3: Implement router command and callback dispatch**

Update `COMMANDS`:

```python
COMMANDS = {
    "/start": "help",
    "/help": "help",
    "/summary": "summary",
    "/tasks": "tasks",
    "/review": "review",
    "/backfill": "backfill",
    "/blacklist": "blacklist",
    "/settings": "settings",
    "/health": "health",
    "/logs": "logs",
}
```

Add menu dispatch in `_handle_callback` before review/status/backfill branches:

```python
if kind == "menu":
    method_name = {
        "summary": "summary",
        "tasks": "tasks",
        "review": "review",
        "backfill": "backfill",
        "health": "health",
        "logs": "logs",
        "settings": "settings",
        "help": "help",
    }.get(action)
    if method_name is None:
        return
    response = getattr(self.services, method_name)()
    if callback_id:
        self.bot_api.answer_callback_query(callback_query_id=callback_id, text="Opened.")
    message = callback_query.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", 0))
    if chat_id:
        self._send_response(chat_id=chat_id, response=response)
    return
```

- [ ] **Step 4: Run router tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_router -v
```

Expected: all router tests pass.

- [ ] **Step 5: Commit router work**

```bash
git add src/telegram_ai_assistant/bot_router.py tests/test_bot_router.py
git commit -m "feat: add bot menu routing"
```

## Task 2: Help Menu And Task Menu Buttons

**Files:**
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Test: `tests/test_bot_services.py`

- [ ] **Step 1: Write failing service tests for help/menu and task menu button**

Add:

```python
def test_help_lists_commands_with_main_menu_buttons(self):
    services = BotServices(runtime_event_repository=FakeRuntimeEventRepository())

    response = services.help()

    self.assertIn("Commands:", response.text)
    for command in ("/summary", "/tasks", "/review", "/backfill", "/blacklist", "/settings", "/health", "/logs"):
        self.assertIn(command, response.text)
    self.assertEqual(
        response.reply_markup,
        {
            "inline_keyboard": [
                [
                    {"text": "Summary", "callback_data": "menu:summary:0"},
                    {"text": "Tasks", "callback_data": "menu:tasks:0"},
                ],
                [
                    {"text": "Review", "callback_data": "menu:review:0"},
                    {"text": "Backfill", "callback_data": "menu:backfill:0"},
                ],
                [
                    {"text": "Health", "callback_data": "menu:health:0"},
                    {"text": "Logs", "callback_data": "menu:logs:0"},
                ],
                [
                    {"text": "Settings", "callback_data": "menu:settings:0"},
                    {"text": "Help", "callback_data": "menu:help:0"},
                ],
            ]
        },
    )
```

Update existing `/tasks` expectations so task markup includes a final menu row:

```python
[{"text": "Menu", "callback_data": "menu:help:0"}]
```

- [ ] **Step 2: Run bot service tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services -v
```

Expected: fails because `help()` and task menu row do not exist.

- [ ] **Step 3: Implement help menu helpers**

Add `help()` to `BotServices`:

```python
def help(self) -> BotResponse:
    return BotResponse(
        text=_format_help(),
        reply_markup=_main_menu_markup(),
    )
```

Add helpers:

```python
def _format_help() -> str:
    return "\n".join(
        [
            "Commands:",
            "/summary - daily structured summary",
            "/tasks - open tasks and commitments",
            "/review - pending low-confidence items",
            "/backfill - safe history import controls",
            "/blacklist - listener allow/deny policy",
            "/settings - non-secret runtime settings",
            "/health - component health",
            "/logs - latest safe warning/error events",
        ]
    )

def _main_menu_markup() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "Summary", "callback_data": "menu:summary:0"},
                {"text": "Tasks", "callback_data": "menu:tasks:0"},
            ],
            [
                {"text": "Review", "callback_data": "menu:review:0"},
                {"text": "Backfill", "callback_data": "menu:backfill:0"},
            ],
            [
                {"text": "Health", "callback_data": "menu:health:0"},
                {"text": "Logs", "callback_data": "menu:logs:0"},
            ],
            [
                {"text": "Settings", "callback_data": "menu:settings:0"},
                {"text": "Help", "callback_data": "menu:help:0"},
            ],
        ]
    }
```

Append menu row in `_tasks_reply_markup`.

- [ ] **Step 4: Run bot service tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services -v
```

Expected: all bot service tests pass.

- [ ] **Step 5: Commit help/menu work**

```bash
git add src/telegram_ai_assistant/bot_services.py tests/test_bot_services.py
git commit -m "feat: add bot help menu"
```

## Task 3: Summary Query And Command

**Files:**
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_bot_services.py`

- [ ] **Step 1: Write failing repository test for summary query**

Add to `ItemQueryRepositoryTests`:

```python
def test_list_summary_items_reads_active_items_and_thoughts(self):
    connection = RecordingConnection()
    connection.cursor_obj.fetchall_result = [
        {
            "item_id": "task-1",
            "item_type": "task",
            "title": "Send report",
            "description": "Prepare report",
            "confidence": 0.91,
            "status": "open",
            "rationale": "Owner committed.",
            "due_at": None,
            "source_refs": [{"chat_id": 100, "telegram_message_id": 200}],
            "metadata": {},
        },
        {
            "item_id": "thought-1",
            "item_type": "thought",
            "title": "Consider pricing",
            "description": "Pricing concern.",
            "confidence": 0.82,
            "status": "open",
            "rationale": "Important thought.",
            "due_at": None,
            "source_refs": [],
            "metadata": {},
        },
    ]

    items = ItemQueryRepository(connection, account_id="main").list_summary_items(limit=20)

    sql, params = connection.statements[0]
    normalized_sql = compact_sql(sql).lower()
    self.assertIn("from extracted_items", normalized_sql)
    self.assertIn("account_id = %(account_id)s", normalized_sql)
    self.assertIn("item_type = any", normalized_sql)
    self.assertIn("status = any", normalized_sql)
    self.assertEqual(params["account_id"], "main")
    self.assertEqual(params["limit"], 20)
    self.assertIn("thought", params["item_types"])
    self.assertEqual(items[0].item_id, "task-1")
    self.assertEqual(items[1].item_type, ItemType.THOUGHT)
```

- [ ] **Step 2: Write failing service tests for `/summary`**

Add a fake repository:

```python
class FakeSummaryQueryRepository:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []

    def list_summary_items(self, *, limit):
        self.calls.append(("list_summary_items", limit))
        return self.items[:limit]
```

Add tests:

```python
def test_summary_groups_items_and_includes_navigation_buttons(self):
    query = FakeSummaryQueryRepository(
        [
            make_task(item_id="task-1", item_type=ItemType.TASK, title="Send report"),
            make_task(item_id="commitment-1", item_type=ItemType.COMMITMENT, title="Call Alice"),
            make_task(item_id="wait-1", item_type=ItemType.WAITING_FOR, title="Waiting for invoice"),
            make_task(item_id="thought-1", item_type=ItemType.THOUGHT, title="Pricing concern"),
        ]
    )
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        summary_query_repository=query,
    )

    response = services.summary()

    self.assertEqual(query.calls, [("list_summary_items", 20)])
    self.assertIn("Summary:", response.text)
    self.assertIn("Tasks and commitments:", response.text)
    self.assertIn("Send report", response.text)
    self.assertIn("Waiting:", response.text)
    self.assertIn("Thoughts:", response.text)
    self.assertIn("Pricing concern", response.text)
    self.assertEqual(response.reply_markup["inline_keyboard"][-1], [{"text": "Help", "callback_data": "menu:help:0"}])

def test_summary_returns_empty_message_when_no_items_exist(self):
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        summary_query_repository=FakeSummaryQueryRepository(),
    )

    response = services.summary()

    self.assertEqual(response.text, "No summary items yet.")
    self.assertIsNotNone(response.reply_markup)
```

- [ ] **Step 3: Run focused tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories.ItemQueryRepositoryTests tests.test_bot_services.BotServicesTests -v
```

Expected: fails because `list_summary_items` and implemented `summary()` are missing.

- [ ] **Step 4: Implement `ItemQueryRepository.list_summary_items`**

Add method beside `list_open_tasks`:

```python
def list_summary_items(self, *, limit: int = 20) -> list[ExtractedItem]:
    sql = """
        SELECT
            item_id,
            item_type,
            title,
            description,
            confidence,
            status,
            rationale,
            due_at,
            source_refs,
            metadata
        FROM extracted_items
        WHERE account_id = %(account_id)s
          AND item_type = ANY(%(item_types)s)
          AND status = ANY(%(statuses)s)
        ORDER BY
            due_at ASC NULLS LAST,
            updated_at DESC,
            confidence DESC,
            item_id ASC
        LIMIT %(limit)s
    """
    params = {
        "account_id": self._account_id,
        "item_types": [
            ItemType.TASK.value,
            ItemType.COMMITMENT.value,
            ItemType.REMINDER.value,
            ItemType.WAITING_FOR.value,
            ItemType.THOUGHT.value,
            ItemType.USEFUL_CONTEXT.value,
        ],
        "statuses": [
            ItemStatus.OPEN.value,
            ItemStatus.IN_PROGRESS.value,
            ItemStatus.PARTIALLY_COMPLETED.value,
            ItemStatus.WAITING_FOR.value,
        ],
        "limit": limit,
    }
    return [_item_from_row(row) for row in _fetchall(self._connection, sql, params)]
```

- [ ] **Step 5: Implement `BotServices.summary`**

Update `__init__` to accept `summary_query_repository`. Replace the old summary stub:

```python
def summary(self) -> BotResponse:
    if self.summary_query_repository is None:
        return BotResponse("Summary service is not configured.", _summary_markup())
    items = self.summary_query_repository.list_summary_items(limit=20)
    if not items:
        return BotResponse("No summary items yet.", _summary_markup())
    return BotResponse(_format_summary(items), _summary_markup())
```

Add `_format_summary(items)` and `_summary_markup()` helpers that group by item type:

```python
def _summary_markup() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "Tasks", "callback_data": "menu:tasks:0"},
                {"text": "Review", "callback_data": "menu:review:0"},
            ],
            [
                {"text": "Refresh", "callback_data": "menu:summary:0"},
                {"text": "Help", "callback_data": "menu:help:0"},
            ],
        ]
    }
```

- [ ] **Step 6: Run focused tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories.ItemQueryRepositoryTests tests.test_bot_services.BotServicesTests -v
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit summary work**

```bash
git add src/telegram_ai_assistant/db/repositories.py src/telegram_ai_assistant/bot_services.py tests/test_repositories.py tests/test_bot_services.py
git commit -m "feat: add bot summary command"
```

## Task 4: Review Query And Review Actions

**Files:**
- Modify: `src/telegram_ai_assistant/domain.py`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing repository tests for pending reviews**

Add a domain dataclass:

```python
@dataclass(frozen=True)
class ReviewEntry:
    review_id: int
    review_type: str
    state: str
    reason: str
    payload: dict[str, object]
    created_at: datetime
    item: ExtractedItem | None = None
```

Then add tests to `ReviewRepositoryTests`:

```python
def test_list_pending_reviews_reads_item_and_payload_data(self):
    connection = RecordingConnection()
    created_at = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
    connection.cursor_obj.fetchall_result = [
        {
            "review_id": 7,
            "review_type": "item",
            "state": "pending",
            "reason": "Low confidence.",
            "payload": {"confidence": 0.5},
            "created_at": created_at,
            "item_id": "item-1",
            "item_type": "task",
            "title": "Send report",
            "description": "Prepare report",
            "confidence": 0.5,
            "status": "candidate",
            "rationale": "Maybe a task.",
            "due_at": None,
            "source_refs": [],
            "metadata": {},
        }
    ]

    entries = ReviewRepository(connection, account_id="main").list_pending_reviews(limit=5)

    sql, params = connection.statements[0]
    normalized_sql = compact_sql(sql).lower()
    self.assertIn("from review_queue", normalized_sql)
    self.assertIn("left join extracted_items", normalized_sql)
    self.assertIn("r.state = 'pending'", normalized_sql)
    self.assertEqual(params["account_id"], "main")
    self.assertEqual(params["limit"], 5)
    self.assertEqual(entries[0].review_id, 7)
    self.assertEqual(entries[0].item.item_id, "item-1")
```

- [ ] **Step 2: Write failing repository tests for approve/reject actions**

Add tests:

```python
def test_approve_item_review_activates_item_and_marks_review_approved(self):
    connection = RecordingConnection()
    connection.cursor_obj.fetchone_result = {
        "review_id": 7,
        "review_type": "item",
        "item_id": "item-1",
        "payload": {},
        "reason": "Looks useful.",
    }

    ReviewRepository(connection, account_id="main").approve_review(7)

    statements = [compact_sql(sql).lower() for sql, _ in connection.statements]
    self.assertIn("select review_id", statements[0])
    self.assertIn("update extracted_items", statements[1])
    self.assertIn("update review_queue", statements[2])
    self.assertEqual(connection.statements[1][1]["status"], "open")
    self.assertEqual(connection.statements[2][1]["state"], "approved")

def test_approve_status_change_review_applies_payload_status_and_marks_approved(self):
    connection = RecordingConnection()
    connection.cursor_obj.fetchone_result = {
        "review_id": 8,
        "review_type": "status_change",
        "item_id": "item-1",
        "payload": {"item_id": "item-1", "new_status": "completed", "rationale": "Owner said done."},
        "reason": "Owner said done.",
    }

    ReviewRepository(connection, account_id="main").approve_review(8)

    statements = [compact_sql(sql).lower() for sql, _ in connection.statements]
    self.assertIn("update extracted_items", statements[1])
    self.assertIn("insert into item_status_events", statements[2])
    self.assertIn("update review_queue", statements[3])
    self.assertEqual(connection.statements[1][1]["new_status"], "completed")
    self.assertEqual(connection.statements[3][1]["state"], "approved")

def test_reject_review_marks_review_rejected_without_item_update(self):
    connection = RecordingConnection()

    ReviewRepository(connection, account_id="main").reject_review(9)

    self.assertEqual(len(connection.statements), 1)
    sql, params = connection.statements[0]
    self.assertIn("update review_queue", compact_sql(sql).lower())
    self.assertEqual(params["review_id"], 9)
    self.assertEqual(params["state"], "rejected")
```

- [ ] **Step 3: Run repository tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories.ReviewRepositoryTests -v
```

Expected: fails because `ReviewEntry`, `list_pending_reviews`, `approve_review`, and `reject_review` are missing.

- [ ] **Step 4: Implement `ReviewEntry` and row parsing**

Add `ReviewEntry` to `domain.py`. Import it in `repositories.py`. Add `_review_entry_from_row(row)` that creates an `ExtractedItem` only when `item_id` is present.

- [ ] **Step 5: Implement review query/actions**

Add to `ReviewRepository`:

```python
def list_pending_reviews(self, *, limit: int = 5) -> list[ReviewEntry]:
    ...

def approve_review(self, review_id: int) -> str:
    review = self._get_pending_review_for_update(review_id)
    if review is None:
        return "Review is no longer pending."
    if review["review_type"] == "item":
        self._activate_review_item(review["item_id"])
    elif review["review_type"] == "status_change":
        self._apply_review_status_change(review)
    else:
        return "Unknown review type."
    self._resolve_review(review_id, "approved")
    return "Review approved."

def reject_review(self, review_id: int) -> str:
    self._resolve_review(review_id, "rejected")
    return "Review rejected."
```

Use parameterized SQL, `FOR UPDATE` in `_get_pending_review_for_update`, account guard through joined `extracted_items` where an item exists, and `resolved_at = NOW()` in `_resolve_review`.

- [ ] **Step 6: Run repository tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories.ReviewRepositoryTests -v
```

Expected: all review repository tests pass.

- [ ] **Step 7: Commit review repository work**

```bash
git add src/telegram_ai_assistant/domain.py src/telegram_ai_assistant/db/repositories.py tests/test_repositories.py
git commit -m "feat: add review queue actions"
```

## Task 5: Review Command And Review Callbacks

**Files:**
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Test: `tests/test_bot_services.py`

- [ ] **Step 1: Write failing service tests for review list and actions**

Add fakes:

```python
class FakeReviewRepository:
    def __init__(self, entries=()):
        self.entries = list(entries)
        self.calls = []

    def list_pending_reviews(self, *, limit):
        self.calls.append(("list_pending_reviews", limit))
        return self.entries[:limit]

    def approve_review(self, review_id):
        self.calls.append(("approve_review", review_id))
        return "Review approved."

    def reject_review(self, review_id):
        self.calls.append(("reject_review", review_id))
        return "Review rejected."
```

Add tests:

```python
def test_review_lists_pending_entries_with_action_buttons(self):
    entry = ReviewEntry(
        review_id=7,
        review_type="item",
        state="pending",
        reason="Low confidence.",
        payload={"confidence": 0.5},
        created_at=datetime(2026, 6, 3, 8, 0, tzinfo=UTC),
        item=make_task(item_id="item-1", title="Send report", status=ItemStatus.CANDIDATE),
    )
    repository = FakeReviewRepository([entry])
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        review_repository=repository,
    )

    response = services.review()

    self.assertEqual(repository.calls, [("list_pending_reviews", 5)])
    self.assertIn("Pending reviews:", response.text)
    self.assertIn("#7 item", response.text)
    self.assertIn("Send report", response.text)
    self.assertEqual(
        response.reply_markup["inline_keyboard"][0],
        [
            {"text": "Approve 1", "callback_data": "review:approve:7"},
            {"text": "Reject 1", "callback_data": "review:reject:7"},
        ],
    )

def test_review_returns_empty_message_when_no_entries_exist(self):
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        review_repository=FakeReviewRepository(),
    )

    response = services.review()

    self.assertEqual(response.text, "No pending reviews.")
    self.assertIsNotNone(response.reply_markup)

def test_review_callback_dispatches_approve_and_reject(self):
    repository = FakeReviewRepository()
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        review_repository=repository,
    )

    approve = services.handle_review_callback("approve", "7")
    reject = services.handle_review_callback("reject", "8")

    self.assertEqual(approve, "Review approved.")
    self.assertEqual(reject, "Review rejected.")
    self.assertEqual(repository.calls, [("approve_review", 7), ("reject_review", 8)])
```

- [ ] **Step 2: Run bot service tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services -v
```

Expected: fails because review service behavior is still stubbed.

- [ ] **Step 3: Implement review service behavior**

Update `BotServices.__init__` with `review_repository`. Replace `review()` and `handle_review_callback()`:

```python
def review(self) -> BotResponse:
    if self.review_repository is None:
        return BotResponse("Review service is not configured.", _main_menu_markup())
    entries = self.review_repository.list_pending_reviews(limit=5)
    if not entries:
        return BotResponse("No pending reviews.", _review_empty_markup())
    return BotResponse(_format_review_entries(entries), _review_reply_markup(entries))

def handle_review_callback(self, action: str, target_id: str) -> str:
    if self.review_repository is None:
        return "Review service is not configured."
    try:
        review_id = int(target_id)
    except ValueError:
        return "Invalid review id."
    if action == "approve":
        return str(self.review_repository.approve_review(review_id))
    if action == "reject":
        return str(self.review_repository.reject_review(review_id))
    return "Unknown review action."
```

Add `_format_review_entries`, `_review_reply_markup`, and `_review_empty_markup`.

- [ ] **Step 4: Run bot service tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_bot_services -v
```

Expected: all bot service tests pass.

- [ ] **Step 5: Commit review service work**

```bash
git add src/telegram_ai_assistant/bot_services.py tests/test_bot_services.py
git commit -m "feat: add bot review command"
```

## Task 6: MVP Backfill, Blacklist, And Settings Commands

**Files:**
- Modify: `src/telegram_ai_assistant/domain.py`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Modify: `src/telegram_ai_assistant/bot_services.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_bot_services.py`

- [ ] **Step 1: Write failing tests for backfill job lookup**

Add `BackfillJobSummary` to `domain.py`:

```python
@dataclass(frozen=True)
class BackfillJobSummary:
    backfill_job_id: int
    status: str
    from_date: datetime
    to_date: datetime
    error: str
    created_at: datetime
```

Add repository test:

```python
def test_latest_backfill_jobs_reads_recent_jobs_for_account(self):
    connection = RecordingConnection()
    now = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
    connection.cursor_obj.fetchall_result = [
        {
            "backfill_job_id": 3,
            "status": "completed",
            "from_date": now,
            "to_date": now,
            "error": "",
            "created_at": now,
        }
    ]

    jobs = BackfillJobQueryRepository(connection, account_id="main").latest_jobs(limit=3)

    sql, params = connection.statements[0]
    normalized_sql = compact_sql(sql).lower()
    self.assertIn("from backfill_jobs", normalized_sql)
    self.assertIn("account_id = %(account_id)s", normalized_sql)
    self.assertEqual(params["account_id"], "main")
    self.assertEqual(params["limit"], 3)
    self.assertEqual(jobs[0].backfill_job_id, 3)
```

- [ ] **Step 2: Write failing service tests for MVP commands**

Add fakes:

```python
class FakeBackfillJobQueryRepository:
    def __init__(self, jobs=()):
        self.jobs = list(jobs)
        self.calls = []

    def latest_jobs(self, *, limit):
        self.calls.append(("latest_jobs", limit))
        return self.jobs[:limit]

class FakeSettingsSnapshot:
    telegram_ingest_account_id = "owner"
    telegram_ingest_chat_id = 123
    telegram_listener_allowed_channel_ids = (777,)
    telegram_listener_denied_chat_ids = (888,)
    lm_studio_base_url = "http://host.docker.internal:1234/v1"
    lm_studio_model = "qwen2.5"
    worker_batch_size = 25
    worker_poll_interval_seconds = 10
    worker_item_auto_apply_threshold = 0.8
    worker_status_auto_apply_threshold = 0.8
    log_level = "INFO"
    telegram_data_dir = "/Users/blda/.telegram/telegram_ai_assistant"
```

Add tests:

```python
def test_backfill_shows_presets_and_latest_jobs(self):
    now = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)
    jobs = FakeBackfillJobQueryRepository(
        [BackfillJobSummary(3, "completed", now, now, "", now)]
    )
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        backfill_job_query_repository=jobs,
    )

    response = services.backfill()

    self.assertEqual(jobs.calls, [("latest_jobs", 3)])
    self.assertIn("Backfill:", response.text)
    self.assertIn("Last jobs:", response.text)
    self.assertEqual(response.reply_markup["inline_keyboard"][0][0]["callback_data"], "backfill:30d:0")

def test_blacklist_shows_listener_policy_from_settings_snapshot(self):
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        settings_snapshot=FakeSettingsSnapshot(),
    )

    response = services.blacklist()

    self.assertIn("Listener policy:", response.text)
    self.assertIn("allowed_channel_ids=777", response.text)
    self.assertIn("denied_chat_ids=888", response.text)
    self.assertNotIn("api_hash", response.text.lower())

def test_settings_shows_allowlisted_non_secret_values(self):
    services = BotServices(
        runtime_event_repository=FakeRuntimeEventRepository(),
        settings_snapshot=FakeSettingsSnapshot(),
    )

    response = services.settings()

    self.assertIn("Settings:", response.text)
    self.assertIn("account_id=owner", response.text)
    self.assertIn("lm_studio_model=qwen2.5", response.text)
    self.assertNotIn("token", response.text.lower())
    self.assertNotIn("api_hash", response.text.lower())
    self.assertNotIn("database_url", response.text.lower())

def test_backfill_callbacks_return_safe_mvp_responses(self):
    services = BotServices(runtime_event_repository=FakeRuntimeEventRepository())

    self.assertIn("30 days", services.handle_backfill_callback("30d", "0"))
    self.assertIn("90 days", services.handle_backfill_callback("90d", "0"))
    self.assertIn("Backfill", services.handle_backfill_callback("status", "0"))
```

- [ ] **Step 3: Run focused tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories tests.test_bot_services -v
```

Expected: fails because backfill query, settings rendering, blacklist rendering, and backfill callbacks are missing.

- [ ] **Step 4: Implement backfill job query**

Import `BackfillJobSummary` and add `BackfillJobQueryRepository.latest_jobs(limit=3)` using:

```sql
SELECT backfill_job_id, status, from_date, to_date, error, created_at
FROM backfill_jobs
WHERE account_id = %(account_id)s
ORDER BY created_at DESC, backfill_job_id DESC
LIMIT %(limit)s
```

- [ ] **Step 5: Implement MVP command renderers**

Update `BotServices.__init__` with `backfill_job_query_repository` and `settings_snapshot`.

Implement:

```python
def backfill(self) -> BotResponse:
    jobs = self.backfill_job_query_repository.latest_jobs(limit=3) if self.backfill_job_query_repository else []
    return BotResponse(_format_backfill(jobs), _backfill_markup())

def blacklist(self) -> BotResponse:
    if self.settings_snapshot is None:
        return BotResponse("Settings service is not configured.", _main_menu_markup())
    return BotResponse(_format_blacklist(self.settings_snapshot), _main_menu_markup())

def settings(self) -> BotResponse:
    if self.settings_snapshot is None:
        return BotResponse("Settings service is not configured.", _main_menu_markup())
    return BotResponse(_format_settings(self.settings_snapshot), _settings_markup())

def handle_backfill_callback(self, action: str, target_id: str) -> str:
    if action == "30d":
        return "Backfill preset selected: last 30 days. Run the CLI backfill command with this bounded window."
    if action == "90d":
        return "Backfill preset selected: last 90 days. Run the CLI backfill command with this bounded window."
    if action == "status":
        return "Backfill status is available from /backfill."
    return "Unknown backfill action."
```

Keep output allowlisted and do not render bot token, API hash, database URL, or Telegram session path contents.

- [ ] **Step 6: Run focused tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_repositories tests.test_bot_services -v
```

Expected: focused repository and service tests pass.

- [ ] **Step 7: Commit MVP command work**

```bash
git add src/telegram_ai_assistant/domain.py src/telegram_ai_assistant/db/repositories.py src/telegram_ai_assistant/bot_services.py tests/test_repositories.py tests/test_bot_services.py
git commit -m "feat: add bot mvp operations commands"
```

## Task 7: Production Wiring, Schema Assertions, And Docs

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `tests/test_app_context.py`
- Modify: `tests/test_db_schema.py`
- Modify: `tests/test_operations_docs.py`
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing app context test for new bot dependencies**

Update `test_run_bot_forever_builds_owner_only_runtime` in `tests/test_app_context.py` so the fake `BotServices` constructor records:

```python
"summary_query_repository",
"review_repository",
"backfill_job_query_repository",
"settings_snapshot",
```

Assert those dependencies are not `None` and that `settings_snapshot.lm_studio_model` equals the configured model.

- [ ] **Step 2: Write schema/docs tests**

In `tests/test_db_schema.py`, extend the review queue test to assert:

```python
"state text not null default 'pending'"
"resolved_at timestamptz"
```

In `tests/test_operations_docs.py`, assert runbook includes:

```python
self.assertIn("/start", text)
self.assertIn("/help", text)
self.assertIn("/summary", text)
self.assertIn("/review", text)
self.assertIn("/blacklist", text)
self.assertIn("/settings", text)
```

- [ ] **Step 3: Run wiring/docs tests and verify they fail**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context tests.test_db_schema tests.test_operations_docs -v
```

Expected: fails because `AppContext` does not pass new dependencies and docs do not list all commands.

- [ ] **Step 4: Wire repositories and settings snapshot**

In `app_context.py`, import `BackfillJobQueryRepository`. Pass to `BotServices`:

```python
summary_query_repository=ItemQueryRepository(
    connection,
    account_id=self.settings.telegram_ingest_account_id,
),
review_repository=ReviewRepository(
    connection,
    account_id=self.settings.telegram_ingest_account_id,
),
backfill_job_query_repository=BackfillJobQueryRepository(
    connection,
    account_id=self.settings.telegram_ingest_account_id,
),
settings_snapshot=self.settings,
```

Reuse the same `ItemQueryRepository` instance for `item_query_repository` and `summary_query_repository` if desired.

- [ ] **Step 5: Update runbook and changelog**

In `docs/operations/local-runbook.md`, replace the bot command section with implemented commands:

```markdown
Implemented production commands:

- `/start` and `/help` show the command list and inline menu.
- `/summary` shows a structured summary from stored extracted items.
- `/review` lists pending low-confidence reviews and supports approve/reject callbacks.
- `/tasks` lists open task-like items and includes inline status buttons.
- `/logs` shows sanitized warning/error runtime events.
- `/health` shows Postgres and LM Studio health.

Implemented MVP operational commands:

- `/backfill` shows bounded backfill presets and latest job status.
- `/blacklist` shows listener allow/deny policy and env-based change instructions.
- `/settings` shows non-secret runtime settings.
```

In `CHANGELOG.md`, add:

```markdown
- Added bot command suite with `/start`, `/help`, `/summary`, `/review`, `/backfill`, `/blacklist`, `/settings`, and inline menu actions.
```

- [ ] **Step 6: Run wiring/docs tests and verify they pass**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest tests.test_app_context tests.test_db_schema tests.test_operations_docs -v
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit wiring/docs work**

```bash
git add src/telegram_ai_assistant/app_context.py tests/test_app_context.py tests/test_db_schema.py tests/test_operations_docs.py docs/operations/local-runbook.md CHANGELOG.md
git commit -m "chore: wire bot command suite"
```

## Task 8: Final Verification And Docker Restart

**Files:**
- No new source files unless previous tasks uncovered a small compatibility fix.

- [ ] **Step 1: Run full test suite**

Run:

```bash
PYTHONPATH=src /Users/blda/projects/telegram_ai_assistant/.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run whitespace and compose checks**

Run:

```bash
git diff --check
docker compose config --quiet
```

Expected: no output and exit code 0.

- [ ] **Step 3: Apply migration idempotently**

Run:

```bash
docker compose exec -T app-worker telegram-ai-assistant migrate
```

Expected: `migration applied`.

- [ ] **Step 4: Rebuild and restart bot runtime without deleting database**

Run:

```bash
docker compose up -d --build app-listener app-worker app-bot
docker compose ps
```

Expected: Postgres remains healthy; `app-listener`, `app-worker`, and `app-bot` are up. Do not run `docker compose down -v`.

- [ ] **Step 5: Check bot health command path indirectly**

Run:

```bash
docker compose exec -T app-worker telegram-ai-assistant health
```

Expected: JSON health report. LM Studio can still be degraded if no model is loaded, but the command must not expose secrets.

- [ ] **Step 6: Final git status**

Run:

```bash
git status --short --branch
git log --oneline -8
```

Expected: branch `codex/bot-command-suite` is clean and contains the task commits.
