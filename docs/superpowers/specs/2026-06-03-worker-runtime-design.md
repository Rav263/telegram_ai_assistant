# Worker Runtime Design

## Goal

Make the worker a production runtime process that turns stored Telegram messages into candidates, extracted items, review entries, and safe operational logs. The listener and backfill already persist messages; this slice makes those messages useful before the full bot runtime is implemented.

## Commands

`telegram-ai-assistant run worker --once` runs one cycle and exits. It is the primary manual/debug mode and prints a JSON result with counts.

`telegram-ai-assistant run worker` runs as a daemon. It repeatedly executes the same cycle, sleeps for `WORKER_POLL_INTERVAL_SECONDS`, logs sanitized counts, and exits cleanly on interrupt or termination.

The worker uses these settings:

- `WORKER_BATCH_SIZE`, default `25`.
- `WORKER_POLL_INTERVAL_SECONDS`, default `10`.
- `WORKER_ITEM_AUTO_APPLY_THRESHOLD`, default `0.8`.
- `WORKER_STATUS_AUTO_APPLY_THRESHOLD`, default `0.8`.

## Processing Flow

One worker cycle has two stages.

First, candidate filtering reads pending messages from `messages`, applies the existing `score_message` filter, writes positive-score rows to `message_candidates`, and records that every inspected message passed the `candidate_filter` stage.

Second, LLM extraction reads queued candidate messages, calls LM Studio through the existing `ExtractionService`, saves high-confidence extracted items, sends low-confidence items to review, records low-confidence status changes for review, and marks candidates processed only after all persistence succeeds.

The existing `Worker` class remains the domain pipeline. This slice adds production repository adapters and runtime orchestration around it.

## Processing State

Add `message_processing_state`:

```sql
CREATE TABLE IF NOT EXISTS message_processing_state (
    account_id TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, chat_id, telegram_message_id, stage)
);
```

The first supported stage is `candidate_filter`. Messages with score `0` are still marked `processed` for this stage so they are not rescored forever.

`message_candidates.status='queued'` remains the retry queue for LLM extraction. On successful persistence, candidates are marked `processed`. On LLM failure, candidates stay `queued` so the daemon can retry later.

## Review Queue

Extend `review_queue` to support both item review and status-change review:

```sql
ALTER TABLE review_queue
    ADD COLUMN IF NOT EXISTS review_type TEXT NOT NULL DEFAULT 'item';

ALTER TABLE review_queue
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::JSONB;

ALTER TABLE review_queue
    ALTER COLUMN item_id DROP NOT NULL;
```

For item review, `review_type='item'` and `item_id` references the candidate item. For status-change review, `review_type='status_change'`, `item_id` may be null, and the sanitized change is stored in `payload`.

## Runtime Events And Bot Logs

Add `runtime_events`:

```sql
CREATE TABLE IF NOT EXISTS runtime_events (
    runtime_event_id BIGSERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Worker, listener, and bot code can record safe operational events. This slice records worker errors and LLM failures first.

Add a bot-facing service method and command mapping for `/logs`. The command returns the latest 10 warning/error runtime events in a compact text format. It must not include Telegram message text, LLM prompt text, bot tokens, API hashes, database URLs, raw exception messages, or raw tracebacks.

## Persistence Adapters

Add or extend repositories:

- `MessageProcessingRepository.pending_messages(limit)` returns messages without a processed `candidate_filter` state.
- `MessageProcessingRepository.mark_candidate_filter_processed(messages)` records successful candidate-filter processing.
- `MessageProcessingRepository.mark_candidate_filter_failed(message, error_type)` records per-message filter failures.
- `CandidateRepository.pending_candidate_messages(limit)` returns queued candidate source messages.
- `CandidateRepository.mark_processed(messages)` marks candidates processed.
- `ItemRepository.save_item(item)` upserts high-confidence extracted items.
- `ItemRepository.apply_status_change(change)` updates item status and writes `item_status_events`.
- `ReviewRepository.enqueue_item(item)` saves low-confidence items as `ItemStatus.CANDIDATE` and queues review.
- `ReviewRepository.enqueue_status_change(change)` writes a `review_type='status_change'` entry.
- `RuntimeEventRepository.record_event(...)` and `latest_events(...)` write and read safe events.
- `LLMRunRepository.record_failure(error)` writes a sanitized failure record with no prompt or message text.

## Error Handling

Candidate filtering failures are per-message. The worker records `candidate_filter` as `failed` with the exception type and continues with the rest of the batch.

LLM failures fail the whole candidate batch. The candidates stay `queued`, `llm_runs` records a sanitized failure, `runtime_events` records a warning/error, and the daemon retries in a later cycle.

Persistence failures roll back the transaction and do not mark candidates processed. Logs and runtime events contain ids, counts, component names, event types, and exception types only.

## Docker

Add an `app-worker` service to `docker-compose.yml` using the same image as `app-listener`:

```yaml
command: telegram-ai-assistant run worker
```

It depends on Postgres health and reads `.env`. Normal production startup runs `postgres`, `app-listener`, and `app-worker` together.

## Testing

Development remains TDD. Tests must cover:

- config parsing for worker settings;
- CLI `run worker --once` parsing;
- one-cycle runtime counts;
- daemon loop stop behavior without long sleeps;
- SQL schema additions and migration compatibility;
- repository SQL for pending messages, processing state, candidates, items, review queue, runtime events, and LLM failures;
- Docker Compose includes `app-worker`;
- privacy checks that runtime events/logs do not include Telegram text or raw exception messages.
