# Live Telegram Ingestor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first live one-shot Telegram ingestor that reads new messages from one configured chat through the read-only adapter, persists them to Postgres, advances a cursor stored on `chats`, and exits.

**Architecture:** Keep live Telegram access behind `TelethonIngestionAdapter` and the existing `ReadOnlyIngestionClient` port. Store cursor state in Postgres through repository methods, then add a small async ingestion service that coordinates client iteration, normalization, message upsert, and cursor update inside the existing connection factory transaction boundary.

**Tech Stack:** Python 3.11, `unittest`, `asyncio`, `psycopg` v3 for Postgres, Telethon for live MTProto access, project-local `.venv`, TDD with fakes for all automated tests.

---

## File Structure

- Modify `src/telegram_ai_assistant/config.py`: add live ingestor settings to `Settings`.
- Modify `tests/test_config.py`: cover required live ingestor settings and optional limit default.
- Modify `pyproject.toml`: declare `telethon>=1.36`.
- Modify `tests/test_project_metadata.py`: assert Telethon dependency is declared.
- Modify `src/telegram_ai_assistant/db/schema.sql`: add cursor columns to `chats`.
- Modify `tests/test_db_schema.py`: assert cursor columns exist.
- Modify `src/telegram_ai_assistant/db/repositories.py`: add `AccountRepository` and `ChatRepository`.
- Modify `tests/test_repositories.py`: cover account/chat ensure methods and cursor read/update/error SQL.
- Create `src/telegram_ai_assistant/ingestion/live.py`: async one-shot ingestion service and result dataclass.
- Create `tests/test_live_ingestor.py`: service behavior with fake client, connection, repositories, and messages.
- Modify `src/telegram_ai_assistant/app_context.py`: build and run the live ingestor without opening connections during construction.
- Modify `src/telegram_ai_assistant/runtime.py`: wire `run_ingestor(settings)` to one-shot ingestion and sanitized output.
- Modify `src/telegram_ai_assistant/cli.py`: allow tests to inject run command runners while preserving production defaults.
- Modify `tests/test_app_context.py`, `tests/test_runtime.py`, and `tests/test_cli.py`: cover live ingestor wiring.
- Modify `docs/operations/local-runbook.md`: document new env vars and one-shot command.
- Modify `docs/operations/manual-unread-smoke-test.md`: update exact smoke workflow.
- Modify `CHANGELOG.md`: add live ingestor entry.

## Parallel Work Boundaries

After the worktree and baseline suite are green, these independent scopes can run in parallel:

- Settings/dependency scope: `config.py`, `tests/test_config.py`, `pyproject.toml`, `tests/test_project_metadata.py`.
- Database cursor/repository scope: `db/schema.sql`, `db/repositories.py`, `tests/test_db_schema.py`, `tests/test_repositories.py`.

The coordinating agent owns `ingestion/live.py`, app context, runtime, CLI, docs, changelog, final verification, and integration. Agents must not edit files outside their assigned scope and must not revert unrelated changes.

## Task 1: Live Ingestor Settings And Telethon Dependency

**Files:**
- Modify: `src/telegram_ai_assistant/config.py`
- Modify: `tests/test_config.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_project_metadata.py`

- [ ] **Step 1: Write failing settings tests**

Update `tests/test_config.py` so `VALID_ENV` includes:

```python
    "TELEGRAM_SESSION_PATH": ".local/telegram-owner.session",
    "TELEGRAM_INGEST_ACCOUNT_ID": "owner",
    "TELEGRAM_INGEST_CHAT_ID": "1001",
```

Add assertions to `test_loads_required_settings_and_defaults`:

```python
self.assertEqual(settings.telegram_session_path, ".local/telegram-owner.session")
self.assertEqual(settings.telegram_ingest_account_id, "owner")
self.assertEqual(settings.telegram_ingest_chat_id, 1001)
self.assertEqual(settings.telegram_ingest_limit, 100)
```

Extend `test_loads_optional_lm_studio_and_backfill_values` with:

```python
"TELEGRAM_INGEST_LIMIT": "25",
```

and assert:

```python
self.assertEqual(settings.telegram_ingest_limit, 25)
```

Add a required-setting case:

