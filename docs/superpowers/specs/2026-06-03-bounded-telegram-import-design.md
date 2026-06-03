# Bounded Telegram Import Design

Date: 2026-06-03

## Goal

Make live Telegram ingestion safe by default: first runs import only a bounded recent window instead of walking a whole chat from the beginning, and smoke tests can explicitly start from the current chat tail without importing old messages.

## Core Decisions

- Keep `run ingestor` as a one-shot single-chat command for this slice.
- Preserve per-chat cursor semantics: when `last_ingested_message_id > 0`, ingestion reads only messages newer than that cursor.
- Add an initial bootstrap mode used only when the chat cursor is empty.
- Default bootstrap mode is `recent`, importing messages newer than `now - TELEGRAM_INGEST_BOOTSTRAP_DAYS`.
- Default bootstrap window is 30 days.
- Add `start_now` mode for controlled smoke tests and backlog skipping. It sets the cursor to the current latest message id and saves no messages, even if the chat already has an older cursor.
- Keep old-history import outside live ingestion. Older ranges remain a backfill concern.
- Keep the Telegram account read-only; new client operations must remain retrieval-only.
- Extend result JSON with optional date bounds so debug output shows the imported period without requiring message text.

## Settings

Add optional settings:

- `TELEGRAM_INGEST_BOOTSTRAP_MODE`: `recent`, `start_now`, or `cursor`; default `recent`.
- `TELEGRAM_INGEST_BOOTSTRAP_DAYS`: positive integer; default `30`.

Mode behavior:

- `recent`: call the read-only client for messages newer than `now - bootstrap_days`, up to `TELEGRAM_INGEST_LIMIT`, in oldest-to-newest order.
- `start_now`: read the latest message id only, update the cursor to that id, save no messages, and exit successfully. This mode is explicit override behavior and applies even when the cursor is non-zero.
- `cursor`: keep the previous behavior for explicit troubleshooting: call new-message ingestion with `min_id=0`.

When the cursor is non-zero, `recent` and `cursor` use regular cursor ingestion.

## Client Port

Extend `IngestionClient` with retrieval-only methods:

- `iter_recent_messages(chat_id, since, limit)` returns messages after `since`, oldest first.
- `get_latest_message_id(chat_id)` returns the newest visible message id, or `0` if the chat has no messages.

`ReadOnlyIngestionClient` implements these through Telethon retrieval methods:

- recent import: `iter_messages(chat_id, limit=limit, offset_date=since, reverse=True)`;
- latest id: `get_messages(chat_id, limit=1)` or equivalent read-only retrieval.

These calls are non-mutating and remain behind `ReadOnlyTelegramGuard`.

## Ingestor Flow

1. Open a database transaction.
2. Ensure account and chat rows exist.
3. Read the chat cursor.
4. Open the read-only Telegram client.
5. Select ingestion behavior:
   - `start_now`: fetch latest id and update cursor without saving messages.
6. If cursor is empty, select bootstrap behavior:
   - `recent`: iterate recent messages since the cutoff.
   - `cursor`: iterate new messages with `min_id=0`.
7. If cursor is non-empty, iterate new messages with `min_id=cursor`.
8. Normalize and upsert each message.
9. Track saved count, latest message id, oldest timestamp, and newest timestamp.
10. Update the cursor only after the selected operation succeeds.
11. Close the Telegram client.

For `recent`, if no messages are found, the cursor stays unchanged because there is no reliable latest id from the recent iterator. Operators can use `start_now` when they want to mark a baseline explicitly or skip an already discovered backlog.

## Runtime Output

The default JSON result continues to include:

- `account_id`
- `chat_id`
- `requested_min_id`
- `saved_count`
- `latest_message_id`

Add:

- `bootstrap_mode`
- `oldest_sent_at` when at least one message was saved
- `newest_sent_at` when at least one message was saved

`debug_messages` remains opt-in through `TELEGRAM_INGEST_DEBUG_MESSAGES=true`.

## Non-Goals

- No all-dialog ingestion in this slice.
- No bot command for backfill control in this slice.
- No automatic older-than-30-days import.
- No worker triggering after ingestion.
- No schema changes; existing chat cursor columns are enough.

## Testing Strategy

All implementation follows TDD.

Required tests:

- config tests for bootstrap mode and days defaults and validation;
- port tests for `iter_recent_messages` and `get_latest_message_id`;
- app context test proving bootstrap settings are passed into `LiveIngestor`;
- live ingestor test for recent bootstrap using a cutoff date;
- live ingestor test for `start_now` updating cursor without saving messages from empty and non-empty cursors;
- live ingestor test proving non-zero cursor ignores bootstrap and uses normal cursor ingestion;
- runtime payload test for `bootstrap_mode`, `oldest_sent_at`, and `newest_sent_at`;
- docs tests updated for the new environment variables.
