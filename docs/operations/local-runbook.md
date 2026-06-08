# Local Runbook

## Environment

Create a project-local Python environment:

```bash
uv venv .venv --python 3.11
```

Install the package and runtime dependencies:

```bash
uv pip install -e .
```

If `uv` is unavailable after creating the environment:

```bash
.venv/bin/python -m pip install -e .
```

Create a `.env` file or export these variables in the service environment:

```bash
TELEGRAM_API_ID=123
TELEGRAM_API_HASH=your-api-hash
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_BOT_PROXY_URL=
TELEGRAM_ALLOWED_USER_ID=123456
TELEGRAM_SESSION_PATH=.local/telegram-owner.session
TELEGRAM_INGEST_ACCOUNT_ID=owner
TELEGRAM_INGEST_CHAT_ID=123456789
TELEGRAM_MTPROXY_HOST=
TELEGRAM_MTPROXY_PORT=
TELEGRAM_MTPROXY_SECRET=
TELEGRAM_INGEST_LIMIT=100
TELEGRAM_INGEST_DEBUG_MESSAGES=false
TELEGRAM_INGEST_BOOTSTRAP_MODE=recent
TELEGRAM_INGEST_BOOTSTRAP_DAYS=30
TELEGRAM_BACKFILL_CHAT_ID=123456789
TELEGRAM_BACKFILL_START_AT=2022-01-01T00:00:00+00:00
TELEGRAM_BACKFILL_END_AT=2022-02-01T00:00:00+00:00
TELEGRAM_BACKFILL_LIMIT=500
TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS=
TELEGRAM_LISTENER_DENIED_CHAT_IDS=
DATABASE_URL=postgresql://localhost/telegram_ai_assistant
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=local-model
LM_STUDIO_MAX_TOKENS=1024
LM_STUDIO_CONTEXT_LENGTH=8192
BACKFILL_DAYS=30
TELEGRAM_DATA_DIR=${HOME}/.telegram/telegram_ai_assistant
WORKER_BATCH_SIZE=5
WORKER_OPEN_ITEM_CONTEXT_LIMIT=10
WORKER_POLL_INTERVAL_SECONDS=10
WORKER_ITEM_AUTO_APPLY_THRESHOLD=0.8
WORKER_STATUS_AUTO_APPLY_THRESHOLD=0.8
LOG_LEVEL=INFO
```

## Services

- Postgres stores messages, candidates, extracted items, status events, LLM action proposals in `llm_actions`, bot actions, and backfill jobs.
- LM Studio serves the local OpenAI-compatible LLM endpoint.
- `telegram-ai-assistant run ingestor` reads Telegram updates through the read-only ingestion adapter.
- `telegram-ai-assistant run listener` saves new Telegram messages from live updates.
- `telegram-ai-assistant run worker` processes candidates and extraction batches.
- `telegram-ai-assistant run bot` serves owner-only Telegram Bot API commands.
- `telegram-ai-assistant run scheduler` drives retries, backfill, and periodic processing.

## Logging

Set `LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. The default is `INFO`.

```bash
LOG_LEVEL=DEBUG PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run listener
```

Use `--log-level` to override `.env` for one command:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli --log-level debug run listener
```

Command result payloads stay on stdout. Application logs go to stderr, so JSON output can still be piped without mixing it with operational logs.

## Ingestor

For this release, `telegram-ai-assistant run ingestor` is a one-shot single-chat command for controlled unread smoke testing. It reads only `TELEGRAM_INGEST_CHAT_ID`, uses `last_ingested_message_id` from the `chats` table as the cursor, saves new messages, advances the cursor, and exits.

`TELEGRAM_INGEST_BOOTSTRAP_MODE` controls how the command behaves around existing history:

- `recent` imports only messages newer than `TELEGRAM_INGEST_BOOTSTRAP_DAYS` days ago, defaulting to 30 days.
- `start_now` moves the cursor to the current latest message without saving old messages. Use it to skip backlog even if the chat already has an older cursor.
- `cursor` preserves raw cursor behavior and starts from message id `0`.