```python
def test_raises_when_ingestor_setting_is_missing(self):
    env = dict(VALID_ENV)
    del env["TELEGRAM_SESSION_PATH"]

    with self.assertRaises(ConfigError):
        Settings.from_env(env)
```

- [ ] **Step 2: Verify settings RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v
```

Expected: FAIL because `Settings` lacks `telegram_session_path`, `telegram_ingest_account_id`, `telegram_ingest_chat_id`, and `telegram_ingest_limit`.

- [ ] **Step 3: Implement settings**

Modify `Settings` in `src/telegram_ai_assistant/config.py` to include:

```python
telegram_session_path: str
telegram_ingest_account_id: str
telegram_ingest_chat_id: int
telegram_ingest_limit: int = 100
```

Update `Settings.from_env` with:

```python
telegram_session_path=_required(env, "TELEGRAM_SESSION_PATH"),
telegram_ingest_account_id=_required(env, "TELEGRAM_INGEST_ACCOUNT_ID"),
telegram_ingest_chat_id=_required_int(env, "TELEGRAM_INGEST_CHAT_ID"),
telegram_ingest_limit=_optional_int(env, "TELEGRAM_INGEST_LIMIT", cls.telegram_ingest_limit),
```

- [ ] **Step 4: Verify settings GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v
```

Expected: PASS.

- [ ] **Step 5: Write failing dependency test**

Update `tests/test_project_metadata.py`:

```python
def test_declares_telethon_dependency(self):
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    self.assertIn("telethon>=1.36", dependencies)
```

- [ ] **Step 6: Verify dependency RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_project_metadata -v
```

Expected: FAIL because `telethon>=1.36` is not declared.

- [ ] **Step 7: Declare dependency**

Modify `pyproject.toml` dependencies:

```toml
dependencies = [
    "psycopg[binary]>=3.2",
    "telethon>=1.36",
]
```

- [ ] **Step 8: Verify dependency GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config tests.test_project_metadata -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add pyproject.toml src/telegram_ai_assistant/config.py tests/test_config.py tests/test_project_metadata.py
git commit -m "feat: add live ingestor settings"
```

## Task 2: Chat Cursor Schema And Repositories

**Files:**
- Modify: `src/telegram_ai_assistant/db/schema.sql`
- Modify: `src/telegram_ai_assistant/db/repositories.py`
- Modify: `tests/test_db_schema.py`
- Modify: `tests/test_repositories.py`

- [ ] **Step 1: Write failing schema test**

Add to `tests/test_db_schema.py`:

```python
def test_chats_store_ingestion_cursor_state(self):
    self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
    schema = re.sub(
        r"\s+",
        " ",
        SCHEMA_PATH.read_text(encoding="utf-8").lower(),
    )

    self.assertIn("last_ingested_message_id bigint not null default 0", schema)
    self.assertIn("last_ingested_at timestamptz", schema)
    self.assertIn("ingestion_error text not null default ''", schema)
```

- [ ] **Step 2: Verify schema RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema -v
```

Expected: FAIL because `chats` lacks cursor columns.

- [ ] **Step 3: Implement schema columns**

Modify the `chats` table in `src/telegram_ai_assistant/db/schema.sql`:

```sql
    last_ingested_message_id BIGINT NOT NULL DEFAULT 0,
    last_ingested_at TIMESTAMPTZ,
    ingestion_error TEXT NOT NULL DEFAULT '',
```

Place these columns before `created_at`.

- [ ] **Step 4: Verify schema GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema -v
```

Expected: PASS.

- [ ] **Step 5: Write failing repository tests**

Extend `tests/test_repositories.py` with a cursor-capable fake:

```python
class FetchingCursor(RecordingCursor):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def fetchone(self):
        return self.row


class FetchingConnection(RecordingConnection):
    def __init__(self, row):
        self.cursor_obj = FetchingCursor(row)
```

Add tests:

