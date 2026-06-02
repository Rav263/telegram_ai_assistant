# Live Telegram Ingestor Design

Date: 2026-06-02

## Goal

Add the first live Telegram ingestion path for the owner account. The ingestor runs in a deliberately narrow one-shot mode: connect to Telegram through the read-only adapter, read new text messages from one configured chat, persist them to Postgres, update the chat ingestion cursor, and exit.

This slice is designed to validate the riskiest product requirement: reading Telegram messages without marking them as read in the owner's normal Telegram interface.

## Core Decisions

- Start with a single allowlisted chat id for the first real-account smoke test.
- Keep `run ingestor` as a one-shot command for this slice.
- Store ingestion cursor state on the `chats` table.
- Use `last_ingested_message_id` as the source of truth for `iter_new_messages(..., min_id=...)`.
- Update the cursor only after messages are normalized and persisted successfully.
- Keep the personal Telegram account read-only. The ingestor must not send, edit, delete, react, mark read, or acknowledge reads.
- Continue processing only text and caption content. Media parsing remains out of scope.
- Keep the unread guarantee as a manual external smoke test because Telegram read state cannot be proven with unit tests alone.

## Settings

Add live ingestor settings to `Settings.from_env`:

- `TELEGRAM_SESSION_PATH`: required path/name for the Telethon session used by the owner account.
- `TELEGRAM_INGEST_ACCOUNT_ID`: required local account id used in Postgres, for example `owner`.
- `TELEGRAM_INGEST_CHAT_ID`: required Telegram chat id for the one-shot smoke run.
- `TELEGRAM_INGEST_LIMIT`: optional integer limit for one run, default `100`.

Existing Telegram API settings remain required:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

The session file and `.env` remain local secrets and must not be committed.

## Database Changes

Extend `chats` with ingestion state:

- `last_ingested_message_id BIGINT NOT NULL DEFAULT 0`
- `last_ingested_at TIMESTAMPTZ`
- `ingestion_error TEXT NOT NULL DEFAULT ''`

The cursor belongs to `(account_id, chat_id)`. This keeps the first single-chat flow aligned with the future multi-chat flow, where each chat can advance independently.

The existing `messages` uniqueness constraint on `(account_id, chat_id, telegram_message_id)` remains the idempotency boundary.

## Repository Changes

Add narrow repository methods around account, chat, and cursor state:

- `AccountRepository.ensure_account(account_id, telegram_user_id=None, display_name='')`
- `ChatRepository.ensure_chat(account_id, chat_id, title='', chat_type='')`
- `ChatRepository.get_last_ingested_message_id(account_id, chat_id) -> int`
- `ChatRepository.update_ingestion_cursor(account_id, chat_id, last_message_id, ingested_at)`
- `ChatRepository.record_ingestion_error(account_id, chat_id, error_type)`

`MessageRepository.upsert_message(message)` remains the persistence path for normalized messages.

Repository methods should accept DB-API-like connections and stay easy to test with fakes.

## Ingestion Service

Add a service that coordinates one ingestion run:

```python
class Ingestor:
    async def run_once(self) -> IngestionRunResult:
        ...
```

Inputs:

- settings or explicit `account_id`, `chat_id`, and `limit`;
- read-only ingestion client factory;
- connection factory;
- normalizer function, defaulting to `normalize_telegram_message`.

Flow:

1. Open a Postgres transaction.
2. Ensure the account row exists.
3. Ensure the chat row exists.
4. Read `last_ingested_message_id` from `chats`.
5. Open the read-only Telegram client.
6. Call `iter_new_messages(chat_id, min_id=last_ingested_message_id, limit=limit)`.
7. Normalize each raw message into a domain `Message`.
8. Upsert each message.
9. Track the maximum `telegram_message_id` saved in this run.
10. Update the chat cursor only if at least one message was saved.
11. Close the Telegram client.
12. Commit the DB transaction.

