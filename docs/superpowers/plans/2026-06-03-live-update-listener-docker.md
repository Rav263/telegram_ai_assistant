# Live Update Listener And Docker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a long-running Telegram live update listener with chat/channel allow-deny policy and package it in a production Docker runtime.

**Architecture:** Extend settings with listener allow/deny id sets, add a focused chat policy module, extend the read-only Telethon adapter with update subscription methods, then add `LiveUpdateListener` as the service that saves accepted updates and advances chat cursors. Wire it into `AppContext`, `runtime`, and CLI as `run listener`; package the same app image with Docker Compose running `postgres` and `app-listener`.

**Tech Stack:** Python 3.11, unittest, Telethon, psycopg, Docker, Docker Compose.

---

## File Structure

- Modify `src/telegram_ai_assistant/config.py`: parse listener allow/deny chat id sets.
- Modify `tests/test_config.py`: cover listener settings defaults, parsing, and invalid values.
- Create `src/telegram_ai_assistant/ingestion/chat_policy.py`: decide whether a chat/update is readable.
- Create `tests/test_chat_policy.py`: policy tests for private, group, supergroup, broadcast channel, allowlist, and denylist.
- Modify `src/telegram_ai_assistant/ingestion/ports.py`: add read-only update subscription methods to the `IngestionClient` protocol and `ReadOnlyIngestionClient`.
- Modify `tests/test_ingestion_ports.py`: cover safe event handler registration and waiting for disconnection.
- Create `src/telegram_ai_assistant/ingestion/listener.py`: implement `LiveUpdateListener` and result dataclasses.
- Create `tests/test_live_update_listener.py`: service-level tests for saving accepted updates, skipping rejected updates, cursor max behavior, and client close.
- Modify `src/telegram_ai_assistant/app_context.py`: build listener from settings.
- Modify `src/telegram_ai_assistant/runtime.py`: add `listener` process runner and startup JSON output.
- Modify `tests/test_app_context.py`, `tests/test_runtime.py`, `tests/test_cli.py`: runtime wiring tests.
- Create `.dockerignore`: exclude local and sensitive files from Docker context.
- Create `Dockerfile`: build production app image.
- Create `docker-compose.yml`: define `postgres` and `app-listener`.
- Modify `pyproject.toml`: include `db/schema.sql` in installed packages so containerized migrations work.
- Modify `docs/operations/local-runbook.md`: document listener and Docker commands.
- Create `tests/test_docker_packaging.py`: Docker and package-data assertions.
- Modify `tests/test_operations_docs.py`: document listener and Docker commands.
- Modify `CHANGELOG.md`: record the feature.

## Parallel Work Boundaries

These task groups can be assigned to parallel workers once the plan is approved:

- Worker A: Tasks 1-2, settings and chat policy files only.
- Worker B: Tasks 3-4, read-only event port and listener service files only.
- Worker C: Tasks 6-7, Docker and operations docs only.

Task 5 must integrate A and B. Task 8 must run after all implementation tasks.

### Task 1: Listener Settings

**Files:**
- Modify: `src/telegram_ai_assistant/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for defaults and parsing**

Add assertions to `SettingsTests.test_loads_required_settings_and_defaults`:

```python
self.assertEqual(settings.telegram_listener_allowed_channel_ids, frozenset())
self.assertEqual(settings.telegram_listener_denied_chat_ids, frozenset())
```

Add this block inside `test_loads_optional_lm_studio_backfill_and_ingest_limit_values` env:

```python
"TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS": "-100111,-100222",
"TELEGRAM_LISTENER_DENIED_CHAT_IDS": "123, 456",
```

Add assertions after the existing backfill assertions:

```python
self.assertEqual(settings.telegram_listener_allowed_channel_ids, frozenset({-100111, -100222}))
self.assertEqual(settings.telegram_listener_denied_chat_ids, frozenset({123, 456}))
```

Add a new test:

```python
def test_raises_when_telegram_listener_id_list_is_invalid(self):
    env = {
        **VALID_ENV,
        "TELEGRAM_LISTENER_DENIED_CHAT_IDS": "123,not-an-int",
    }

    with self.assertRaises(ConfigError):
        Settings.from_env(env)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v
