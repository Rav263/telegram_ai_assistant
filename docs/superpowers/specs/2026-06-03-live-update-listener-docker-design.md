# Live Update Listener And Docker Runtime Design

Date: 2026-06-03

## Goal

Add a long-running Telegram live update listener that saves new messages from the owner's account as updates arrive, while preserving the existing read-only safety guarantees. Package the application in a production-oriented Docker image and compose setup so the listener can run continuously while development continues.

## Core Decisions

- Add a separate runtime process: `run listener`.
- Keep `run ingestor` as one-shot catch-up by cursor.
- Keep `run backfill` as explicit historical import by date range.
- The listener subscribes to Telethon `NewMessage` updates and saves accepted messages immediately.
- Listener scope is all regular chats by default, excluding broadcast channels unless explicitly allowed.
- Denylist always wins over default inclusion and channel allowlist.
- Secret chats remain unsupported.
- Docker packaging uses one application image and multiple commands/services, not an in-container process supervisor.
- LM Studio remains outside Docker for now and is configured by URL.

## Chat Scope Policy

The listener evaluates every incoming Telegram update with a single policy:

- Private chats are readable by default.
- Basic groups are readable by default.
- Supergroups are readable by default.
- Broadcast channels are not readable by default.
- Broadcast channels are readable only when their chat id is in `TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS`.
- Any chat id in `TELEGRAM_LISTENER_DENIED_CHAT_IDS` is rejected regardless of type or allowlist membership.

Telethon can represent supergroups as channel-like entities, so the implementation must distinguish `megagroup=True` from `broadcast=True`. Supergroups must not be blocked merely because their entity class is channel-like.

## Settings

Add optional listener settings:

- `TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS`: comma-separated Telegram chat ids for broadcast channels that may be read.
- `TELEGRAM_LISTENER_DENIED_CHAT_IDS`: comma-separated Telegram chat ids that must never be read.

The listener uses existing Telegram and database settings:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_PATH`
- `TELEGRAM_INGEST_ACCOUNT_ID`
- `DATABASE_URL`

The bot owner setting and LM Studio URL remain available for other processes but are not listener-specific.

## Listener Flow

`LiveUpdateListener.run_forever()` coordinates the long-running process:

1. Connect through the existing Telethon adapter behind the read-only guard.
2. Subscribe to new message updates.
3. For each update, extract the raw Telegram message and chat metadata.
4. Evaluate `ChatIngestionPolicy`.
5. If rejected, skip without saving.
6. Ensure the account and chat rows exist.
7. Normalize the message through the existing `normalize_telegram_message`.
8. Upsert the message with `MessageRepository.upsert_message`.
9. Update `chats.last_ingested_message_id` to the max of the current cursor and saved message id.
10. Continue until the process is interrupted or the Telegram client disconnects.

The listener should not print message text by default. Debug message output can be added later if needed, but it is not required for the first listener slice.

## Read-Only Safety

The new adapter surface must only register event handlers and receive updates. It must remain behind `ReadOnlyTelegramGuard`, and tests must prove mutating methods such as `send_message`, `send_read_acknowledge`, and `mark_read` are not used.

Receiving updates is acceptable because it does not intentionally mark messages read in the main Telegram interface. The existing manual unread smoke test remains the safety check before broad use.

## Reliability Model

The first listener slice provides real-time saving while the process is online. It does not attempt a startup catch-up internally.

Catch-up remains a separate workflow:

- Run `run ingestor` to catch up a configured chat by cursor.
- Run `run backfill` for explicit older date ranges.
- Later scheduler work can run catch-up across known chats.

This separation keeps the listener simple and avoids hidden history scans on startup.

## Runtime Output

`run listener` is long-running. On startup it should print a small JSON status payload such as:

- `process`
- `account_id`
- `allowed_channel_count`
- `denied_chat_count`
- `status`

Per-message logs should avoid text and secrets. If per-message operational logging is added, it should include ids and status only.

## Docker Runtime

Add production packaging:

- `Dockerfile` builds a Python 3.11 application image.
- `.dockerignore` excludes local virtualenvs, git metadata, caches, worktrees, local sessions, and editor files.
- `docker-compose.yml` defines:
  - `postgres`;
  - `app-listener`, running `telegram-ai-assistant run listener`;
  - a persistent app volume or bind mount for Telegram session files;
  - env loading through `.env`.

The same image supports one-shot operational commands:

```bash
docker compose run --rm app-listener telegram-ai-assistant migrate
docker compose run --rm app-listener telegram-ai-assistant run backfill
docker compose run --rm app-listener telegram-ai-assistant health
```

On macOS, LM Studio can be reached from Docker with:

```bash
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1
```

On Linux, the operator must set `LM_STUDIO_BASE_URL` to a reachable host address.

## Non-Goals

- No worker, bot, or scheduler Docker services in this slice.
- No in-container supervisor.
- No bot commands for managing listener allow/deny lists.
- No persisted database table for listener policy.
- No startup catch-up across all dialogs.
- No media downloads, OCR, or attachment extraction.
- No secret chat support.

## Testing Strategy

All implementation follows TDD.

Required tests:

- settings parse comma-separated listener allow/deny ids and reject malformed ids;
- chat policy accepts private chats, basic groups, and supergroups by default;
- chat policy rejects broadcast channels unless allowlisted;
- chat policy denylist overrides all other rules;
- read-only adapter can register and receive update events without mutating calls;
- listener service saves accepted messages and advances cursor;
- listener service skips denied chats and unallowed broadcast channels;
- runtime dispatch includes `listener`;
- CLI parses `run listener`;
- Docker files are present and document the listener command.
