# One-Shot Backfill Design

Date: 2026-06-03

## Goal

Add a first production-usable backfill slice that imports older Telegram history for one configured chat and date range without changing the live ingestion cursor.

## Core Decisions

- Backfill is separate from live ingestion.
- Backfill never updates `chats.last_ingested_message_id`.
- Backfill saves normalized messages through `MessageRepository.upsert_message`, so duplicate imports are idempotent.
- The first slice is one-shot and CLI-driven through `run backfill`.
- The first slice uses one chat id from settings, not all dialogs.
- The first slice uses explicit ISO datetime bounds.
- Backfill progress uses its own cursor: `before_message_id`.
- Telegram access stays read-only and uses history retrieval only.
- Bot-driven `/backfill` remains future work; the bot can later wrap this service.

## Settings

Add optional required-for-backfill settings:

- `TELEGRAM_BACKFILL_CHAT_ID`: Telegram chat id to import.
- `TELEGRAM_BACKFILL_START_AT`: inclusive lower datetime bound, ISO 8601.
- `TELEGRAM_BACKFILL_END_AT`: exclusive upper datetime bound, ISO 8601.
- `TELEGRAM_BACKFILL_LIMIT`: maximum messages to inspect in one run, default `500`.

The command still uses existing account and Telegram session settings:

- `TELEGRAM_INGEST_ACCOUNT_ID`
- `TELEGRAM_SESSION_PATH`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

## Client Port

Add a read-only history method for date-range backfill:

```python
iter_backfill_messages(chat_id, start_at, end_at, before_message_id, limit)
```

The Telethon-backed read-only client implements it with `iter_messages`:

- `offset_date=end_at` to walk messages older than the end bound;
- `max_id=before_message_id` when resuming older pages;
- `reverse=False` so results are newest-to-oldest;
- local stop when `message.date < start_at`.

This method only retrieves history and remains behind `ReadOnlyTelegramGuard`.

## Service Flow

`BackfillService.run_once()` coordinates one configured run:

1. Open a database transaction.
2. Ensure the account and chat rows exist.
3. Open the read-only Telegram client.
4. Call `iter_backfill_messages(...)`.
5. Normalize each raw message.
6. Upsert each message.
7. Track saved count, oldest/newest timestamps, latest imported id, and next `before_message_id`.
8. Close the Telegram client.
9. Commit the transaction.
10. Return a JSON-safe result.

The service does not create a persisted `backfill_jobs` row in this first slice. It reports `next_before_message_id`, which the operator can feed into a future persisted job flow. The existing `BackfillJob` model remains the direction for the later bot/scheduler implementation.

## Runtime Output

`run backfill` prints JSON:

- `account_id`
- `chat_id`
- `start_at`
- `end_at`
- `requested_before_message_id`
- `next_before_message_id`
- `saved_count`
- `oldest_sent_at`
- `newest_sent_at`

No message text is printed by default.

## Non-Goals

- No all-dialog backfill.
- No bot `/backfill` command implementation.
- No persisted backfill job repository.
- No scheduler integration.
- No worker trigger after imported messages.
- No media download or OCR.

## Testing Strategy

All implementation follows TDD.

Required tests:

- settings parse valid backfill values and reject malformed date ranges;
- read-only client calls Telethon history retrieval with safe parameters and stops at `start_at`;
- backfill service saves normalized messages and does not update live cursor;
- runtime dispatch includes `backfill`;
- CLI `run backfill` prints result JSON without message text;
- runbook documents the new settings and command.