```

Expected: fail because `Settings` has no listener id set fields.

- [ ] **Step 3: Implement listener settings**

In `src/telegram_ai_assistant/config.py`, add fields to `Settings`:

```python
telegram_listener_allowed_channel_ids: frozenset[int] = frozenset()
telegram_listener_denied_chat_ids: frozenset[int] = frozenset()
```

In `Settings.from_env`, pass:

```python
telegram_listener_allowed_channel_ids=_optional_int_set(
    env,
    "TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS",
),
telegram_listener_denied_chat_ids=_optional_int_set(
    env,
    "TELEGRAM_LISTENER_DENIED_CHAT_IDS",
),
```

Add helper:

```python
def _optional_int_set(env: Mapping[str, str], name: str) -> frozenset[int]:
    value = env.get(name)
    if value is None or not value.strip():
        return frozenset()
    result: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError as exc:
            raise ConfigError(f"setting must be a comma-separated list of integers: {name}") from exc
    return frozenset(result)
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_config -v
```

Expected: all config tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/telegram_ai_assistant/config.py tests/test_config.py
git commit -m "feat: add listener scope settings"
```

### Task 2: Chat Ingestion Policy

**Files:**
- Create: `src/telegram_ai_assistant/ingestion/chat_policy.py`
- Create: `tests/test_chat_policy.py`

- [ ] **Step 1: Write failing policy tests**

Create `tests/test_chat_policy.py`:

```python
import unittest

from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy, ChatMetadata


class ChatIngestionPolicyTests(unittest.TestCase):
    def test_allows_private_basic_group_and_supergroup_by_default(self):
        policy = ChatIngestionPolicy()

        self.assertTrue(policy.can_read(ChatMetadata(chat_id=10, chat_type="private")))
        self.assertTrue(policy.can_read(ChatMetadata(chat_id=11, chat_type="group")))
        self.assertTrue(
            policy.can_read(
                ChatMetadata(
                    chat_id=-10012,
                    chat_type="channel",
                    is_megagroup=True,
                    is_broadcast=False,
                )
            )
        )

    def test_rejects_broadcast_channel_without_allowlist(self):
        policy = ChatIngestionPolicy()

        self.assertFalse(
            policy.can_read(
                ChatMetadata(
                    chat_id=-100111,
                    chat_type="channel",
                    is_megagroup=False,
                    is_broadcast=True,
                )
            )
        )

    def test_allows_broadcast_channel_when_allowlisted(self):
        policy = ChatIngestionPolicy(allowed_channel_ids=frozenset({-100111}))

        self.assertTrue(
            policy.can_read(
                ChatMetadata(
                    chat_id=-100111,
                    chat_type="channel",
                    is_megagroup=False,
                    is_broadcast=True,
                )
            )
        )

    def test_denylist_overrides_default_and_channel_allowlist(self):
        policy = ChatIngestionPolicy(
            allowed_channel_ids=frozenset({-100111}),
            denied_chat_ids=frozenset({10, -100111}),
        )

        self.assertFalse(policy.can_read(ChatMetadata(chat_id=10, chat_type="private")))
        self.assertFalse(
            policy.can_read(
                ChatMetadata(
                    chat_id=-100111,
                    chat_type="channel",
                    is_megagroup=False,
                    is_broadcast=True,
                )
            )
        )

    def test_rejects_unknown_and_secret_chat_types(self):
        policy = ChatIngestionPolicy()

        self.assertFalse(policy.can_read(ChatMetadata(chat_id=20, chat_type="secret")))
        self.assertFalse(policy.can_read(ChatMetadata(chat_id=21, chat_type="unknown")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_chat_policy -v
```

Expected: fail because `telegram_ai_assistant.ingestion.chat_policy` does not exist.

- [ ] **Step 3: Implement policy**

Create `src/telegram_ai_assistant/ingestion/chat_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMetadata:
    chat_id: int
    chat_type: str
    title: str = ""
    is_megagroup: bool = False
    is_broadcast: bool = False


@dataclass(frozen=True)
class ChatIngestionPolicy:
    allowed_channel_ids: frozenset[int] = frozenset()
    denied_chat_ids: frozenset[int] = frozenset()

    def can_read(self, chat: ChatMetadata) -> bool:
        if chat.chat_id in self.denied_chat_ids:
            return False
        if chat.is_broadcast:
            return chat.chat_id in self.allowed_channel_ids
        if chat.is_megagroup:
            return True
        return chat.chat_type in {"private", "group", "supergroup"}
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_chat_policy -v
```

