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
- Added local operations runbooks and manual unread smoke test checklist.
