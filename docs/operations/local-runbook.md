# Local Runbook

## Environment

Create a project-local Python environment:

```bash
uv venv .venv --python 3.11
```

Create a `.env` file or export these variables in the service environment:

```bash
TELEGRAM_API_ID=123
TELEGRAM_API_HASH=your-api-hash
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_ALLOWED_USER_ID=123456
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

## Tests

Run the Python suite:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Run the manual unread smoke test before enabling the real Telegram account broadly:

```bash
open docs/operations/manual-unread-smoke-test.md
```