Expected: all chat policy tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/telegram_ai_assistant/ingestion/chat_policy.py tests/test_chat_policy.py
git commit -m "feat: add listener chat policy"
```

### Task 3: Read-Only Update Subscription Port

**Files:**
- Modify: `src/telegram_ai_assistant/ingestion/ports.py`
- Modify: `src/telegram_ai_assistant/ingestion/telethon_adapter.py`
- Modify: `tests/test_ingestion_ports.py`

- [ ] **Step 1: Write failing tests for event subscription**

Extend `FakeTelegramClient`:

```python
self.event_handlers = []
self.disconnected_waited = False
```

Add methods:

```python
def add_event_handler(self, handler, event):
    self.calls.append(("add_event_handler", event.__class__.__name__))
    self.event_handlers.append((handler, event))

async def run_until_disconnected(self):
    self.calls.append(("run_until_disconnected",))
    self.disconnected_waited = True
```

Add a fake event class near `FakeMessage`:

```python
class FakeNewMessageEvent:
    pass
```

Add test:

```python
def test_listen_new_messages_registers_allowed_handler_and_waits_until_disconnected(self):
    fake_client = FakeTelegramClient()
    client = ReadOnlyIngestionClient(
        fake_client,
        guard=ReadOnlyTelegramGuard(),
        new_message_event_factory=FakeNewMessageEvent,
    )

    async def handler(update):
        return None

    asyncio.run(client.listen_new_messages(handler))
    asyncio.run(client.run_until_disconnected())

    self.assertEqual(len(fake_client.event_handlers), 1)
    self.assertIs(fake_client.event_handlers[0][0], handler)
    self.assertIsInstance(fake_client.event_handlers[0][1], FakeNewMessageEvent)
    self.assertEqual(
        fake_client.calls[-2:],
        [("add_event_handler", "FakeNewMessageEvent"), ("run_until_disconnected",)],
    )
```

Add test for adapter event factory loading:

```python
def test_telethon_adapter_loads_new_message_event_factory(self):
    from telegram_ai_assistant.ingestion import telethon_adapter

    original_loader = telethon_adapter._load_telegram_client
    original_event_loader = telethon_adapter._load_new_message_event
    FakeTelethonClient.instances = []

    class FakeLoadedNewMessageEvent:
        pass

    telethon_adapter._load_telegram_client = lambda: FakeTelethonClient
    telethon_adapter._load_new_message_event = lambda: FakeLoadedNewMessageEvent
    try:
        adapter = asyncio.run(
            TelethonIngestionAdapter.connect(
                "session-name",
                123,
                "hash",
            )
        )
    finally:
        telethon_adapter._load_telegram_client = original_loader
        telethon_adapter._load_new_message_event = original_event_loader

    async def handler(update):
        return None

    asyncio.run(adapter.listen_new_messages(handler))

    fake_client = FakeTelethonClient.instances[0]
    self.assertEqual(fake_client.calls[-1], ("add_event_handler", "FakeLoadedNewMessageEvent"))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_ports -v
```

Expected: fail because `ReadOnlyIngestionClient` has no `listen_new_messages` or constructor event factory.

- [ ] **Step 3: Implement update port**

In `src/telegram_ai_assistant/ingestion/ports.py`, update imports:

```python
from collections.abc import AsyncIterator, Awaitable, Callable
```

Add protocol methods:

```python
    async def listen_new_messages(self, handler: Callable[[object], Awaitable[None]]) -> None:
        pass

    async def run_until_disconnected(self) -> None:
        pass
```

Update `ReadOnlyIngestionClient.__init__`:

```python
def __init__(
    self,
    client: object,
    guard: ReadOnlyTelegramGuard | None = None,
    new_message_event_factory: Callable[[], object] | None = None,
):
    self._client = client
    self._guard = guard or ReadOnlyTelegramGuard()
    self._new_message_event_factory = new_message_event_factory
```

Add methods:

```python
async def listen_new_messages(self, handler: Callable[[object], Awaitable[None]]) -> None:
    method = self._allowed_method("add_event_handler")
    if self._new_message_event_factory is None:
        raise RuntimeError("NewMessage event factory is not configured")
    method(handler, self._new_message_event_factory())

async def run_until_disconnected(self) -> None:
    await self.call("run_until_disconnected")
```

In `src/telegram_ai_assistant/ingestion/telethon_adapter.py`, return adapter with factory:

```python
return cls(
    client,
    guard=guard or ReadOnlyTelegramGuard(),
    new_message_event_factory=_load_new_message_event,
)
```

Add loader:

```python
def _load_new_message_event() -> type[Any]:
    try:
        from telethon import events
    except ImportError as exc:
        raise TelethonAdapterError("Telethon is required to use TelethonIngestionAdapter") from exc
    return events.NewMessage
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_ingestion_ports -v
```

Expected: all ingestion port tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/telegram_ai_assistant/ingestion/ports.py src/telegram_ai_assistant/ingestion/telethon_adapter.py tests/test_ingestion_ports.py
git commit -m "feat: add read-only live update subscription"
```

