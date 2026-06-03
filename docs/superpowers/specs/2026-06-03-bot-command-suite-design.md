# Bot Command Suite Design

## Goal

Make the owner-only Telegram bot useful as the main operating interface for the assistant. The slice adds a complete command surface with inline buttons while keeping implementation risk bounded:

- production-grade `/summary` and `/review`;
- MVP-grade `/backfill`, `/blacklist`, and `/settings`;
- `/start` and `/help` as the discoverable menu entry points;
- callback buttons for navigation and common actions.

The existing listener, worker, extraction, task listing, health, logs, and Docker runtime remain the foundation. This design extends the bot service layer and database query/action repositories without rewriting the runtime.

## Current State

Already implemented:

- Telegram live update listener saves accepted messages without intentionally marking them read.
- Worker filters messages, calls LM Studio, saves high-confidence extracted items, and queues low-confidence items/status changes.
- Bot runtime is owner-only, long-polls through Telegram Bot API, persists update offsets, and retries safely.
- Bot commands `/health`, `/logs`, and `/tasks` work in production.
- `/tasks` includes inline buttons for completed, partially completed, and cancelled status actions.

Still missing:

- `/summary`, `/review`, `/backfill`, `/blacklist`, `/settings`, `/help`, and `/start` product behavior.
- Review queue browsing and review action persistence.
- A clear button-based menu so commands are discoverable from Telegram.

## Scope

Production scope:

- `/summary` builds a concise structured summary from stored `extracted_items`.
- `/review` lists pending review entries and supports approve/reject actions that update the database.
- Review actions must be idempotent enough for repeated Telegram callbacks and must not expose raw private text beyond the reviewed item data already stored for the owner.

MVP scope:

- `/backfill` shows safe preset actions: last 30 days, last 90 days, status/help.
- `/blacklist` shows current listener allow/deny policy and explains that updates are configured through environment variables and restart for this slice.
- `/settings` shows only non-secret runtime settings.
- `/help` and `/start` show the command list and main menu buttons.

Out of scope for this slice:

- Arbitrary date input for backfill through chat text.
- Persistent settings mutation from the bot.
- In-bot editing of extracted item text.
- LLM-generated natural-language summary polish. The first version summarizes existing structured data without a new LLM call.
- Multi-user access.

## Command UX

### Main Menu

`/start` and `/help` both return a short command list with inline buttons:

```text
Summary | Tasks
Review  | Backfill
Health  | Logs
Settings | Help
```

The menu is safe to send repeatedly and should not depend on any database query.

### `/summary`

Returns a compact summary for the default recent period, initially today or the last 24 hours depending on the available timestamps. The summary groups items by:

- active tasks and commitments;
- reminders and due items;
- waiting items;
- notable thoughts.

The response includes buttons:

- `Tasks`;
- `Review`;
- `Refresh`;
- `Help`.

The first implementation reads from `extracted_items` only. It does not call LM Studio, so the command remains available when LM Studio is down.

### `/review`

Returns up to five pending review entries. Each entry includes:

- review id;
- review type;
- candidate title or status-change summary;
- confidence if available;
- short rationale if available.

Each entry has action buttons:

- approve;
- reject or ignore.

For item review, approve saves or promotes the candidate item to an active state and marks the review processed. Reject marks the review rejected and leaves the item in a non-active candidate/rejected state where supported by the existing model.

For status-change review, approve applies the proposed status change and marks the review processed. Reject marks the review rejected without changing the item.

If no pending entries exist, `/review` returns `No pending reviews.` with a menu button.

### `/backfill`

Returns current backfill settings and safe action buttons:

- `Last 30 days`;
- `Last 90 days`;
- `Status`;
- `Help`.

For MVP, the command must not launch an unbounded import. It can either run the existing bounded one-shot backfill service synchronously with configured limits or return a clear "not configured" response if the runtime dependencies are absent.

### `/blacklist`

Shows the current listener policy:

- allowed broadcast channel ids;
- denied chat ids;
- default policy for private chats, basic groups, supergroups, and channels.

It does not write settings in this slice. The response explains that the lists are changed through environment variables followed by service restart.

### `/settings`

Shows only allowlisted non-secret fields:

- ingest account id;
- ingest chat id if configured;
- listener allowed channel ids;
- listener denied chat ids;
- LM Studio base URL host/path and configured model;
- worker batch size;
- worker poll interval;
- item/status auto-apply thresholds;
- log level;
- Telegram data directory path if safe to show.

It must not show bot token, API hash, database URL, Telegram session file contents, raw prompts, or message text.

## Callback Design

Keep callback payloads short and compatible with the existing `kind:action:target_id` parser.

Initial callback forms:

```text
menu:summary:0
menu:tasks:0
menu:review:0
menu:backfill:0
menu:health:0
menu:logs:0
menu:settings:0
menu:help:0
review:approve:<review_id>
review:reject:<review_id>
backfill:30d:0
backfill:90d:0
backfill:status:0
status:completed:<item_id>
status:partially_completed:<item_id>
status:cancelled:<item_id>
```

