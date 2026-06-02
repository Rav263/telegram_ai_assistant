# Production Wiring Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production wiring for `.env` loading, `psycopg` Postgres connections, real schema migration, online health checks, and a lightweight `AppContext`.

**Architecture:** Keep the existing tested core unchanged and add narrow wiring modules around it. `env.py` loads environment values, `db/connection.py` owns Postgres connection lifecycle, `app_context.py` builds factories without opening connections, and `cli.py` routes `migrate` and online `health` through those factories.

**Tech Stack:** Python 3.11+, `unittest`, project-local `.venv`, `psycopg` v3 dependency declared in `pyproject.toml`, no external dotenv dependency.

---

## File Structure

- Create `src/telegram_ai_assistant/env.py`: minimal `.env` parser and environment merge helper.
- Create `src/telegram_ai_assistant/db/connection.py`: `PostgresConnectionFactory` with injectable connect callable.
- Create `src/telegram_ai_assistant/app_context.py`: context factory for settings, connections, migration, and health.
- Modify `src/telegram_ai_assistant/health.py`: add online component check helpers for Postgres and LM Studio.
- Modify `src/telegram_ai_assistant/cli.py`: wire `migrate` and online `health` through `AppContext`.
- Modify `pyproject.toml`: add `psycopg[binary]>=3.2`.
- Modify `CHANGELOG.md`: add production wiring entry.
- Modify `docs/operations/local-runbook.md`: document `.env`, `migrate`, and online health.
- Add tests under `tests/` for each new behavior.

## Parallel Work Boundaries

These scopes can run in parallel after worktree setup:

- Env scope: `src/telegram_ai_assistant/env.py`, `tests/test_env.py`.
- DB connection scope: `src/telegram_ai_assistant/db/connection.py`, `tests/test_db_connection.py`.

The coordinating agent owns `app_context.py`, `cli.py`, `health.py`, `pyproject.toml`, `CHANGELOG.md`, and docs to avoid conflicts.

## Task 1: Minimal `.env` Loader

**Files:**
- Create: `src/telegram_ai_assistant/env.py`
- Test: `tests/test_env.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_env.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from telegram_ai_assistant.env import load_dotenv, load_environment


class EnvLoaderTests(unittest.TestCase):
    def test_load_dotenv_parses_comments_empty_lines_and_quotes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                """
# comment
TELEGRAM_API_HASH='hash value'
DATABASE_URL="postgresql://localhost/db"
BACKFILL_DAYS=30
""",
                encoding="utf-8",
            )

            values = load_dotenv(path)

        self.assertEqual(values["TELEGRAM_API_HASH"], "hash value")
        self.assertEqual(values["DATABASE_URL"], "postgresql://localhost/db")
        self.assertEqual(values["BACKFILL_DAYS"], "30")

    def test_missing_dotenv_returns_empty_mapping(self):
        self.assertEqual(load_dotenv(Path("/tmp/missing-telegram-ai.env")), {})

    def test_shell_environment_overrides_dotenv_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DATABASE_URL=postgresql://dotenv/db\n", encoding="utf-8")

            values = load_environment(path, {"DATABASE_URL": "postgresql://shell/db"})

        self.assertEqual(values["DATABASE_URL"], "postgresql://shell/db")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_env -v
```

Expected: FAIL because `telegram_ai_assistant.env` does not exist.

- [ ] **Step 3: Implement `env.py`**

Create `src/telegram_ai_assistant/env.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Mapping


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_environment(env_file: Path, environ: Mapping[str, str]) -> dict[str, str]:
    merged = load_dotenv(env_file)
    merged.update(dict(environ))
    return merged
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_env -v
```

Expected: PASS.

## Task 2: Postgres Connection Factory

**Files:**
- Create: `src/telegram_ai_assistant/db/connection.py`
- Test: `tests/test_db_connection.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_db_connection.py` with fake connection objects asserting:

- `PostgresConnectionFactory.connect()` calls the injected connect callable with the database URL.
- `PostgresConnectionFactory.connection()` commits and closes on success.
- `PostgresConnectionFactory.connection()` rolls back and closes on failure.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_connection -v
```

Expected: FAIL because `telegram_ai_assistant.db.connection` does not exist.

- [ ] **Step 3: Implement connection factory**

Create `src/telegram_ai_assistant/db/connection.py` with:

```python
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