### Task 4: Live Update Listener Service

**Files:**
- Create: `src/telegram_ai_assistant/ingestion/listener.py`
- Create: `tests/test_live_update_listener.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_live_update_listener.py`:

```python
import asyncio
from datetime import UTC, datetime
import unittest

from telegram_ai_assistant.domain import Message, MessageDirection
from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy, ChatMetadata
from telegram_ai_assistant.ingestion.listener import LiveUpdateListener


class FakeConnectionFactory:
    def __init__(self):
        self.connection_obj = FakeConnection()

    def connection(self):
        return self.connection_obj


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeAccountRepository:
    def __init__(self, connection):
        self.accounts = []

    def ensure_account(self, account_id, telegram_user_id=None, display_name=""):
        self.accounts.append((account_id, telegram_user_id, display_name))


class FakeChatRepository:
    def __init__(self, connection):
        self.chats = []
        self.cursor = 0
        self.updated_cursors = []

    def ensure_chat(self, account_id, chat_id, title="", chat_type=""):
        self.chats.append((account_id, chat_id, title, chat_type))

    def get_last_ingested_message_id(self, account_id, chat_id):
        return self.cursor

    def update_ingestion_cursor(self, account_id, chat_id, last_message_id, ingested_at):
        self.cursor = last_message_id
        self.updated_cursors.append((account_id, chat_id, last_message_id, ingested_at))


class FakeMessageRepository:
    def __init__(self, connection):
        self.messages = []

    def upsert_message(self, message):
        self.messages.append(message)


class FakeListenerClient:
    def __init__(self):
        self.handler = None
        self.calls = []

    async def listen_new_messages(self, handler):
        self.handler = handler
        self.calls.append("listen")

    async def run_until_disconnected(self):
        self.calls.append("run_until_disconnected")

    async def close(self):
        self.calls.append("close")


class FakeEvent:
    def __init__(self, raw_message, chat_metadata):
        self.message = raw_message
        self.chat_metadata = chat_metadata


class RawMessage:
    def __init__(self, message_id, chat_id=1001, text="hello"):
        self.id = message_id
        self.chat_id = chat_id
        self.sender_id = 3001
        self.date = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)
        self.message = text
        self.out = False


class RepositoryBundle:
    def __init__(self, account, chat, messages):
        self.account = account
        self.chat = chat
        self.messages = messages


class LiveUpdateListenerTests(unittest.TestCase):
    def test_run_forever_registers_handler_and_closes_client(self):
        client = FakeListenerClient()
        listener, _repositories = make_listener(client)

        result = asyncio.run(listener.run_forever())

        self.assertIsNotNone(client.handler)
        self.assertEqual(client.calls, ["listen", "run_until_disconnected", "close"])
        self.assertEqual(result.account_id, "owner")
        self.assertEqual(result.status, "stopped")

    def test_handler_saves_accepted_update_and_advances_cursor(self):
        client = FakeListenerClient()
        listener, repositories = make_listener(client)
        asyncio.run(listener.run_forever())

        asyncio.run(
            client.handler(
                FakeEvent(
                    RawMessage(50),
                    ChatMetadata(chat_id=1001, chat_type="private", title="Alice"),
                )
            )
        )

        self.assertEqual(repositories.account.accounts, [("owner", None, "")])
        self.assertEqual(repositories.chat.chats, [("owner", 1001, "Alice", "private")])
        self.assertEqual(
            repositories.messages.messages,
            [
                Message(
                    account_id="owner",
                    chat_id=1001,
                    telegram_message_id=50,
                    sender_id=3001,
                    direction=MessageDirection.INCOMING,
                    sent_at=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
                    text="hello",
                )
            ],
        )
        self.assertEqual(repositories.chat.updated_cursors[-1][2], 50)

    def test_handler_does_not_move_cursor_backwards(self):
        client = FakeListenerClient()
        listener, repositories = make_listener(client)
        repositories.chat.cursor = 100
        asyncio.run(listener.run_forever())

        asyncio.run(
            client.handler(
                FakeEvent(
                    RawMessage(50),
                    ChatMetadata(chat_id=1001, chat_type="private"),
                )
            )
        )

        self.assertEqual(repositories.chat.updated_cursors[-1][2], 100)

    def test_handler_skips_rejected_update(self):
        client = FakeListenerClient()
        listener, repositories = make_listener(
            client,
            policy=ChatIngestionPolicy(denied_chat_ids=frozenset({1001})),
        )
        asyncio.run(listener.run_forever())

        asyncio.run(
            client.handler(
                FakeEvent(
                    RawMessage(50),
                    ChatMetadata(chat_id=1001, chat_type="private"),
                )
            )
        )

        self.assertEqual(repositories.account.accounts, [])
        self.assertEqual(repositories.chat.chats, [])
        self.assertEqual(repositories.messages.messages, [])
        self.assertEqual(repositories.chat.updated_cursors, [])


def make_listener(client, policy=None):
    connection_factory = FakeConnectionFactory()
    repositories = RepositoryBundle(
        account=FakeAccountRepository(connection_factory.connection_obj),
        chat=FakeChatRepository(connection_factory.connection_obj),
        messages=FakeMessageRepository(connection_factory.connection_obj),
    )
    listener = LiveUpdateListener(
        account_id="owner",
        connection_factory=connection_factory,
        client_factory=lambda: client,
        policy=policy or ChatIngestionPolicy(),
        account_repository_factory=lambda connection: repositories.account,
        chat_repository_factory=lambda connection: repositories.chat,
        message_repository_factory=lambda connection: repositories.messages,
        now=lambda: datetime(2026, 6, 3, 11, 0, tzinfo=UTC),
        chat_metadata_extractor=lambda event: event.chat_metadata,
        message_extractor=lambda event: event.message,
    )
    return listener, repositories


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_update_listener -v
```

