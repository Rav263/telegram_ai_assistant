# Changelog

## Unreleased

- Added project setup requirements for the MVP foundation.
- Added core domain types for messages, extracted items, statuses, and source references.
- Added a broad semantic candidate filter for implicit tasks, commitments, and waiting states.
- Added status review policy for high-confidence automatic updates and low-confidence review routing.
- Added strict validation for LM Studio extraction JSON responses.
- Added owner-only access control for the summary bot.
- Added read-only guard for Telegram methods that could mutate account state.
- Added environment config loading and CLI skeleton.
- Added Postgres schema and repository ports.
- Added Telegram ingestion normalization and content extractor ports.
- Added LM Studio client and extraction service.
- Added worker pipeline for candidates, extraction, and review routing.
- Added configurable Telegram history backfill jobs.
- Added owner-only summary bot routing and Bot API client.
- Added health checks for runtime components.
- Added CLI runtime dispatch and offline health command.
- Added local operations runbooks and manual unread smoke test checklist.
- Added production wiring base for `.env` loading, Postgres migrations, and online health checks.
- Added one-shot live Telegram ingestor with chat cursor persistence.
- Added opt-in ingestor debug output for saved message text and captions.
