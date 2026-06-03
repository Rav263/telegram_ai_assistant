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
DATABASE_URL=postgresql://localhost/telegram_ai_assistant
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
BACKFILL_DAYS=30
```

## Services

- Postgres stores messages, candidates, extracted items, status events, bot actions, and backfill jobs.
- LM Studio serves the local OpenAI-compatible LLM endpoint.
- `telegram-ai-assistant run ingestor` reads Telegram updates through the read-only ingestion adapter.
- `telegram-ai-assistant run worker` processes candidates and extraction batches.
- `telegram-ai-assistant run bot` serves owner-only Telegram Bot API commands.
- `telegram-ai-assistant run scheduler` drives retries, backfill, and periodic processing.

## Ingestor

For this release, `telegram-ai-assistant run ingestor` is a one-shot single-chat command for controlled unread smoke testing. It reads only `TELEGRAM_INGEST_CHAT_ID`, uses `last_ingested_message_id` from the `chats` table as the cursor, saves new messages, advances the cursor, and exits.

Run it only against a controlled non-secret chat until the manual unread smoke test passes:

```bash
PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run ingestor
```

The command prints JSON with `saved_count`, `requested_min_id`, and `latest_message_id`. It must not print message text, bot tokens, API hashes, database passwords, or Telegram session contents.

Set `TELEGRAM_INGEST_DEBUG_MESSAGES=true` only for local troubleshooting when you need the command output to include `debug_messages` with saved message IDs, sender IDs, direction, timestamp, text, and caption. Turn it back off after debugging so routine logs do not contain private message text.

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

## Tests

Run the Python suite:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Run the manual unread smoke test before enabling the real Telegram account broadly:

```bash
open docs/operations/manual-unread-smoke-test.md
```