Expected: fail because `telegram_ai_assistant.ingestion.listener` does not exist.

- [ ] **Step 3: Implement listener service**

Create `src/telegram_ai_assistant/ingestion/listener.py`:

```python
from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telegram_ai_assistant.db.repositories import AccountRepository, ChatRepository, MessageRepository
from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy, ChatMetadata
from telegram_ai_assistant.ingestion.normalizer import normalize_telegram_message
from telegram_ai_assistant.ingestion.ports import IngestionClient


@dataclass(frozen=True)
class ListenerRunResult:
    account_id: str
    status: str


class LiveUpdateListener:
    def __init__(
        self,
        *,
        account_id: str,
        connection_factory: Any,
        client_factory: Callable[[], Any],
        policy: ChatIngestionPolicy,
        normalizer: Callable[[str, object], Any] = normalize_telegram_message,
        account_repository_factory: Callable[[Any], Any] = AccountRepository,
        chat_repository_factory: Callable[[Any], Any] = ChatRepository,
        message_repository_factory: Callable[[Any], Any] = MessageRepository,
        now: Callable[[], datetime] | None = None,
        chat_metadata_extractor: Callable[[object], ChatMetadata] | None = None,
        message_extractor: Callable[[object], object] | None = None,
    ):
        self.account_id = account_id
        self.connection_factory = connection_factory
        self.client_factory = client_factory
        self.policy = policy
        self.normalizer = normalizer
        self.account_repository_factory = account_repository_factory
        self.chat_repository_factory = chat_repository_factory
        self.message_repository_factory = message_repository_factory
        self.now = now or (lambda: datetime.now(UTC))
        self.chat_metadata_extractor = chat_metadata_extractor or extract_chat_metadata
        self.message_extractor = message_extractor or extract_event_message

    async def run_forever(self) -> ListenerRunResult:
        client = await _resolve_client(self.client_factory())
        try:
            await client.listen_new_messages(self.handle_update)
            await client.run_until_disconnected()
        finally:
            await client.close()
        return ListenerRunResult(account_id=self.account_id, status="stopped")

    async def handle_update(self, event: object) -> None:
        chat_metadata = self.chat_metadata_extractor(event)
        if not self.policy.can_read(chat_metadata):
            return

        raw_message = self.message_extractor(event)
        message = self.normalizer(self.account_id, raw_message)

        with self.connection_factory.connection() as connection:
            account_repository = self.account_repository_factory(connection)
            chat_repository = self.chat_repository_factory(connection)
            message_repository = self.message_repository_factory(connection)

            account_repository.ensure_account(self.account_id)
            chat_repository.ensure_chat(
                self.account_id,
                chat_metadata.chat_id,
                chat_metadata.title,
                chat_metadata.chat_type,
            )
            message_repository.upsert_message(message)
            current_cursor = chat_repository.get_last_ingested_message_id(
                self.account_id,
                chat_metadata.chat_id,
            )
            chat_repository.update_ingestion_cursor(
                self.account_id,
                chat_metadata.chat_id,
                max(current_cursor, message.telegram_message_id),
                self.now(),
            )


async def _resolve_client(value: Any) -> IngestionClient:
    if inspect.isawaitable(value):
        return await value
    return value


def extract_event_message(event: object) -> object:
    return getattr(event, "message")


def extract_chat_metadata(event: object) -> ChatMetadata:
    chat = getattr(event, "chat", None)
    message = extract_event_message(event)
    chat_id = int(getattr(message, "chat_id"))
    is_megagroup = bool(getattr(chat, "megagroup", False))
    is_broadcast = bool(getattr(chat, "broadcast", False))
    title = str(getattr(chat, "title", "") or getattr(chat, "first_name", "") or "")
    chat_type = _chat_type(chat, is_megagroup, is_broadcast)
    return ChatMetadata(
        chat_id=chat_id,
        chat_type=chat_type,
        title=title,
        is_megagroup=is_megagroup,
        is_broadcast=is_broadcast,
    )


def _chat_type(chat: object, is_megagroup: bool, is_broadcast: bool) -> str:
    if is_broadcast:
        return "channel"
    if is_megagroup:
        return "supergroup"
    class_name = chat.__class__.__name__.lower() if chat is not None else ""
    if "chat" in class_name:
        return "group"
    if "user" in class_name:
        return "private"
    return "unknown"
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_live_update_listener -v
```