If normalization or persistence fails, the transaction rolls back and the cursor is not advanced. If a Telegram connection or iteration failure happens before persistence completes, the command returns non-zero and records only a sanitized error type when possible.

## Runtime And CLI

`run ingestor` becomes the one-shot live ingestor for this slice.

Expected behavior:

- load `.env` and shell environment;
- build `AppContext`;
- build `TelethonIngestionAdapter` with `TELEGRAM_SESSION_PATH`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH`;
- run one ingestion pass for `TELEGRAM_INGEST_CHAT_ID`;
- print a concise result: saved count, skipped count if tracked, and latest cursor;
- return `0` on success and non-zero on failure;
- never print secrets, Telegram session contents, or full message text.

Long-running polling, all-dialog ingestion, blacklist handling, backfill, and worker triggering remain out of scope for this slice.

## Read-Only Boundary

The live path must use `TelethonIngestionAdapter` through `ReadOnlyIngestionClient`.

Allowed Telegram calls for this slice:

- connect/disconnect lifecycle;
- `iter_messages` through `iter_new_messages`;
- optionally `get_me` only if needed for metadata.

Disallowed Telegram calls include:

- `send_message`
- `send_read_acknowledge`
- `mark_read`
- edits, deletes, reactions, forwards, or any method that mutates account-visible state.

Unit tests should verify that the live ingestor path uses the read-only client interface and does not call mutating methods. The manual unread smoke test remains mandatory before broader account use.

## Error Handling

Failures are classified without leaking secret values or full message text:

- `config_error`: missing or invalid settings;
- `telegram_error`: connection or iteration failure;
- `normalization_error`: raw message shape cannot be normalized;
- `database_error`: transaction, schema, or repository failure.

On failure:

- return a non-zero exit code;
- close the Telegram client if it was opened;
- roll back the DB transaction if it was opened;
- leave `last_ingested_message_id` unchanged unless all saved messages in the transaction were committed;
- print only error class/type information.

## Testing Strategy

All implementation follows TDD.

Required automated tests:

- config tests for the new ingestor settings and defaults;
- schema test for new `chats` cursor columns;
- repository tests for ensuring account/chat rows and reading/updating cursor state;
- ingestion service test that reads the cursor, calls `iter_new_messages` with `min_id`, saves normalized messages, and updates cursor;
- ingestion service test that leaves cursor unchanged on normalization or DB failure;
- runtime/CLI test that `run ingestor` invokes the one-shot service and returns a useful exit code;
- read-only boundary test showing mutating Telegram calls are rejected before fake client execution;
- metadata test declaring the Telethon dependency or optional dependency needed for live ingestion.

Manual verification:

- create or migrate a local Postgres database;
- configure `.env` with the single controlled chat id;
- run `telegram-ai-assistant run ingestor`;
- verify the message is persisted;
- verify the normal Telegram UI still shows the controlled chat as unread;
- stop and rerun ingestor to confirm cursor idempotency.

## Operational Documentation

Update the local runbook with:

- new `.env` variables;
- Telethon session setup notes;
- one-shot ingestor command;
- expected output;
- safe rollback instructions.

Update the manual unread smoke checklist with:

- the exact `run ingestor` command;
- how to confirm the DB row was saved;
- how to confirm `last_ingested_message_id` advanced;
- what to do if the unread badge disappears.

## Non-Goals

- Backfill of the last 30 days.
- Long-running polling loop.
- Listening to all dialogs.
- Blacklist or allowlist management beyond one configured chat id.
- Secret chat support.
- Media download, OCR, transcription, or document parsing.
- Triggering the worker after ingestion.
- Bot commands for ingestion control.
- Systemd or launchd service files.

## Future Slices

After this slice passes the manual unread smoke test, the next practical steps are:

- polling mode for the same single-chat ingestor;
- multi-chat allowlist;
- all-dialog ingestion with blacklist controls;
- backfill integration using the same cursor model;
- worker triggering after committed message ingestion.
