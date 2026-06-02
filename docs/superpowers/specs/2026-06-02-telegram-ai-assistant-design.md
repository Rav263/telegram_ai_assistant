# Telegram AI Assistant Design

Date: 2026-06-02

## Goal

Build a local-first Telegram assistant that reads new messages from the owner's personal Telegram account without marking them as read, extracts tasks, commitments, thoughts, reminders, waiting states, and useful context, and exposes concise summaries through a separate Telegram Bot API bot.

The personal Telegram account is read-only. The summary bot is the only interface that sends messages.

## Core Decisions

- Scope is all cloud Telegram dialogs except chats excluded by blacklist.
- The Telegram user account is strictly read-only.
- Secret chats are out of scope for the MVP.
- Processing is local-first. Message content is stored locally and sent only to a local-network LM Studio endpoint.
- The app runs Mac-first and remains portable to Linux.
- Postgres is the primary database from the start.
- The summary interface is a separate Telegram Bot API bot with commands and inline buttons.
- The bot responds only to the configured owner Telegram user id.
- History import is configurable. The default initial backfill is the last 30 days, and older imports can be requested through the bot.
- MVP processes text messages and existing text captions. Media bytes are not downloaded, transcribed, OCRed, or parsed; non-text media is stored as metadata only.
- A `ContentExtractor` interface is included so voice transcription, OCR, and document parsing can be added later.
- Development follows TDD for all behavior: write a failing test first, implement the smallest passing change, then refactor.

## Architecture

Use a modular Python backend in one repository with separate runnable processes and a shared Postgres database.

### Processes

- `ingestor`: logs in to Telegram as the owner account through MTProto, listens for new updates, imports history, normalizes messages, and persists them. This process must not send, edit, delete, react to, or mark messages as read.
- `worker`: processes saved messages, applies a broad candidate filter, calls LM Studio in batches, extracts items, and proposes or applies status changes.
- `bot`: uses a separate Telegram Bot API token to serve summaries, reviews, settings, backfill controls, and status actions. It only responds to the owner user id.
- `scheduler`: runs periodic extraction, retries, backfill jobs, health checks, and summary snapshots. This can be a separate process or part of the worker for the MVP.

### Runtime

Expose one CLI with modes:

- `run ingestor`
- `run worker`
- `run bot`
- `run scheduler`
- `run all`

The CLI stays OS-neutral. Mac `launchd` and Linux `systemd` wrappers are deployment details, not application dependencies.

## Data Flow

1. `ingestor` receives a new Telegram update or imports historical messages.
2. The message is normalized into account, chat, sender, direction, timestamp, text, caption, reply reference, forward metadata, Telegram entities, and Telegram ids.
3. Raw update metadata and the normalized message are saved to Postgres.
4. Messages are deduplicated by `(account_id, chat_id, telegram_message_id)`.
5. A broad candidate filter assigns a candidate score and reason labels.
6. `worker` builds batches from candidates with a small context window around each source message.
7. LM Studio returns structured JSON with extracted items, confidence, due dates, source references, rationale, and proposed status changes.
8. High-confidence items and status changes are applied automatically.
9. Low-confidence items and disputed status changes are placed in `review_queue`.
10. The bot reads aggregated state and presents summaries, tasks, reviews, backfill controls, and health.
11. Inline button actions write human feedback and status events back to Postgres.

Unread behavior is a product requirement. The Telegram adapter must avoid read or ack methods. Before using the real account broadly, run a manual smoke test in a controlled chat to confirm the main Telegram UI still shows the message as unread after ingestion.

## Data Model

Minimum tables:

- `accounts`: Telegram user account metadata, import defaults, read-only guard settings.
- `chats`: dialog metadata, chat type, title, username, blacklist flag, import state.
- `messages`: normalized messages, text, caption, direction, sender, timestamps, reply and forward refs.
- `raw_updates`: raw Telegram update metadata for audit and recovery.
- `message_candidates`: candidate score, reason labels, and processing state.
- `extracted_items`: tasks, thoughts, commitments, reminders, waiting-for items, and useful context.
- `item_status_events`: status history for each extracted item.
- `review_queue`: low-confidence items and disputed status changes needing owner action.
- `llm_runs`: LM Studio requests, model, prompt version, latency, result hash, and error state.
- `backfill_jobs`: import scope, period, chat filter, cursor, progress, and status.
- `bot_actions`: commands, callbacks, denied access, and audit trail.
- `settings`: thresholds, prompt versions, blacklist overrides, and runtime options.

Item statuses:

- `candidate`
- `open`
- `in_progress`
- `partially_completed`
- `completed`
- `cancelled`
- `obsolete`
- `waiting_for`

Every extracted item and status event stores source message references and a short rationale. This is required for review, rollback, and debugging.

## Extraction Logic

Extraction has two stages.

### Candidate Filter

The fast filter is intentionally broad. It should not rely only on direct task words. It flags possible importance from signals such as:

