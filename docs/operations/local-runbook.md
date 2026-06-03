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
TELEGRAM_ALLOWED_USER_ID=123456
TELEGRAM_SESSION_PATH=.local/telegram-owner.session
TELEGRAM_INGEST_ACCOUNT_ID=owner
TELEGRAM_INGEST_CHAT_ID=123456789
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
BACKFILL_DAYS=30
TELEGRAM_DATA_DIR=${HOME}/.telegram/telegram_ai_assistant
WORKER_BATCH_SIZE=25
WORKER_POLL_INTERVAL_SECONDS=10
WORKER_ITEM_AUTO_APPLY_THRESHOLD=0.8
WORKER_STATUS_AUTO_APPLY_THRESHOLD=0.8
LOG_LEVEL=INFO
```

## Services

- Postgres stores messages, candidates, extracted items, status events, bot actions, and backfill jobs.
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

By default the listener reads private chats, basic groups, and supergroups. Broadcast channels are ignored unless their ids are listed in `TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS`. Any id in `TELEGRAM_LISTENER_DENIED_CHAT_IDS` is never read.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run listener
```

Keep `run ingestor` available as cursor catch-up after the machine sleeps or the listener is stopped.

## Worker

Use `telegram-ai-assistant run worker --once` for local debugging. It reads pending stored messages, writes `message_candidates`, processes queued candidates through LM Studio, saves high-confidence extracted items, queues low-confidence reviews, and prints JSON counts.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run worker --once
```

Use `telegram-ai-assistant run worker` as the daemon process. It repeats the same cycle and sleeps for `WORKER_POLL_INTERVAL_SECONDS` between cycles.

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run worker
```

Worker tuning variables:

- `WORKER_BATCH_SIZE` controls how many messages/candidates one cycle processes, defaulting to 25.
- `WORKER_POLL_INTERVAL_SECONDS` controls daemon sleep, defaulting to 10.
- `WORKER_ITEM_AUTO_APPLY_THRESHOLD` controls automatic item saving versus review, defaulting to 0.8.
- `WORKER_STATUS_AUTO_APPLY_THRESHOLD` controls automatic status updates versus review, defaulting to 0.8.

LLM failures and worker errors are recorded as sanitized runtime events. Ask the owner-only bot for `/logs` to see the latest warning/error runtime events without Telegram message text, raw prompts, bot tokens, API hashes, database URLs, or raw tracebacks.

## Backfill

Use `telegram-ai-assistant run backfill` for explicit historical imports by chat and date range. It reads through the same read-only Telegram adapter, normalizes and upserts messages, and exits after one batch.

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

Build and start the production listener and worker stack:

```bash
docker compose up -d postgres app-listener app-worker
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

## Tests

Run the Python suite:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Run the manual unread smoke test before enabling the real Telegram account broadly:

```bash
open docs/operations/manual-unread-smoke-test.md
```
