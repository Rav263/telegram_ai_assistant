# Bot Command Center Design

## Goal

Turn the owner-only Telegram bot into a hybrid command center for daily assistant workflows and production operations.

The bot must help the owner review extracted tasks, reminders, waiting states, thoughts, and source messages while also exposing safe operational controls for the local production runtime.

## Product Mode

Use a hybrid command center with two primary zones:

- Assistant: summaries, tasks, reminders, waiting states, reviews, search, and item/source details.
- Ops: health, logs, queues, backfill, chat policy, backups, migrations, restarts, and deploy checks.

The current command set remains compatible. New flows must extend the bot without breaking existing commands or callback payloads.

## Navigation Shell

Every rich bot response should include persistent navigation buttons:

- Assistant
- Ops
- Settings
- Help

The shell uses stable callback namespaces:

- `menu:*`
- `task:*`
- `review:*`
- `search:*`
- `source:*`
- `bf:*`
- `policy:*`
- `ops:*`
- `settings:*`
- `alert:*`
- `digest:*`

Multi-step flows use short-lived bot session state with expiry. `/cancel` clears the active session.

## Commands

Assistant commands:

- `/summary`: current structured summary.
- `/today`: today, overdue, and upcoming tasks/reminders.
- `/tasks`: open task-like items.
- `/reminders`: time-bound commitments and reminders.
- `/waiting`: waiting-for states and stale waits.
- `/thoughts`: useful thoughts and context.
- `/review`: proposed items and proposed status changes.
- `/search <query>`: extracted items first, saved message snippets second.
- `/item <id>`: item details, source references, status actions, and edit actions.

Ops commands:

- `/health`: component health plus queue summary.
- `/logs`: sanitized recent warning/error events.
- `/queues`: message backlog, candidates, review count, backfill jobs, scheduled notifications, and ops jobs.
- `/backfill`: known-chat backfill UI.
- `/blacklist`: known-chat listener policy UI.
- `/backup`: create a database backup.
- `/migrate`: run migrations.
- `/restart`: restart allowlisted app services.
- `/deploy`: guided backup, migrate, restart, and health verification.

Settings commands:

- `/settings`: settings dashboard.
- `/quiet`: quiet hours.
- `/digest`: digest schedule.
- `/alerts`: alert categories and delivery rules.
- `/thresholds`: review and auto-apply thresholds.
- `/model`: LLM model and non-secret endpoint settings.
- `/limits`: batch sizes, page sizes, catch-up limits.

Help commands:

- `/start`
- `/help`

## Review And Editing

Use a controlled edit flow, not a free-form conversational editor.

Supported review actions:

- approve extracted item;
- reject extracted item;
- apply suggested status change;
- ignore suggested status change;
- edit item title;
- edit due date;
- edit item type;
- edit item status.

Short text input is allowed only inside an active session. The session records the flow, target item, field, and expiry. After a value is applied or `/cancel` is received, the session is deleted.

## Search And Sources

`/search <query>` searches both extracted items and saved messages.

Result order:

1. matching extracted items;
2. saved message snippets.

Results are paged. Message snippets must be bounded and safe for Telegram display. The bot must not dump full chat history.

Item results support:

- open item details;
- mark status;
- open source message;
- edit item.

Message results support:

- create task from message;
- create thought/context from message;
- open neighboring source context only in bounded form.

## Settings Model

Bot-managed settings are non-secret runtime settings.

Mutable from the bot:

- LLM model id;
- non-secret LLM base URL;
- thresholds;
- quiet hours;
- digest schedule;
- alert toggles;
- batch sizes;
- page sizes;
- catch-up limits;
- listener policy overrides.

Not mutable from the bot:

- Telegram API hash;
- Telegram bot token;
- database password;
- raw database URL when it contains credentials;
- Telegram session file path contents.

Secret settings are shown only as `configured` or `not configured`.

## Data Model

Add `bot_sessions`.

Purpose:

- short-lived multi-step flows;
- keyed by owner user id, bot chat id, and flow id;
- JSON payload;
- expiry timestamp;
- cleanup by repository/runtime.

Add `bot_settings`.

Purpose:

- non-secret runtime settings;
- typed values: bool, int, float, string, JSON;
- DB values override environment defaults where the runtime supports hot reload.

