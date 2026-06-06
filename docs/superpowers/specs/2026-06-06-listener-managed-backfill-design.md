# Listener-Managed Backfill Design

Date: 2026-06-06

## Goal

Move bot-managed Telegram backfill execution out of `app-worker` and into `app-listener` so only one process owns the Telethon user session. This avoids SQLite session lock failures while preserving the existing bot UX, persisted `backfill_jobs`, read-only Telegram guard, and worker pipeline for filtering and LLM extraction.

## Problem

The current bot-managed backfill implementation stores jobs in Postgres, but `app-worker` claims and executes those jobs. In Docker production, both `app-listener` and `app-worker` use the same `TELEGRAM_SESSION_PATH`. The listener keeps a long-lived Telethon client open for live updates, while the worker opens a second Telethon client for backfill batches. Telethon sessions are SQLite-backed, so concurrent access can fail with `OperationalError`.

Stopping the listener while backfill runs is a workable manual workaround, but it breaks live ingestion during imports and makes the production runtime fragile.

## Current State

- `app-listener` is the long-lived Telegram session owner and handles live `NewMessage` updates.
- `app-worker` processes saved messages, scores candidates, calls LM Studio, writes extracted items, and currently also runs persisted backfill jobs.
- `backfill_jobs` already stores chat id/title, date range, status, cursor, saved count, and sanitized error type/metadata.
- The bot creates and manages backfill jobs but never opens the Telegram user session.
- `/logs` can show sanitized `runtime_events`, but backfill job failures currently only update `backfill_jobs.last_error_type`.

## Decision

`app-listener` becomes the only runtime that executes Telegram history reads for persisted backfill jobs.

The listener will:

- connect one Telethon client;
- register live update handlers as it does today;
- run a cooperative background backfill loop using the same connected client;
- execute at most one bounded backfill batch per poll;
- write progress back to `backfill_jobs`;
- continue to save live updates while backfill work is idle or between bounded batches.

`app-worker` will no longer claim or execute `backfill_jobs`. It remains responsible for message scoring, LLM extraction, item persistence, review queue processing, and status-change extraction.

## Scope

In scope:

- Listener-managed execution of existing persisted backfill jobs.
- Reusing one connected read-only Telegram client for live updates and backfill batches.
- Removing backfill execution from `Worker`.
- Recording sanitized backfill failure events in `runtime_events`.
- Keeping existing `/backfill` bot controls and `backfill_jobs` schema.
- Updating Docker/runbook docs to state that `app-listener` must be a singleton.
- TDD coverage for listener loop, app context wiring, worker behavior, runtime output, and safe diagnostics.

Out of scope:

- Multiple Telegram user accounts.
- Multiple listener replicas.
- A separate backfill-only Telegram session.
- Automatic retry scheduling beyond the existing job status model.
- Media/content extraction beyond the current text/caption path.
- Changing the bot backfill UX.

## Architecture

Add a listener-side backfill component with a small interface:

- claim one job from `BackfillJobRepository`;
- execute one bounded history batch using an already connected `IngestionClient`;
- persist messages through the existing repositories;
- update progress, completion, cancellation, or failure state.

The existing `BackfillService` should be refactored so the history import core can accept an externally owned client. The current one-shot CLI backfill path may keep using a convenience wrapper that creates and closes its own client. Listener-managed backfill must not close the listener's shared client after a batch.

The listener loop should avoid blocking forever inside a separate worker loop. It should run live update registration and then periodically poll backfill jobs while the Telethon client remains connected. A small async task or cooperative scheduler is acceptable, but the implementation must keep tests deterministic by allowing injected sleep/stop hooks.

## Data Flow

1. Owner uses `/backfill` in the bot.
2. Bot creates a `backfill_jobs` row with `pending` status.
3. `app-listener` polls for `pending`, resumable `running`, or `cancel_requested` jobs.
4. If the job is `cancel_requested`, listener marks it `cancelled` without reading Telegram.
5. Listener runs one bounded batch with `chat_id`, `from_date`, `to_date`, `next_before_message_id`, and configured batch limit.
6. Each normalized message is upserted into `messages`; live cursors are not moved.
7. Listener updates `saved_count` and `next_before_message_id`.
8. Listener marks the job `completed` when the batch returns no continuation cursor or no further messages in range.
9. Worker later processes the newly saved messages through the existing candidate and LLM pipeline.