Expected: all listener service tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/telegram_ai_assistant/ingestion/listener.py tests/test_live_update_listener.py
git commit -m "feat: add live update listener service"
```

### Task 5: Runtime And CLI Wiring

**Files:**
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `tests/test_app_context.py`
- Modify: `tests/test_runtime.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing runtime tests**

In `tests/test_app_context.py`, add:

```python
    def test_run_listener_forever_builds_service_with_settings(self):
        factory = FakeConnectionFactory()
        captured = {}

        class FakeListener:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def run_forever(self):
                return "result"

        settings = replace(
            make_settings(),
            telegram_listener_allowed_channel_ids=frozenset({-100111}),
            telegram_listener_denied_chat_ids=frozenset({1002}),
        )
        context = AppContext(
            settings=settings,
            connection_factory=factory,
            listener_factory=FakeListener,
            telegram_client_factory=lambda settings: "client-factory",
        )

        result = asyncio.run(context.run_listener_forever())

        self.assertEqual(result, "result")
        self.assertEqual(captured["account_id"], "owner")
        self.assertEqual(captured["policy"].allowed_channel_ids, frozenset({-100111}))
        self.assertEqual(captured["policy"].denied_chat_ids, frozenset({1002}))
        self.assertIs(captured["connection_factory"], factory)
        self.assertEqual(captured["client_factory"], "client-factory")
```

In `tests/test_runtime.py`, import `ListenerRunResult` and `run_listener`:

```python
from telegram_ai_assistant.ingestion.listener import ListenerRunResult
...
    run_listener,
```

Update `test_all_declared_processes_have_default_runners` expected tuple:

```python
("ingestor", "backfill", "listener", "worker", "bot", "scheduler", "all")
```

Add:

```python
    def test_run_listener_executes_context_and_prints_startup_result(self):
        calls = []

        class FakeContext:
            async def run_listener_forever(self):
                calls.append("run")
                return ListenerRunResult(account_id="owner", status="stopped")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_listener(make_settings(), context_factory=lambda settings: FakeContext())

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["run"])
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["process"], "listener")
        self.assertEqual(payload["account_id"], "owner")
        self.assertEqual(payload["status"], "stopped")

    def test_run_listener_failure_returns_nonzero_without_secret_values(self):
        class FailingContext:
            async def run_listener_forever(self):
                raise RuntimeError("failed with secret-token")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = run_listener(make_settings(), context_factory=lambda settings: FailingContext())

        self.assertEqual(exit_code, 1)
        self.assertIn("listener failed", output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())
```

In `tests/test_cli.py`, add:

```python
    def test_parses_run_listener_command(self):
        args = build_parser().parse_args(["run", "listener"])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.process, "listener")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime tests.test_cli -v
```

Expected: fail because listener runtime wiring does not exist.

- [ ] **Step 3: Implement runtime wiring**

In `src/telegram_ai_assistant/app_context.py`, import:

```python
from .ingestion.chat_policy import ChatIngestionPolicy
from .ingestion.listener import LiveUpdateListener
```

Add dataclass field:

```python
listener_factory: Any = LiveUpdateListener
```

Add method:

