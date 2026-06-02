# Production Wiring Base Design

Date: 2026-06-02

## Goal

Add the first production wiring layer for the Telegram AI assistant: `.env` loading, `psycopg` Postgres connection factory, real `migrate` CLI behavior, online health checks, and an `AppContext` factory layer.

This feature connects existing tested core modules to real local infrastructure without implementing live Telegram, bot, worker, or scheduler loops.

## Core Decisions

- Use `psycopg` v3 as the Postgres driver.
- Keep a synchronous DB-API-like runtime because existing repositories and migrations are sync.
- Use a minimal built-in `.env` parser instead of `python-dotenv`.
- Shell environment variables override `.env` values.
- `migrate` only applies schema to an existing database. It does not create the database.
- Add `AppContext` and factories, but do not add a DI framework.
- Keep `run ingestor`, `run worker`, `run bot`, and `run scheduler` as dispatch points.
- Keep TDD mandatory for every behavior.

## Architecture

Add these modules:

- `env.py`: loads environment values from a `.env` file and merges them with `os.environ`.
- `db/connection.py`: creates Postgres connections using `psycopg.connect`.
- `app_context.py`: constructs settings, connection factories, repository factories, migration service, and health checker.

Modify these modules:

- `cli.py`: route `migrate` and online `health` through `AppContext`.
- `runtime.py`: keep process dispatch points, but allow them to receive context-ready settings/factories in later slices.
- `health.py`: support real component checks while preserving offline health behavior.
- `pyproject.toml`: add `psycopg` as a dependency.
- `docs/operations/local-runbook.md`: document `.env`, migration, health, and manual Postgres setup.

No global DB connection should exist. Connections are opened by factories and closed by command boundaries.

## Environment Loading

The `.env` parser supports:

- missing file returns an empty mapping;
- empty lines;
- comment lines beginning with `#`;
- `KEY=value`;
- optional single or double quotes around values;
- preserving spaces inside quoted values.

The `.env` parser does not support:

- variable expansion;
- multiline values;
- `export KEY=value`;
- shell command substitution.

`load_environment(env_file, environ)` returns a merged mapping where `environ` wins over `.env`.

Secrets must not be printed by default. Error messages can name missing keys but must not print values.

## Database Wiring

`db/connection.py` provides a small connection factory:

- `PostgresConnectionFactory(database_url: str)`;
- `connect()` opens a new `psycopg` connection;
- `connection()` is a context manager that yields a connection, commits on success, rolls back on failure, and closes in all cases.

The existing migration and repository modules keep accepting DB-API-like connections. They should not import `psycopg` directly.

## Migrate CLI

`telegram-ai-assistant migrate`:

1. Loads `.env` and shell environment.
2. Builds `Settings`.
3. Opens a Postgres connection.
4. Applies `schema.sql` through `apply_schema(connection)`.
5. Commits and closes.
6. Prints a short success message.
7. Returns exit code `0`.

On connection or migration failure:

- rollback is attempted if a connection exists;
- connection is closed;
- a concise error is printed;
- exit code is non-zero.

The command does not create a database. If the database does not exist, the user must create it first.

## Health CLI

`telegram-ai-assistant health --offline` keeps existing no-network behavior.

`telegram-ai-assistant health` runs online checks:

- Postgres: connect and execute `SELECT 1`.
- LM Studio: call an OpenAI-compatible models endpoint at `${LM_STUDIO_BASE_URL}/models`.

The output is JSON with:

- overall status: `ok`, `degraded`, or `down`;
- component entries with name, status, and details.

Health checks must use injectable transports/factories in tests and must not require live Postgres or LM Studio during the normal unit test suite.

## AppContext

`AppContext` is a lightweight dataclass/factory object. It owns:

- `settings`;
- `connection_factory`;
- repository factory methods;
- migration runner;
- health checker factory.

It should be easy to build from:

- explicit settings for tests;
- loaded environment for CLI.

The context should not open external connections during construction. Connections open only when commands or runners request them.

## Testing Strategy

All implementation follows TDD.

Required tests:

- `.env` parser handles comments, empty lines, quotes, missing files, and shell env overrides.
- `Settings` can be built from merged environment.
- Postgres connection factory calls injected `connect` with `DATABASE_URL`.
- Connection context commits on success, rolls back on failure, and always closes.
- `migrate` CLI applies schema, commits, closes, and returns success with fake connection.
- `migrate` CLI returns non-zero on connection/migration errors.
- online `health` reports Postgres and LM Studio `ok` using fakes.
- online `health` reports `down` when a fake component fails.
- offline `health` remains unchanged.

Manual verification:

- Create a local Postgres database.
- Run `telegram-ai-assistant migrate`.
- Run `telegram-ai-assistant health` with LM Studio available.

## Non-Goals

- Creating Postgres databases.
- Running live Telegram ingestion.
- Running live Bot API polling.
- Running worker polling loops.
- Running scheduler loops.
- Launchd or systemd service files.
- Executing the manual unread smoke test.
- Adding external `.env` dependencies.

## Next Slices

After this feature, the next practical choices are:

- live worker loop using Postgres repositories;
- live Telegram ingestion loop;
- live Bot API polling loop.