## Concurrency Model

Only one `app-listener` instance is supported. This must be documented as an operational invariant because the listener owns the Telegram session and claims backfill jobs.

Postgres row locking in `BackfillJobRepository.claim_next_job()` still remains useful. It protects against accidental duplicate execution if two listener instances are started, but it is not a license to scale listeners horizontally because the Telethon session remains single-owner.

Backfill batches stay bounded by `WORKER_BATCH_SIZE` or a listener-specific batch setting if implementation proves that a separate setting is cleaner. Bounded batches keep live updates responsive and make cancellation cooperative.

## Error Handling And Diagnostics

On backfill failure, listener must:

- mark the job `failed`;
- set `last_error_type`;
- store only safe `last_error_metadata`;
- record a `runtime_events` row with `component=listener`, `severity=warning`, `event_type=backfill_failed`, and metadata containing `job_id`, `chat_id`, `error_type`, and allowlisted safe details.

Logs and bot responses must not include raw Telegram message text, captions, API hashes, bot tokens, database URLs, or session paths.

`/logs` should become useful for this failure class without exposing secrets. A failed job detail can continue showing the short `Error: OperationalError` line, while `/logs` provides safe context such as `job_id=1 chat_id=... error_type=OperationalError`.

## Runtime And Operations

Docker keeps the same three long-lived app processes:

- `app-listener`: live Telegram updates and backfill job execution;
- `app-worker`: filtering, candidate processing, LLM extraction, and item/review persistence;
- `app-bot`: owner-only bot commands and inline buttons.

Operational rules:

- do not scale `app-listener` above one replica;
- do not run manual `telegram-ai-assistant run backfill` while listener is active against the same session;
- run migrations after deploy because existing backfill schema must be present;
- do not use `docker compose down -v`;
- backfill progress is observed through `/backfill`, `/logs`, and `docker compose logs app-listener`.

## TDD Plan

Implementation must start with failing tests:

- Listener tests proving a pending backfill job is claimed and executed through the existing connected client.
- Listener tests proving live update handler registration still happens.
- Listener tests proving cancel-requested jobs are cancelled without Telegram reads.
- Listener tests proving failures mark the job failed and write a safe `runtime_events` entry.
- Backfill service tests for an externally owned client path that does not close the shared client.
- Worker tests proving worker no longer runs persisted backfill jobs.
- App context tests proving `run_listener_forever` wires the backfill repository/runner and `run_worker_once` does not.
- Runtime tests updating worker output expectations if backfill counters are removed or fixed at zero.
- Operations docs tests documenting listener-owned backfill and singleton listener deployment.

Verification command:

```bash
env PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

## Migration Strategy

No new database columns are required for the first slice. The existing `backfill_jobs` and `runtime_events` tables are enough. If implementation discovers a need for a separate listener-specific setting, prefer environment configuration over schema changes.

Deployment sequence:

1. Deploy code.
2. Run `telegram-ai-assistant migrate`.
3. Recreate `app-listener`, `app-worker`, and `app-bot`.
4. Ensure only one `app-listener` is running.
5. Retry failed backfill jobs by setting them back to `pending` or creating a new job from the bot.

## Rejected Alternatives

Separate backfill Telegram session: avoids SQLite locks, but requires a second account authorization flow and another session file to protect.

File lock around Telethon session: does not solve the long-lived listener case because the listener may hold the session for the whole process lifetime.

Stopping listener during backfill: useful as a manual recovery path, but live ingestion pauses and operations become brittle.

Keeping backfill in worker: preserves the current code shape, but keeps the root cause of session lock failures.

## Acceptance Criteria

- Creating a bot-managed backfill job no longer requires stopping `app-listener`.
- Backfill batches are executed by `app-listener` using the already connected Telegram client.
- `app-worker` no longer opens Telegram for persisted backfill jobs.
- A failed backfill job writes safe diagnostics visible through `/logs`.
- Existing bot backfill controls continue to work.
- Existing live update ingestion continues to work.
- Full test suite passes.