```python
async def run_listener_forever(self):
    listener = self.listener_factory(
        account_id=self.settings.telegram_ingest_account_id,
        connection_factory=self.connection_factory,
        client_factory=self.telegram_client_factory(self.settings),
        policy=ChatIngestionPolicy(
            allowed_channel_ids=self.settings.telegram_listener_allowed_channel_ids,
            denied_chat_ids=self.settings.telegram_listener_denied_chat_ids,
        ),
    )
    return await listener.run_forever()
```

In `src/telegram_ai_assistant/runtime.py`, import:

```python
from .ingestion.listener import ListenerRunResult
```

Update `PROCESS_NAMES`:

```python
PROCESS_NAMES = ("ingestor", "backfill", "listener", "worker", "bot", "scheduler", "all")
```

Add:

```python
def run_listener(settings: Settings, *, context_factory=AppContext.from_settings) -> int:
    try:
        result = asyncio.run(context_factory(settings).run_listener_forever())
    except Exception as exc:
        print(f"listener failed: {type(exc).__name__}")
        return 1
    print(json.dumps(_listener_result_payload(result), ensure_ascii=False, sort_keys=True))
    return 0


def _listener_result_payload(result: ListenerRunResult) -> dict[str, Any]:
    return {
        "process": "listener",
        "account_id": result.account_id,
        "status": result.status,
    }
```

Add to `DEFAULT_RUNNERS`:

```python
"listener": run_listener,
```

Do not add `listener` to `run_all`; it is long-running.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_runtime tests.test_cli -v
```

Expected: all runtime wiring tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/telegram_ai_assistant/app_context.py src/telegram_ai_assistant/runtime.py tests/test_app_context.py tests/test_runtime.py tests/test_cli.py
git commit -m "feat: wire live update listener runtime"
```

### Task 6: Docker Production Runtime

**Files:**
- Create: `.dockerignore`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `pyproject.toml`
- Create: `tests/test_docker_packaging.py`

- [ ] **Step 1: Write failing Docker file tests**

Create `tests/test_docker_packaging.py`:

```python
from pathlib import Path
import tomllib
import unittest


class DockerPackagingTests(unittest.TestCase):
    def test_dockerfile_installs_project_and_runs_listener_cli(self):
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("useradd", dockerfile)
        self.assertIn("/var/lib/telegram-ai-assistant/sessions", dockerfile)
        self.assertIn("pip install --no-cache-dir .", dockerfile)
        self.assertIn('CMD ["telegram-ai-assistant", "run", "listener"]', dockerfile)

    def test_docker_compose_defines_postgres_and_listener(self):
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("postgres:", compose)
        self.assertIn("app-listener:", compose)
        self.assertIn("telegram-ai-assistant run listener", compose)
        self.assertIn("telegram-sessions", compose)
        self.assertIn("TELEGRAM_SESSION_PATH", compose)
        self.assertIn("/var/lib/telegram-ai-assistant/sessions", compose)
        self.assertIn("env_file:", compose)

    def test_dockerignore_excludes_local_sensitive_and_generated_files(self):
        dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

        self.assertIn(".git", dockerignore)
        self.assertIn(".venv", dockerignore)
        self.assertIn(".worktrees", dockerignore)
        self.assertIn(".local", dockerignore)
        self.assertIn("*.session", dockerignore)

    def test_schema_sql_is_included_in_installed_package_data(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["tool"]["setuptools"]["package-data"]["telegram_ai_assistant.db"],
            ["schema.sql"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_docker_packaging -v
```

Expected: fail because Docker files do not exist and `schema.sql` is not package data.

- [ ] **Step 3: Add `.dockerignore`**

Create `.dockerignore`:

```dockerignore
.git
.codegraph
.cursor
.worktrees
.venv
__pycache__
*.pyc
*.pyo
.pytest_cache
.mypy_cache
.ruff_cache
.DS_Store
.env
.env.*
.local
*.session
*.session-journal
src/*.egg-info
dist
build
.idea
.vscode
```

- [ ] **Step 4: Include migration SQL in package data**

Add to `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"telegram_ai_assistant.db" = ["schema.sql"]
```

- [ ] **Step 5: Add `Dockerfile`**

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN useradd --create-home --shell /bin/sh appuser \
    && mkdir -p /var/lib/telegram-ai-assistant/sessions \
    && chown -R appuser:appuser /var/lib/telegram-ai-assistant
USER appuser