- time expressions: "через 30 минут", "завтра", "потом", "на неделе";
- commitments from the owner: "перезвоню", "посмотрю", "отправлю";
- direct or implied requests;
- decisions;
- waiting states: "жду", "ожидаю", "пока от них";
- references to documents, places, links, payments, meetings, or handoffs;
- self-notes and ideas;
- replies where context changes the meaning.

The examples below must be treated as task-like candidates:

- "Если там сейчас есть что-то важное, то скопируйте это оттуда."
- "Через минут 30-40 перезвоню."

### LLM Extraction

LM Studio receives batches of candidate messages plus context windows and returns strict JSON.

Extracted item types:

- `task`
- `thought`
- `commitment`
- `reminder`
- `waiting_for`
- `useful_context`

Each item includes:

- title;
- short description;
- type;
- due time or estimated time if present;
- assignee or source;
- confidence;
- source message ids;
- rationale;
- optional priority;
- optional related chat ids.

### Status Detection

Outgoing owner messages also update existing items. The worker passes relevant open items to the LLM and asks for proposed status changes.

Examples:

- "Я перезвонил Ивану, но по оплате еще не договорились" can partially complete a call-related item while keeping payment unresolved.
- "Скопировал важное из папки, завтра разберу остальное" can mark one part completed and another still open.
- "Все, оплату отправил" can complete an open payment task.
- "Это уже не актуально" can cancel or obsolete a task.

High-confidence status changes are applied automatically. Low-confidence changes go to the review queue with buttons to confirm, rollback, or ignore.

## Bot UX

The summary bot uses the Telegram Bot API and only serves the configured owner user id. Other users are ignored or receive a neutral denial, and the access attempt is logged.

Commands:

- `/summary`: concise summary for today by default, including active tasks, important thoughts, waiting items, and notable changes.
- `/tasks`: active tasks grouped by due date, priority, and source.
- `/review`: low-confidence candidates and disputed status changes.
- `/backfill`: start or inspect history import. Default is the last 30 days; older periods can be requested.
- `/blacklist`: view and edit excluded chats.
- `/settings`: thresholds, LM Studio health, import settings, and prompt versions.
- `/health`: ingestor, worker, bot, Postgres, and LM Studio status.

Inline actions:

- candidate actions: add, ignore, snooze, edit type;
- status actions: confirm, rollback, ignore;
- task actions: complete, partially done, not relevant, show source;
- backfill actions: import last 30 days, import older period, pause, resume, cancel.

Summaries should be short by default with an option to expand details. Source references should include chat and timestamp information when available, without marking Telegram messages as read.

## Reliability

- Use idempotent writes and unique Telegram ids to avoid duplicates.
- Workers must be retry-safe.
- LM Studio failures must not block ingestion.
- `llm_runs` stores enough metadata to audit model behavior without logging full message text by default.
- Backfill jobs store cursors and progress so they can resume after restart.
- Bot actions are audited.
- Read-only protection is enforced through the Telegram adapter interface.

## Privacy And Security

- No cloud LLM provider is used for MVP.
- Message content stays in Postgres and the local-network LM Studio request path.
- Logs must not include full message text by default.
- Secrets are supplied through environment variables or local secret storage.
- Telegram session files, `.env`, bot tokens, and database credentials are ignored by git.
- The bot enforces `allowed_user_id`.

## Testing Strategy

All implementation follows TDD:

1. Write a failing test for the intended behavior.
2. Implement the smallest change that makes the test pass.
3. Refactor while keeping tests green.

Required test areas:

- candidate filtering for implicit tasks, time commitments, waiting states, and self-notes;
- LLM JSON parsing and validation;
- item creation and source references;
- status transitions, including partial completion and rollback;
- bot access control for allowed and denied users;
- bot callback handling;
- Postgres deduplication and idempotent worker behavior;
- backfill job cursor and resume logic;
- read-only Telegram adapter guard;
- LM Studio failure and retry behavior.

Integration tests should use Postgres and mocked Telegram and Bot API clients. The unread guarantee requires a manual smoke test against Telegram because it depends on external client behavior.

## Non-Goals For MVP

- Sending messages from the personal Telegram account.
- Auto-replying as the personal Telegram account.
- Secret chat support.
- Voice transcription.
- OCR for images.
- Document parsing.
- Web dashboard.
- Multi-user summary bot access.
- External cloud LLM providers.

## Open Implementation Notes

- Prefer Telethon for the initial MTProto implementation unless verification shows it marks messages read in the target flow.
- Keep the Telegram integration behind an adapter so TDLib can replace it if read-only behavior requires a different client.
- Keep the LLM client OpenAI-compatible so LM Studio model changes do not affect worker internals.
- Store prompt versions and result hashes to make extraction behavior auditable.
- Use repository or DAO boundaries around database access so Postgres SQL is not scattered across business logic.