`status:*` remains compatible with the existing `/tasks` buttons.

After a callback:

- the bot always answers `answerCallbackQuery` when a callback id is present;
- successful review/status actions return a concise result;
- failures return a safe concise result and record a sanitized runtime event;
- the bot can send a fresh message or rely on the next `Refresh` button rather than editing old messages in the first release.

The router should dispatch menu callbacks to the same service methods used by slash commands, avoiding separate behavior.

## Data Access

Add focused query/action methods rather than putting SQL in `BotServices`.

Proposed repository capabilities:

- `ItemQueryRepository.list_summary_items(limit, since)` reads active and notable items for `/summary`.
- `ReviewQueryRepository.list_pending_reviews(limit)` reads pending review entries and joins item data where safe and useful.
- `ReviewActionRepository.approve_review(review_id)` applies item review or status-change review and marks the review processed.
- `ReviewActionRepository.reject_review(review_id)` marks the review rejected or ignored.
- `BackfillStatusRepository.latest_jobs(limit)` optionally reads recent `backfill_jobs` for `/backfill status`.

If the existing `review_queue` schema does not have enough state vocabulary, extend it with compatible `ALTER TABLE` statements rather than replacing the table.

## Services

`BotServices` remains the product orchestration boundary. It should accept optional dependencies so tests and partial runtime wiring stay simple:

- runtime event repository;
- health report provider;
- item query repository;
- item repository;
- summary query repository;
- review query/action repository;
- backfill runner or backfill status provider;
- settings snapshot provider.

Each command method returns `BotResponse` when buttons are needed, or a plain string when not needed.

Formatting helpers should stay small and deterministic:

- `format_help`;
- `format_summary`;
- `format_review_entries`;
- `format_backfill`;
- `format_blacklist`;
- `format_settings`.

## Safety And Privacy

The bot is owner-only. Existing denied-user behavior remains unchanged.

All operational output uses allowlists:

- `/settings` uses explicit safe setting keys;
- `/logs` keeps existing safe metadata keys;
- `/health` keeps existing safe health detail keys;
- runtime errors record exception type and safe metadata, not raw error text or tracebacks.

Review and summary responses may include extracted item titles/descriptions because the owner requested a bot interface for their personal data. They must not include bot token, API hash, database URL, Telegram session file contents, raw prompts, or full raw Telegram update payloads.

Backfill callbacks must remain bounded by preset windows and configured limits.

## Error Handling

Every command should return a useful owner-facing message if a dependency is not configured.

Examples:

- `Summary service is not configured.`
- `Review service is not configured.`
- `Backfill service is not configured.`
- `Settings service is not configured.`

Callback action failures should:

- answer the callback with a short failure text;
- record a sanitized runtime event with component `bot`;
- avoid advancing Telegram bot offset only when the router/runtime already considers the update failed.

Repository action methods should be transaction-friendly and rely on the app context connection boundary.

## Testing Strategy

TDD is required for the entire slice.

Router tests:

- `/start` and `/help` dispatch to help/menu service.
- Menu callbacks dispatch to the same service methods as slash commands.
- Unknown callback kinds/actions are ignored safely.
- Callback responses use `answer_callback_query`.

Service tests:

- `/summary` formats grouped items and menu buttons.
- `/summary` returns a configured fallback when no items exist.
- `/review` formats pending item and status-change reviews with action buttons.
- Review approve/reject callbacks call the action repository.
- `/backfill` shows preset buttons and safe configured state.
- `/blacklist` shows listener policy without secrets.
- `/settings` shows only allowlisted values.
- `/help` lists all implemented commands and main menu buttons.

Repository tests:

- summary query filters by account, status/type, and time window;
- pending review query reads item and payload data;
- approve item review marks review processed and activates or preserves the item according to the existing item model;
- approve status-change review applies the status change and records an item status event;
- reject review marks review rejected without applying changes.

Runtime/app context tests:

- production bot context wires new repositories/services;
- no construction-time database connection is opened;
- missing optional dependencies produce safe responses.

Docs and packaging tests:

- runbook lists all bot commands;
- changelog records the command suite;
- Docker compose remains valid.

Final verification:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
docker compose config --quiet
```

## Definition Of Done

- `/start` and `/help` show a menu and command list.
- `/summary` returns a useful summary from stored extracted items.
- `/review` lists pending reviews and includes approve/reject buttons.
- Review approve/reject actions update the database.
- `/backfill`, `/blacklist`, and `/settings` no longer return generic not-implemented text.
- `/tasks`, `/health`, and `/logs` still work.
- All responses remain owner-only.
- Secret values are not displayed.
- Tests cover router, services, repositories, runtime wiring, docs, and Docker compose.
- Docker runtime can be rebuilt and restarted without losing Postgres data.