CMD ["telegram-ai-assistant", "run", "listener"]
```

- [ ] **Step 6: Add `docker-compose.yml`**

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: telegram_ai_assistant
      POSTGRES_USER: telegram_ai_assistant
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-telegram_ai_assistant}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U telegram_ai_assistant -d telegram_ai_assistant"]
      interval: 10s
      timeout: 5s
      retries: 5

  app-listener:
    build: .
    restart: unless-stopped
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://telegram_ai_assistant:${POSTGRES_PASSWORD:-telegram_ai_assistant}@postgres:5432/telegram_ai_assistant
      TELEGRAM_SESSION_PATH: /var/lib/telegram-ai-assistant/sessions/telegram-owner.session
    command: telegram-ai-assistant run listener
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - telegram-sessions:/var/lib/telegram-ai-assistant/sessions

volumes:
  postgres-data:
  telegram-sessions:
```

- [ ] **Step 7: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_docker_packaging -v
```

Expected: all Docker packaging tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add .dockerignore Dockerfile docker-compose.yml pyproject.toml tests/test_docker_packaging.py
git commit -m "feat: add production docker listener runtime"
```

### Task 7: Operations Docs And Changelog

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `tests/test_operations_docs.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing docs tests**

In `tests/test_operations_docs.py`, add assertions to `test_local_runbook_mentions_core_services`:

```python
self.assertIn("TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS", text)
self.assertIn("TELEGRAM_LISTENER_DENIED_CHAT_IDS", text)
self.assertIn("telegram-ai-assistant run listener", text)
self.assertIn("docker compose up -d postgres app-listener", text)
self.assertIn("docker compose run --rm app-listener telegram-ai-assistant migrate", text)
self.assertIn("docker compose run --rm app-listener telegram-ai-assistant health", text)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_operations_docs -v
```

Expected: fail until runbook is updated.

- [ ] **Step 3: Update runbook env block**

In `docs/operations/local-runbook.md`, add to the `.env` example:

```bash
TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS=
TELEGRAM_LISTENER_DENIED_CHAT_IDS=
```

- [ ] **Step 4: Add Listener section**

Add after the `Ingestor` section:

```markdown
## Listener

Use `telegram-ai-assistant run listener` for live update ingestion. It listens for new Telegram messages and saves accepted updates without intentionally marking messages read.

By default the listener reads private chats, basic groups, and supergroups. Broadcast channels are ignored unless their ids are listed in `TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS`. Any id in `TELEGRAM_LISTENER_DENIED_CHAT_IDS` is never read.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run listener
```

Keep `run ingestor` available as cursor catch-up after the machine sleeps or the listener is stopped.
```

- [ ] **Step 5: Add Docker section**

Add before `Tests`:

```markdown
## Docker

Build and start the production listener stack:

```bash
docker compose up -d postgres app-listener
```

Run migrations in the same image:

```bash
docker compose run --rm app-listener telegram-ai-assistant migrate
```

Run one-shot backfill in the same image:

```bash
docker compose run --rm app-listener telegram-ai-assistant run backfill
```

Run health in the same image:

```bash
docker compose run --rm app-listener telegram-ai-assistant health
```

On macOS, use `LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1` when LM Studio runs on the host. On Linux, set `LM_STUDIO_BASE_URL` to a host address reachable from the container.
```

- [ ] **Step 6: Update changelog**

Add under `## Unreleased`:

```markdown
- Added live Telegram update listener with chat/channel allow-deny policy.
- Added Docker production runtime for the listener and Postgres.
```

- [ ] **Step 7: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_operations_docs -v
```

Expected: operations docs tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add docs/operations/local-runbook.md tests/test_operations_docs.py CHANGELOG.md
git commit -m "docs: document live listener docker runtime"
```

### Task 8: Full Verification

**Files:**
- Verify all files changed by Tasks 1-7.

- [ ] **Step 1: Run full unit suite**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI version**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli version
```

Expected: prints `0.1.0`.

- [ ] **Step 3: Run offline health**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli health --offline
```

Expected: JSON with `"status": "ok"`.

- [ ] **Step 4: Run Docker config validation if Docker is available**

Run:

```bash
docker compose config
```

Expected: exits `0` and prints normalized compose config. If Docker is not available, record the exact failure in the final response.

- [ ] **Step 5: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit `0`.

- [ ] **Step 6: Review git status**

Run:

```bash
git status --short --branch
```

Expected: only intentional tracked changes remain, or no tracked changes after commits. Untracked local generated files must not be staged unless listed in this plan.

## Self-Review

- Spec coverage: settings, policy, read-only update subscription, listener service, runtime/CLI, Docker packaging, operations docs, and verification are covered.
- TDD coverage: every production behavior task starts with failing tests and verifies RED before implementation.
- Scope: startup catch-up, bot policy management, worker/bot Docker services, media extraction, and secret chats remain out of scope as required.