```python
class AccountRepositoryTests(unittest.TestCase):
    def test_ensure_account_upserts_account(self):
        connection = RecordingConnection()

        AccountRepository(connection).ensure_account(
            account_id="owner",
            telegram_user_id=123,
            display_name="Owner",
        )

        sql, params = connection.statements[0]
        self.assertIn("insert into accounts", compact_sql(sql).lower())
        self.assertIn("on conflict (account_id)", compact_sql(sql).lower())
        self.assertEqual(params["account_id"], "owner")
        self.assertEqual(params["telegram_user_id"], 123)
        self.assertEqual(params["display_name"], "Owner")


class ChatRepositoryTests(unittest.TestCase):
    def test_ensure_chat_upserts_chat_without_moving_cursor(self):
        connection = RecordingConnection()

        ChatRepository(connection).ensure_chat(
            account_id="owner",
            chat_id=1001,
            title="Smoke",
            chat_type="private",
        )

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("insert into chats", normalized_sql)
        self.assertIn("on conflict (account_id, chat_id)", normalized_sql)
        self.assertNotIn("last_ingested_message_id = excluded.last_ingested_message_id", normalized_sql)
        self.assertEqual(params["account_id"], "owner")
        self.assertEqual(params["chat_id"], 1001)

    def test_get_last_ingested_message_id_returns_zero_when_chat_has_no_cursor(self):
        connection = FetchingConnection((None,))

        cursor = ChatRepository(connection).get_last_ingested_message_id("owner", 1001)

        self.assertEqual(cursor, 0)
        self.assertIn("select last_ingested_message_id", compact_sql(connection.statements[0][0]).lower())

    def test_update_ingestion_cursor_writes_last_message_id_and_timestamp(self):
        connection = RecordingConnection()
        ingested_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)

        ChatRepository(connection).update_ingestion_cursor("owner", 1001, 205, ingested_at)

        sql, params = connection.statements[0]
        normalized_sql = compact_sql(sql).lower()
        self.assertIn("update chats", normalized_sql)
        self.assertIn("last_ingested_message_id = %(last_ingested_message_id)s", normalized_sql)
        self.assertEqual(params["last_ingested_message_id"], 205)
        self.assertEqual(params["last_ingested_at"], ingested_at)

    def test_record_ingestion_error_stores_sanitized_error_type(self):
        connection = RecordingConnection()

        ChatRepository(connection).record_ingestion_error("owner", 1001, "telegram_error")

        sql, params = connection.statements[0]
        self.assertIn("ingestion_error", compact_sql(sql).lower())
        self.assertEqual(params["ingestion_error"], "telegram_error")
```

Update imports:

```python
from telegram_ai_assistant.db.repositories import (
    AccountRepository,
    CandidateRepository,
    ChatRepository,
    MessageRepository,
)
```

- [ ] **Step 6: Verify repository RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_repositories -v
```

Expected: FAIL because `AccountRepository` and `ChatRepository` do not exist.

- [ ] **Step 7: Implement repositories**

Add to `src/telegram_ai_assistant/db/repositories.py`:

```python
def _fetchone(connection: Connection, sql: str, params: object | None = None) -> object | None:
    cursor = connection.cursor()
    if hasattr(cursor, "__enter__"):
        with cursor as active_cursor:
            active_cursor.execute(sql, params)
            return active_cursor.fetchone()
    cursor.execute(sql, params)
    return cursor.fetchone()


class AccountRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def ensure_account(
        self,
        account_id: str,
        telegram_user_id: int | None = None,
        display_name: str = "",
    ) -> None:
        sql = """
            INSERT INTO accounts (account_id, telegram_user_id, display_name)
            VALUES (%(account_id)s, %(telegram_user_id)s, %(display_name)s)
            ON CONFLICT (account_id)
            DO UPDATE SET
                telegram_user_id = COALESCE(EXCLUDED.telegram_user_id, accounts.telegram_user_id),
                display_name = EXCLUDED.display_name
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": account_id,
                "telegram_user_id": telegram_user_id,
                "display_name": display_name,
            },
        )
```

Add:

```python
class ChatRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def ensure_chat(
        self,
        account_id: str,
        chat_id: int,
        title: str = "",
        chat_type: str = "",
    ) -> None:
        sql = """
            INSERT INTO chats (account_id, chat_id, title, chat_type)
            VALUES (%(account_id)s, %(chat_id)s, %(title)s, %(chat_type)s)
            ON CONFLICT (account_id, chat_id)
            DO UPDATE SET
                title = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                updated_at = NOW()
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": account_id,
                "chat_id": chat_id,
                "title": title,
                "chat_type": chat_type,
            },
        )

    def get_last_ingested_message_id(self, account_id: str, chat_id: int) -> int:
        sql = """
            SELECT last_ingested_message_id
            FROM chats
            WHERE account_id = %(account_id)s AND chat_id = %(chat_id)s
        """
        row = _fetchone(self._connection, sql, {"account_id": account_id, "chat_id": chat_id})
        if not row or row[0] is None:
            return 0
        return int(row[0])

    def update_ingestion_cursor(
        self,
        account_id: str,
        chat_id: int,
        last_ingested_message_id: int,
        last_ingested_at,
    ) -> None:
        sql = """
            UPDATE chats
            SET
                last_ingested_message_id = %(last_ingested_message_id)s,
                last_ingested_at = %(last_ingested_at)s,
                ingestion_error = '',
                updated_at = NOW()
            WHERE account_id = %(account_id)s AND chat_id = %(chat_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": account_id,
                "chat_id": chat_id,
                "last_ingested_message_id": last_ingested_message_id,
                "last_ingested_at": last_ingested_at,
            },
        )

    def record_ingestion_error(self, account_id: str, chat_id: int, error_type: str) -> None:
        sql = """
            UPDATE chats
            SET ingestion_error = %(ingestion_error)s, updated_at = NOW()
            WHERE account_id = %(account_id)s AND chat_id = %(chat_id)s
        """
        _execute(
            self._connection,
            sql,
            {
                "account_id": account_id,
                "chat_id": chat_id,
                "ingestion_error": error_type,
            },
        )
```

- [ ] **Step 8: Verify repository GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_schema tests.test_repositories -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add src/telegram_ai_assistant/db/schema.sql src/telegram_ai_assistant/db/repositories.py tests/test_db_schema.py tests/test_repositories.py
git commit -m "feat: add chat ingestion cursor repositories"
```

## Task 3: One-Shot Ingestion Service

**Files:**
- Create: `src/telegram_ai_assistant/ingestion/live.py`
- Create: `tests/test_live_ingestor.py`

- [ ] **Step 1: Write failing happy-path service test**

Create `tests/test_live_ingestor.py` with fake raw messages, fake repositories, fake connection factory, and fake read-only client. The key test should:

```python
result = asyncio.run(ingestor.run_once())

self.assertEqual(client.calls, [("iter_new_messages", 1001, 200, 10), ("close",)])
self.assertEqual(message_repository.messages, [normalized_first, normalized_second])
self.assertEqual(chat_repository.updated_cursor, 202)
self.assertEqual(result.saved_count, 2)
self.assertEqual(result.latest_message_id, 202)
```

Use raw message ids `201` and `202`; configure the fake chat repository cursor as `200`; configure `limit=10`.

- [ ] **Step 2: Verify service RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_ingestor -v
```

Expected: FAIL because `telegram_ai_assistant.ingestion.live` does not exist.

- [ ] **Step 3: Implement result dataclass and service constructor**

Create `src/telegram_ai_assistant/ingestion/live.py` with:

```python
from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telegram_ai_assistant.db.repositories import AccountRepository, ChatRepository, MessageRepository
from telegram_ai_assistant.ingestion.normalizer import normalize_telegram_message
from telegram_ai_assistant.ingestion.ports import IngestionClient


@dataclass(frozen=True)
class IngestionRunResult:
    account_id: str
    chat_id: int
    requested_min_id: int
    saved_count: int
    latest_message_id: int


class LiveIngestor:
    def __init__(
        self,
        *,
        account_id: str,
        chat_id: int,
        limit: int,
        connection_factory: Any,
        client_factory: Callable[[], Any],
        normalizer: Callable[[str, object], Any] = normalize_telegram_message,
        account_repository_factory: Callable[[Any], Any] = AccountRepository,
        chat_repository_factory: Callable[[Any], Any] = ChatRepository,
        message_repository_factory: Callable[[Any], Any] = MessageRepository,
        now: Callable[[], datetime] | None = None,
    ):
        self.account_id = account_id
        self.chat_id = chat_id
        self.limit = limit
        self.connection_factory = connection_factory
        self.client_factory = client_factory
        self.normalizer = normalizer
        self.account_repository_factory = account_repository_factory
        self.chat_repository_factory = chat_repository_factory
        self.message_repository_factory = message_repository_factory
        self.now = now or (lambda: datetime.now(UTC))
```

- [ ] **Step 4: Implement `run_once`**

Add to `LiveIngestor`:

```python
async def run_once(self) -> IngestionRunResult:
    client = None
    with self.connection_factory.connection() as connection:
        account_repository = self.account_repository_factory(connection)
        chat_repository = self.chat_repository_factory(connection)
        message_repository = self.message_repository_factory(connection)

        account_repository.ensure_account(self.account_id)
        chat_repository.ensure_chat(self.account_id, self.chat_id)
        requested_min_id = chat_repository.get_last_ingested_message_id(self.account_id, self.chat_id)

        client = await _resolve_client(self.client_factory())
        saved_count = 0
        latest_message_id = requested_min_id
        try:
            async for raw_message in client.iter_new_messages(
                self.chat_id,
                min_id=requested_min_id,
                limit=self.limit,
            ):
                message = self.normalizer(self.account_id, raw_message)
                message_repository.upsert_message(message)
                saved_count += 1
                latest_message_id = max(latest_message_id, message.telegram_message_id)
        finally:
            await client.close()

        if saved_count:
            chat_repository.update_ingestion_cursor(
                self.account_id,
                self.chat_id,
                latest_message_id,
                self.now(),
            )

        return IngestionRunResult(
            account_id=self.account_id,
            chat_id=self.chat_id,
            requested_min_id=requested_min_id,
            saved_count=saved_count,
            latest_message_id=latest_message_id,
        )


async def _resolve_client(value: Any) -> IngestionClient:
    if inspect.isawaitable(value):
        return await value
    return value
```

- [ ] **Step 5: Verify happy-path GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_ingestor -v
```

Expected: PASS for the happy path.

- [ ] **Step 6: Write failing no-message and failure tests**

Add tests:

```python
def test_run_once_does_not_move_cursor_when_no_messages_are_saved(self):
    client = FakeIngestionClient(messages=[])
    chat_repository = FakeChatRepository(cursor=200)
    ingestor = make_ingestor(client=client, chat_repository=chat_repository)

    result = asyncio.run(ingestor.run_once())

    self.assertEqual(client.calls, [("iter_new_messages", 1001, 200, 10), ("close",)])
    self.assertIsNone(chat_repository.updated_cursor)
    self.assertEqual(result.saved_count, 0)
    self.assertEqual(result.latest_message_id, 200)

def test_run_once_closes_client_and_leaves_cursor_unchanged_when_normalization_fails(self):
    client = FakeIngestionClient(messages=[make_raw_message(201)])
    chat_repository = FakeChatRepository(cursor=200)
    ingestor = make_ingestor(
        client=client,
        chat_repository=chat_repository,
        normalizer=lambda account_id, raw_message: (_ for _ in ()).throw(ValueError("bad raw message")),
    )

    with self.assertRaises(ValueError):
        asyncio.run(ingestor.run_once())
    self.assertIn(("close",), client.calls)
    self.assertIsNone(chat_repository.updated_cursor)
```

- [ ] **Step 7: Verify failure behavior GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_ingestor -v
```

Expected: PASS.

- [ ] **Step 8: Commit service**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_ingestor -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add src/telegram_ai_assistant/ingestion/live.py tests/test_live_ingestor.py
git commit -m "feat: add one-shot live ingestor service"
```

## Task 4: AppContext, Runtime, And CLI Wiring

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `src/telegram_ai_assistant/cli.py`
- Modify: `tests/test_app_context.py`
- Modify: `tests/test_runtime.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing AppContext test**

Add to `tests/test_app_context.py`:

```python
def test_run_ingestor_once_builds_service_with_settings(self):
    factory = FakeConnectionFactory()
    captured = {}

    class FakeIngestor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run_once(self):
            return "result"

    context = AppContext(
        settings=make_settings(),
        connection_factory=factory,
        ingestor_factory=FakeIngestor,
        telegram_client_factory=lambda settings: "client-factory",
    )

    result = asyncio.run(context.run_ingestor_once())

    self.assertEqual(result, "result")
    self.assertEqual(captured["account_id"], "owner")
    self.assertEqual(captured["chat_id"], 1001)
    self.assertEqual(captured["limit"], 100)
    self.assertIs(captured["connection_factory"], factory)
    self.assertEqual(captured["client_factory"], "client-factory")
```

Update `make_settings()` in the same file to include live ingestor fields.

- [ ] **Step 2: Verify AppContext RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context -v
```

Expected: FAIL because `AppContext` lacks `ingestor_factory`, `telegram_client_factory`, and `run_ingestor_once`.

- [ ] **Step 3: Implement AppContext wiring**

Modify `AppContext` fields:

```python
ingestor_factory: Any = LiveIngestor
telegram_client_factory: Callable[[Settings], Any] = default_telegram_client_factory
```

Add:

```python
def default_telegram_client_factory(settings: Settings):
    return lambda: TelethonIngestionAdapter.connect(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
```

Add method:

```python
async def run_ingestor_once(self):
    ingestor = self.ingestor_factory(
        account_id=self.settings.telegram_ingest_account_id,
        chat_id=self.settings.telegram_ingest_chat_id,
        limit=self.settings.telegram_ingest_limit,
        connection_factory=self.connection_factory,
        client_factory=self.telegram_client_factory(self.settings),
    )
    return await ingestor.run_once()
```

- [ ] **Step 4: Verify AppContext GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context -v
```

Expected: PASS.

- [ ] **Step 5: Write failing runtime tests**

Update `tests/test_runtime.py` with live settings in every direct `Settings` construction. Add:

```python
def test_run_ingestor_executes_context_and_prints_result(self):
    calls = []

    class FakeContext:
        async def run_ingestor_once(self):
            calls.append("run")
            return IngestionRunResult(
                account_id="owner",
                chat_id=1001,
                requested_min_id=200,
                saved_count=2,
                latest_message_id=202,
            )

    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FakeContext())

    self.assertEqual(exit_code, 0)
    self.assertEqual(calls, ["run"])
    self.assertIn('"saved_count": 2', output.getvalue())
```

Add failure test:

```python
def test_run_ingestor_failure_returns_nonzero_without_secret_values(self):
    class FailingContext:
        async def run_ingestor_once(self):
            raise RuntimeError("failed with secret-token")

    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = run_ingestor(make_settings(), context_factory=lambda settings: FailingContext())

    self.assertEqual(exit_code, 1)
    self.assertIn("ingestor failed", output.getvalue())
    self.assertNotIn("secret-token", output.getvalue())
```

- [ ] **Step 6: Verify runtime RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_runtime -v
```

Expected: FAIL because `run_ingestor` does not accept `context_factory` and does not run the context.

- [ ] **Step 7: Implement runtime**

Modify `src/telegram_ai_assistant/runtime.py`:

```python
import asyncio
import json
from typing import Any

from .app_context import AppContext
from .ingestion.live import IngestionRunResult
```

Change `run_ingestor`:

```python
def run_ingestor(settings: Settings, *, context_factory=AppContext.from_settings) -> int:
    try:
        result = asyncio.run(context_factory(settings).run_ingestor_once())
    except Exception as exc:
        print(f"ingestor failed: {type(exc).__name__}")
        return 1
    print(json.dumps(_ingestion_result_payload(result), sort_keys=True))
    return 0
```

Add:

```python
def _ingestion_result_payload(result: IngestionRunResult) -> dict[str, Any]:
    return {
        "account_id": result.account_id,
        "chat_id": result.chat_id,
        "requested_min_id": result.requested_min_id,
        "saved_count": result.saved_count,
        "latest_message_id": result.latest_message_id,
    }
```

Add `AppContext.from_settings(settings)` in `app_context.py`:

```python
@classmethod
def from_settings(cls, settings: Settings) -> "AppContext":
    return cls(
        settings=settings,
        connection_factory=PostgresConnectionFactory(settings.database_url),
    )
```

- [ ] **Step 8: Verify runtime GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime -v
```

Expected: PASS.

- [ ] **Step 9: Write failing CLI injection test**

Update `tests/test_cli.py`:

```python
def test_run_command_accepts_injected_runner(self):
    calls = []

    def runner(settings):
        calls.append(settings.telegram_ingest_chat_id)
        return 9

    exit_code = main(
        ["run", "ingestor"],
        environ=VALID_ENV,
        runners={"ingestor": runner},
    )

    self.assertEqual(exit_code, 9)
    self.assertEqual(calls, [1001])
```

Import `VALID_ENV` from `tests.test_config` or duplicate the full environment mapping in `tests/test_cli.py`.

- [ ] **Step 10: Verify CLI RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_cli -v
```

Expected: FAIL because `main()` does not accept `runners`.

- [ ] **Step 11: Implement CLI runner injection**

Modify `src/telegram_ai_assistant/cli.py` `main` signature:

```python
runners: Mapping[str, Callable[[Settings], int]] | None = None,
```

Change run branch:

```python
if args.command == "run":
    environment = load_environment(env_file, os.environ if environ is None else environ)
    return run_process(args.process, Settings.from_env(environment), runners=runners)
```

- [ ] **Step 12: Verify wiring GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime tests.test_cli -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add src/telegram_ai_assistant/app_context.py src/telegram_ai_assistant/runtime.py src/telegram_ai_assistant/cli.py tests/test_app_context.py tests/test_runtime.py tests/test_cli.py
git commit -m "feat: wire live ingestor runtime"
```

## Task 5: Operations Documentation And Changelog

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `docs/operations/manual-unread-smoke-test.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_operations_docs.py`

- [ ] **Step 1: Write failing operations doc tests**

Update `tests/test_operations_docs.py` with assertions that:

```python
self.assertIn("TELEGRAM_SESSION_PATH", runbook)
self.assertIn("TELEGRAM_INGEST_CHAT_ID", runbook)
self.assertIn("telegram-ai-assistant run ingestor", runbook)
self.assertIn("last_ingested_message_id", smoke_test)
self.assertIn("telegram-ai-assistant run ingestor", smoke_test)
```

- [ ] **Step 2: Verify docs RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_operations_docs -v
```

Expected: FAIL because docs do not mention live ingestor variables and cursor verification.

- [ ] **Step 3: Update runbook**

Add `.env` variables:

```bash
TELEGRAM_SESSION_PATH=.local/telegram-owner.session
TELEGRAM_INGEST_ACCOUNT_ID=owner
TELEGRAM_INGEST_CHAT_ID=123456789
TELEGRAM_INGEST_LIMIT=100
```

Add command:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run ingestor
```

Document that this command is one-shot, single-chat, and should be used only with a controlled chat until the manual unread smoke test passes.

- [ ] **Step 4: Update manual unread smoke test**

Add steps to confirm persistence and cursor:

```sql
SELECT chat_id, telegram_message_id, text, caption
FROM messages
WHERE account_id = 'owner' AND chat_id = 123456789
ORDER BY telegram_message_id DESC
LIMIT 5;

SELECT last_ingested_message_id
FROM chats
WHERE account_id = 'owner' AND chat_id = 123456789;
```

Keep the existing unread badge pass criteria.

- [ ] **Step 5: Update changelog**

Add under `## Unreleased`:

```markdown
- Added one-shot live Telegram ingestor with chat cursor persistence.
```

- [ ] **Step 6: Verify docs GREEN and commit**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_operations_docs -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Commit:

```bash
git add CHANGELOG.md docs/operations/local-runbook.md docs/operations/manual-unread-smoke-test.md tests/test_operations_docs.py
git commit -m "docs: document live Telegram ingestor"
```

## Task 6: Final Verification

**Files:**
- No production edits unless verification exposes a bug.

- [ ] **Step 1: Run full automated suite**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI smoke checks**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli version
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli health --offline
```

Expected: version prints `0.1.0`; offline health prints JSON with `"status": "ok"`.

- [ ] **Step 3: Inspect branch status**

Run:

```bash
git status --short --branch
git log --oneline main..HEAD
```

Expected: branch is `codex/live-telegram-ingestor`; worktree has no uncommitted implementation changes; commit list contains the plan and feature commits.

- [ ] **Step 4: Report manual verification gap**

Report clearly that automated tests cannot prove Telegram unread behavior. The manual unread smoke test must be run with a controlled chat before broad account use.