After the cursor is non-empty, `recent` and `cursor` read only messages newer than `last_ingested_message_id`.

Run it only against a controlled non-secret chat until the manual unread smoke test passes:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run ingestor
```

The command prints JSON with `saved_count`, `requested_min_id`, `latest_message_id`, `bootstrap_mode`, and optional `oldest_sent_at`/`newest_sent_at` period bounds. It must not print message text, bot tokens, API hashes, database passwords, or Telegram session contents.

Set `TELEGRAM_INGEST_DEBUG_MESSAGES=true` only for local troubleshooting when you need the command output to include `debug_messages` with saved message IDs, sender IDs, direction, timestamp, text, and caption. Turn it back off after debugging so routine logs do not contain private message text.

## Listener

Use `telegram-ai-assistant run listener` for live update ingestion. It listens for new Telegram messages and saves accepted updates without intentionally marking messages read.

By default the listener reads private chats, basic groups, and supergroups. Broadcast channels are ignored unless their ids are listed in `TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS` or allowed through the owner-only bot. Any id in `TELEGRAM_LISTENER_DENIED_CHAT_IDS` is never read, and bot-managed deny overrides are also enforced.

On startup, after registering the live update handler, the listener catches up known chats that already have a non-zero `last_ingested_message_id`. It reads only messages newer than the stored cursor through the same read-only Telegram path and advances each chat cursor after saving. The per-chat startup catch-up batch size uses `TELEGRAM_INGEST_LIMIT`.

app-listener executes persisted backfill jobs created from `/backfill` with the already connected Telegram user session. Do not scale `app-listener` above one replica because the Telethon session is a singleton runtime resource.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run listener
```

Keep `run ingestor` available for controlled single-chat debugging, but normal missed-message recovery now happens inside `app-listener` on startup.

## Worker

Use `telegram-ai-assistant run worker --once` for local debugging. It reads pending stored messages, writes `message_candidates`, processes queued candidates through LM Studio, saves audited action proposals to `llm_actions`, applies only high-confidence `create_item` actions automatically, queues review-first non-create actions, and prints JSON counts.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run worker --once
```

Use `telegram-ai-assistant run worker` as the daemon process. It repeats the same cycle and sleeps for `WORKER_POLL_INTERVAL_SECONDS` between cycles.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run worker
```

Worker tuning variables:

- `WORKER_BATCH_SIZE` controls how many messages/candidates one cycle processes, defaulting to 5.
- `WORKER_OPEN_ITEM_CONTEXT_LIMIT` controls how many open items are included in each LLM prompt, defaulting to 10.
- `WORKER_POLL_INTERVAL_SECONDS` controls daemon sleep, defaulting to 10.
- `WORKER_ITEM_AUTO_APPLY_THRESHOLD` controls automatic item saving versus review, defaulting to 0.8.
- `WORKER_STATUS_AUTO_APPLY_THRESHOLD` controls automatic status updates versus review, defaulting to 0.8.

LLM extraction now proposes actions instead of directly mutating existing items. Supported action proposals include creating items, updating item status or fields, merging duplicates, scheduling notifications, and linking sources to existing items. User-facing task, reminder, review, and rationale text from the LLM must be Russian. The worker stores every proposal in `llm_actions` with source references, confidence, payload, state, and rationale before applying or routing it.

The initial policy is deliberately conservative: high-confidence `create_item` proposals may be applied automatically, while status changes, field edits, duplicate merges, notification scheduling, and source links go to review-first handling. Failed actions are marked failed instead of being retried blindly or hidden.

app-worker does not open the Telegram user session for backfill. It only processes messages already saved by the listener, ingestor, or explicit backfill command.

LLM failures and worker errors are recorded as sanitized runtime events. Ask the owner-only bot for `/logs` to see the latest warning/error runtime events without Telegram message text, raw prompts, bot tokens, API hashes, database URLs, or raw tracebacks.