ConnectCallable = Callable[[str], Any]


def default_connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(database_url)


class PostgresConnectionFactory:
    def __init__(self, database_url: str, connect: ConnectCallable = default_connect):
        self.database_url = database_url
        self._connect = connect

    def connect(self) -> Any:
        return self._connect(self.database_url)

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = self.connect()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_db_connection -v
```

Expected: PASS.

## Task 3: AppContext And Migration Runner

**Files:**
- Create: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/cli.py`
- Test: `tests/test_app_context.py`
- Test: `tests/test_cli_migrate.py`

- [ ] **Step 1: Write failing AppContext tests**

Create tests that build `AppContext(settings, connection_factory)` with fake connection factory and assert construction does not open a connection. Assert `context.migrate()` opens a connection and calls `apply_schema`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context -v
```

Expected: FAIL because `app_context.py` does not exist.

- [ ] **Step 3: Implement AppContext**

Create `AppContext` as a dataclass with `settings`, `connection_factory`, `schema_applier`, `health_transport`, and methods `from_environment(environment)`, `migrate()`, and `online_health_report()`.

- [ ] **Step 4: Write failing migrate CLI tests**

Create `tests/test_cli_migrate.py` using a fake `context_factory` passed to `main([...], context_factory=...)`. Assert:

- `main(["migrate"], context_factory=fake)` returns `0` and calls `migrate`.
- failed migrate returns non-zero and does not print secret values.

- [ ] **Step 5: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_cli_migrate -v
```

Expected: FAIL because `main()` does not accept `context_factory` and `migrate` still prints stub text.

- [ ] **Step 6: Implement migrate CLI wiring**

Modify `cli.main()` to accept optional `env_file`, `environ`, and `context_factory` keyword-only args. `migrate` should load environment, build context, call `context.migrate()`, print a success message, and return `0`; exceptions return `1`.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_app_context tests.test_cli_migrate -v
```

Expected: PASS.

## Task 4: Online Health Wiring

**Files:**
- Modify: `src/telegram_ai_assistant/health.py`
- Modify: `src/telegram_ai_assistant/app_context.py`
- Modify: `src/telegram_ai_assistant/cli.py`
- Test: `tests/test_online_health.py`
- Test: `tests/test_cli_health.py`

- [ ] **Step 1: Write failing online health tests**

Create tests with fake Postgres connection factory and fake LM Studio transport. Assert online health returns `ok` when `SELECT 1` and `/models` succeed, and `down` when either fake fails.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_online_health -v
```

Expected: FAIL because online health helpers do not exist.

- [ ] **Step 3: Implement online health helpers**

Add `postgres_health_check(connection_factory)` and `lm_studio_health_check(base_url, transport)` helpers returning `ComponentHealth`. Use injectable transport in tests and standard-library HTTP in production.

- [ ] **Step 4: Write failing CLI health tests**

Create tests asserting `main(["health"], context_factory=fake)` returns `0`, prints JSON with component names, and keeps `main(["health", "--offline"])` unchanged.

- [ ] **Step 5: Implement CLI health wiring**

Modify `cli.py` so online health builds `AppContext` and prints `context.online_health_report()` JSON. Keep `--offline` no-network behavior.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_online_health tests.test_cli_health -v
```

Expected: PASS.

## Task 5: Dependency, Runbook, And Final Verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `docs/operations/local-runbook.md`

- [ ] **Step 1: Add dependency**

Modify `pyproject.toml`:

```toml
dependencies = [
    "psycopg[binary]>=3.2",
]
```

- [ ] **Step 2: Update docs and changelog**

Add a changelog bullet:

```markdown
- Added production wiring for `.env`, Postgres migrations, AppContext, and online health.
```

Update `docs/operations/local-runbook.md` with:

```markdown
telegram-ai-assistant migrate
telegram-ai-assistant health
telegram-ai-assistant health --offline
```

- [ ] **Step 3: Run final verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli version
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli health --offline
```

Expected: all tests PASS, version prints `0.1.0`, offline health prints JSON.

- [ ] **Step 4: Commit**

Run:

```bash
git add pyproject.toml CHANGELOG.md docs/operations/local-runbook.md src/telegram_ai_assistant tests
git commit -m "feat: add production wiring base"
```

