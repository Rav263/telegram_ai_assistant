# Bot-Managed Backfill Design

Date: 2026-06-06

## Goal

Let the owner start bounded Telegram history imports from the bot without shell access, while preserving the existing read-only Telegram safety model and live ingestion cursors.

The first production slice supports one selected chat at a time. The owner chooses a chat from a paginated bot UI, chooses a lookback period, confirms the import, and the worker executes the persisted job in bounded batches.

## Current State

- Live update ingestion already saves new messages for allowed chats and keeps `chats.last_ingested_message_id` for live progress.
- `BackfillService.run_once(...)` can import one bounded history batch for one chat/date range without moving the live cursor.
- `/backfill` exists in the bot, but it is an MVP status/action surface and does not create real jobs.
- The worker currently processes candidate messages; it does not execute persisted backfill jobs.
- `chats` stores chat metadata such as title and chat type, so the bot can list known chats without asking Telegram for every dialog in this slice.

## Scope

In scope:

- Bot-managed creation of persisted backfill jobs for one selected chat.
- Period buttons for `1`, `5`, `10`, `15`, `30`, and `90` days.
- Paginated chat picker with 6 chats per page, displaying chat names.
- Previous and next page buttons.
- Confirmation before launching a job.
- Worker execution of one bounded backfill batch per cycle.
- Job status reporting and cancellation from the bot.
- Tests first for repositories, bot flow, worker runner, and wiring.

Out of scope:

- All-dialog backfill.
- Secret chats.
- Media extraction beyond the existing text/caption path.
- Live Telegram dialog discovery from the bot command.
- Automatic retries with backoff. The first slice can mark a job `failed` and expose sanitized diagnostics.
- Reordering candidate extraction priority after a backfill batch.

## Chat Eligibility

The bot lists known chats from the local `chats` table. A chat is eligible when it matches the same ingestion policy used by the listener:

- private chats, basic groups, and supergroups are eligible by default;
- broadcast channels are eligible only when explicitly allowlisted;
- denylisted chats are never shown;
- unknown or secret chat types are not shown.

This keeps manual backfill aligned with the live ingestion safety policy and prevents the bot from becoming a separate path around the denylist.

## Bot UX

`/backfill` opens a compact control surface:

1. Choose period: `1d`, `5d`, `10d`, `15d`, `30d`, `90d`.
2. Choose chat: list 6 eligible chats by display name.
3. Use previous and next buttons to page through chats.
4. Confirm: show chat name, period, calculated UTC date range, and current active job count for that chat.
5. Launch or cancel.

After launch, the bot returns the job id and status. The same surface exposes:

- latest jobs;
- job progress with saved count and date range;
- cancel action for `pending` and `running` jobs;
- sanitized error summary for `failed` jobs.

No raw Telegram message text should be shown in backfill status or error messages.

## Callback Model

Telegram callback data is short, so callbacks must store only compact routing state:

- `bf:d:{days}` selects a period;
- `bf:p:{days}:{page}` opens a chat page for a period;
- `bf:c:{days}:{page}:{chat_id}` selects a chat;
- `bf:confirm:{days}:{chat_id}` shows confirmation;
- `bf:start:{days}:{chat_id}` creates the persisted job;
- `bf:cancel:{job_id}` requests cancellation;
- `bf:status:{job_id}` shows one job.

Chat titles, date ranges, and job details are reloaded from the database when handling the callback. This avoids oversized callback payloads and stale title copies.

## Data Model

Extend the persisted `backfill_jobs` storage so the bot and worker can coordinate through Postgres:

- `id`: database job id;
- `account_id`: owner account, initially `owner`;
- `chat_id`: Telegram chat id;
- `chat_title`: snapshot for display;
- `from_date`: inclusive lower bound;
- `to_date`: exclusive upper bound;
- `status`: `pending`, `running`, `completed`, `cancel_requested`, `cancelled`, or `failed`;
- `next_before_message_id`: cursor for older history pages;
- `saved_count`: cumulative saved/upserted messages;
- `last_error_type`: sanitized exception class or domain error code;
- `last_error_metadata`: safe JSON metadata without raw message text or secrets;
- `created_at`, `started_at`, `finished_at`, `updated_at`.

The repository layer should provide explicit operations:

- list eligible chats for bot pagination;
- create a pending backfill job;
- list latest jobs for the owner;
- request cancellation;
- claim the next pending, running, or cancel-requested job for worker execution;
- update progress after a batch;
- mark completed, cancelled, or failed.

Claiming must be transaction-safe so two worker instances do not execute the same job concurrently.

## Runtime Flow

The bot only manages jobs. It never opens the Telegram user session and never imports history directly.

The worker loop adds a backfill step after the existing candidate-processing step:

1. Claim one `pending`, resumable `running`, or `cancel_requested` backfill job.
2. If the job is `cancel_requested`, mark it `cancelled` and stop.
3. Run one bounded `BackfillService` batch using `chat_id`, `from_date`, `to_date`, and `next_before_message_id`.
4. Add `saved_count` to the job total.
5. If the service returns a new `next_before_message_id`, keep the job `running`.
6. If no next cursor remains, mark the job `completed`.
7. On safe domain errors or unexpected exceptions, store sanitized diagnostics and mark the job `failed`.

Backfill continues to use read-only Telegram history retrieval and must not update `chats.last_ingested_message_id`.

## Safety And Privacy

- The Telegram user client remains behind the existing read-only guard.
- Backfill must not mark messages as read.
- Backfill status and logs must not include raw message text, captions, API hashes, bot tokens, session paths, or database URLs.
- Bot access remains owner-only.
- Cancellation is cooperative: a running batch finishes its current bounded page, then the next worker cycle observes `cancel_requested`.

## TDD Plan

Implementation must start with failing tests:

- Schema/repository tests for job columns, create/list/page/cancel/claim/progress/terminal states.
- Chat pagination tests proving 6 chats per page and ingestion-policy filtering.
- Bot service tests for period buttons, chat pages, previous/next buttons, confirmation, job creation, status, and cancellation.
- Worker runner tests for one-batch execution, continuation cursor, completion, cancellation, and sanitized failure handling.
- App context/runtime tests proving the worker is wired with the backfill job repository and service factory.
- Operations docs tests covering bot-managed backfill usage and Docker runtime behavior.

The full verification command remains:

```bash
env PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

## Operations

Docker production runtime should not need a new process. The existing `app-worker` container runs persisted backfill jobs as part of its poll cycle.

Operational notes to document during implementation:

- start with `docker compose up -d postgres app-listener app-worker app-bot`;
- use `/backfill` in the bot to create jobs;
- use `/logs` for sanitized runtime errors;
- use `/health` to confirm Postgres, LM Studio, listener, worker, and bot status;
- do not remove `~/.telegram/telegram_ai_assistant/postgres` unless intentionally deleting the local database.

## Future Work

- Live dialog discovery and manual refresh of the chat list.
- All-dialog backfill with global progress.
- Retry policy for transient Telegram/network failures.
- Backfill-specific rate limiting and pause/resume controls.
- Bot filters by chat type or search query when the known chat list becomes large.