Add `scheduled_notifications`.

Purpose:

- proactive digest and alert delivery;
- notification type: digest, reminder, overdue, waiting_nudge;
- status: pending, sent, cancelled, failed;
- due time;
- quiet-window behavior;
- stable dedupe key;
- source refs where applicable.

Add `ops_jobs`.

Purpose:

- long-running safe operational actions;
- action type: backup, migrate, restart, deploy step;
- status: pending, running, completed, failed, cancelled;
- sanitized log lines and metadata;
- audit trail.

Reuse existing tables:

- `extracted_items`
- `review_queue`
- `messages`
- `backfill_jobs`
- `chat_policy_overrides`
- `runtime_events`
- `bot_runtime_state`

## Proactive Runtime

Add a notification planner and dispatcher.

`NotificationPlanner` scans extracted items, reminders, and waiting states and creates `scheduled_notifications`.

`NotificationDispatcher` sends due notifications through the Bot API, respects quiet hours, batches low-priority items, and records sent or failed status.

The runtime may initially run inside `app-bot`, but the design must allow moving it to a separate `app-scheduler` service later.

Delivery rules:

- exact reminders are scheduled near due time;
- overdue tasks are batched unless urgent;
- waiting-for nudges are created after a configurable age;
- morning/evening digests are scheduled by `/digest`;
- quiet hours delay delivery unless a future explicit bypass setting allows otherwise;
- stable dedupe keys prevent duplicate notifications after restart.

Alert callbacks:

- snooze;
- mark done;
- open item;
- mute rule.

## Ops Actions

Safe ops actions are allowlisted enum actions, not arbitrary shell commands.

Allowed actions:

- create a Postgres backup under `~/.telegram/telegram_ai_assistant/backups`;
- run migrations;
- restart allowlisted services: `app-listener`, `app-worker`, `app-bot`;
- run a guided deploy sequence: backup, migrate, rebuild/restart, health check.

Forbidden actions:

- arbitrary shell commands;
- `docker compose down -v`;
- `docker volume prune`;
- database restore/drop from the bot;
- displaying raw env values, secrets, raw tracebacks, or raw command output.

All ops actions create `ops_jobs` rows and sanitized `runtime_events`.

## Error Handling And Safety

The bot is owner-only.

Every output must pass through safe rendering:

- no bot token;
- no API hash;
- no DB password;
- no raw credential-bearing URL;
- no raw traceback;
- no unbounded message dumps;
- no raw LLM prompt dumps.

Failed flows should provide:

- a short user-facing error;
- a safe error type;
- a job id or event id when applicable;
- a button to open `/logs` or refresh the job.

Sessions expire to avoid accidental edits from later free text.

## Implementation Slices

1. Bot shell contract
   - stable callback namespaces;
   - persistent nav;
   - bot sessions;
   - `/cancel`;
   - command catalog tests.

2. Assistant views
   - `/today`;
   - `/reminders`;
   - `/waiting`;
   - `/thoughts`;
   - `/item`;
   - review/edit field flow;
   - source detail pages.

3. Search
   - `/search <query>`;
   - item results;
   - message snippets;
   - paging;
   - create item from message.

4. Settings
   - `bot_settings`;
   - `/quiet`;
   - `/digest`;
   - `/alerts`;
   - `/thresholds`;
   - `/model`;
   - `/limits`;
   - no secret mutation.

5. Proactive runtime
   - `scheduled_notifications`;
   - planner;
   - dispatcher;
   - digest;
   - reminders;
   - snooze and mute.

6. Ops safe actions
   - `/queues`;
   - `/backup`;
   - `/migrate`;
   - `/restart`;
   - `/deploy`;
   - `ops_jobs`.

Each slice uses TDD, updates docs and changelog, and requires the full test suite before merge.

## Acceptance Criteria

- Existing bot commands continue to work.
- The main menu separates Assistant and Ops concerns.
- Multi-step text input only applies inside an active bot session.
- Search returns bounded item and message results.
- Proactive notifications survive restarts and avoid duplicate sends.
- Quiet hours delay alerts and batch low-priority notifications.
- Ops actions are allowlisted and audited.
- Secrets are never mutable through the bot and never printed.
- Full unit suite and `git diff --check` pass for each implementation slice.