For LM Studio connection failures, `/logs` may include safe technical fields such as `endpoint_scheme`, `endpoint_host`, `endpoint_path`, `http_status`, and `transport_error_type`. If Docker on macOS reports `endpoint_host=127.0.0.1`, set `LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1` in `.env` so the container reaches LM Studio on the host.

LM Studio must have a chat model available before the worker can extract items. Set `LM_STUDIO_MODEL` to the exact model id accepted by LM Studio. On worker startup, the app lists models through LM Studio's native `/api/v1/models` endpoint. If `LM_STUDIO_MODEL` is already loaded with `LM_STUDIO_CONTEXT_LENGTH`, it is reused. If the configured model is loaded with different parameters, the worker unloads that configured-model instance through `/api/v1/models/unload` and then loads it through `/api/v1/models/load` with `LM_STUDIO_CONTEXT_LENGTH`, defaulting to 8192. Other loaded models are not touched. `LM_STUDIO_MAX_TOKENS` is the completion budget, not the context length; keep it below `LM_STUDIO_CONTEXT_LENGTH` and start with 1024 for structured JSON extraction. You can load the model manually with `lms load <model_key> --context-length 8192`. For local smoke checks, use the local LM Studio `gemma-2b4` model. For production smoke checks, use `LM_STUDIO_BASE_URL=http://192.168.0.10:1234/v1` with `LM_STUDIO_MODEL=gemma-4-12b-qat`. If `/logs` shows `http_status=400` for `/v1/chat/completions`, first verify that `LM_STUDIO_MODEL` matches a downloaded model and that `/logs` request diagnostics show reasonable `request_body_bytes`, `message_count`, `prompt_characters`, and `response_format_name`. If the LM Studio server log still says the request exceeds the context size, unload the configured model instance, reload it with `LM_STUDIO_CONTEXT_LENGTH`, then lower `WORKER_BATCH_SIZE`, `WORKER_OPEN_ITEM_CONTEXT_LIMIT`, and `LM_STUDIO_MAX_TOKENS`.

## Bot

Use `telegram-ai-assistant run bot` for owner-only Telegram Bot API long polling. The bot accepts only updates from `TELEGRAM_ALLOWED_USER_ID`; denied users receive no command response.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run bot
```

The bot persists the latest processed Telegram `update_id` in `bot_runtime_state`, so restarts continue from the next update instead of replaying old commands. Telegram Bot API polling failures are recorded as sanitized runtime events and retried with a bounded backoff.

Implemented production commands:

- `/start` and `/help` show the command list and inline menu.
- `/cancel` clears the current active bot flow for the owner and chat.
- `/summary` shows a structured summary from stored extracted items.
- `/review` lists pending low-confidence reviews and LLM action proposals, grouped by source message where possible, and supports approve/reject callbacks.
- `/tasks` lists open task-like items and includes inline buttons to mark each item completed, partially completed, or cancelled.
- `/logs` shows sanitized warning/error runtime events.
- `/health` shows Postgres and LM Studio health.

Bot command center shell:

- The top-level inline menu exposes `Assistant`, `Ops`, `Settings`, and `Help`.
- Assistant opens summary, tasks, review, and backfill controls.
- Ops opens health, logs, backfill, and blacklist controls.
- Active text-edit flows are stored in `bot_sessions` and are scoped by Telegram user id, bot chat id, and flow id.
- Free text is ignored unless an active bot flow exists, so normal messages to the bot do not trigger commands accidentally.
- If an active bot flow is stuck or no longer needed, send `/cancel` to clear the active bot flow.

Implemented MVP operational commands:

- `/blacklist` shows listener allow/deny policy, lists known chats 6 per page, and supports allow/deny/reset buttons for bot-managed policy overrides.
- `/settings` shows non-secret runtime settings.

Bot-managed backfill:

- `/backfill creates persisted backfill jobs` for one selected chat and period.
- Period buttons cover `1, 5, 10, 15, 30, 90 days`.
- The bot shows 6 chats per page with previous/next buttons.
- Select a chat, confirm the date range, then press Start.
- app-listener executes persisted backfill jobs with the same read-only Telegram client used for live updates.
- Do not scale `app-listener` above one replica.
- Use the job status and cancel buttons from the bot to inspect or request cancellation.
- Backfill jobs do not move `last_ingested_message_id`, so live listener/ingestor cursors remain independent.
- Failed jobs show only sanitized error type/metadata through the bot and `/logs`.

## Backfill

Use `telegram-ai-assistant run backfill` for explicit shell-driven historical imports by chat and date range. It reads through the same read-only Telegram adapter, normalizes and upserts messages, and exits after one batch. For day presets and chat picking from Telegram, use the owner-only bot `/backfill` flow instead.

Do not run manual `telegram-ai-assistant run backfill` while `app-listener` is active against the same `TELEGRAM_SESSION_PATH`; both commands would try to use the same Telethon session.

Set these variables for each run:

- `TELEGRAM_BACKFILL_CHAT_ID` is the Telegram chat to import.
- `TELEGRAM_BACKFILL_START_AT` is the inclusive lower time bound and must include a timezone.
- `TELEGRAM_BACKFILL_END_AT` is the upper time bound and must be after `TELEGRAM_BACKFILL_START_AT`.
- `TELEGRAM_BACKFILL_LIMIT` caps one run, defaulting to 500.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run backfill
```

The command prints JSON with `saved_count`, `start_at`, `end_at`, optional `oldest_sent_at`/`newest_sent_at`, and `next_before_message_id`. Backfill does not update `last_ingested_message_id`, so it does not move the live ingestor cursor.

## Database

Create the Postgres database before running migrations. The migration command applies schema to an existing database and does not create the database itself.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli migrate
```

## Health

Use offline health to verify the CLI and local Python environment without touching external services:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli health --offline
```

Use online health after Postgres and LM Studio are running. It checks Postgres with `SELECT 1` and LM Studio through the `/models` endpoint:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli health
```

## Docker

Docker stores Postgres data in a host bind mount, not in a Docker-managed anonymous database location. The default path is `~/.telegram/telegram_ai_assistant/postgres`. Override it with `TELEGRAM_DATA_DIR` when needed:

```bash
export TELEGRAM_DATA_DIR="${HOME}/.telegram/telegram_ai_assistant"
mkdir -p "${TELEGRAM_DATA_DIR}/postgres"
```

Do not run `docker compose down -v` for this project. Also avoid `docker volume prune` unless you have checked what it will remove. For normal restarts and deploys, use `docker compose up -d --build ...` or `docker compose restart ...`.

Before changing storage or upgrading Postgres, create a logical backup:

```bash
docker compose exec -T postgres pg_dump -U telegram_ai_assistant -d telegram_ai_assistant > "${HOME}/.telegram/telegram_ai_assistant/backups/telegram_ai_$(date +%F_%H%M).sql"
```

Build and start the production listener, worker, and bot stack:

```bash
docker compose up -d postgres app-listener app-worker app-bot
```

For Docker, set `LOG_LEVEL` in `.env` before starting the service. Use `INFO` for normal operation and `DEBUG` only while diagnosing listener scope or message persistence issues.

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

If Telegram direct connections time out, configure an MTProxy endpoint in `.env`:

```bash
TELEGRAM_MTPROXY_HOST=proxy.example.com
TELEGRAM_MTPROXY_PORT=443
TELEGRAM_MTPROXY_SECRET=dd00000000000000000000000000000000
```

All three `TELEGRAM_MTPROXY_*` values must be set together. Restart `app-listener` after changing them:

```bash
docker compose up -d --force-recreate app-listener
```

MTProxy is only for Telethon/MTProto traffic. The Telegram Bot API uses HTTPS, so if bot commands time out, configure an HTTP(S) proxy separately:

```bash
TELEGRAM_BOT_PROXY_URL=http://proxy.example.com:8080
```

Restart `app-bot` after changing it:

```bash
docker compose up -d --force-recreate app-bot
```

## Tests

Run the Python suite:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Run the manual unread smoke test before enabling the real Telegram account broadly:

```bash
open docs/operations/manual-unread-smoke-test.md
```
