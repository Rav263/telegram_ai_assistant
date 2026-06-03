# Logging Levels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable logging levels for CLI, local, and Docker runs while preserving existing stdout JSON payloads.

**Architecture:** Add `Settings.log_level`, a focused `logging_config.py` module, and a global CLI `--log-level` override. Runtime and listener modules use standard-library `logging` and log only operational metadata.

**Tech Stack:** Python 3.11, `argparse`, standard `logging`, `unittest`, Docker Compose.

---

### Task 1: Config Model

**Files:**
- Modify: `src/telegram_ai_assistant/config.py`
- Test: `tests/test_config.py`

- [ ] Write tests for default `INFO`, custom lowercase values, and invalid values.
- [ ] Run config tests and verify the new tests fail because `Settings.log_level` does not exist.
- [ ] Add `LOG_LEVELS`, `Settings.log_level`, and `_optional_choice(..., LOG_LEVELS)`.
- [ ] Re-run config tests and commit.

### Task 2: Logging Configuration and CLI Override

**Files:**
- Create: `src/telegram_ai_assistant/logging_config.py`
- Modify: `src/telegram_ai_assistant/cli.py`
- Test: `tests/test_logging_config.py`, `tests/test_cli.py`

- [ ] Write tests that `configure_logging("debug")` sets the root level and writes to `stderr`.
- [ ] Write CLI tests for global `--log-level` parsing and override precedence over env.
- [ ] Run focused tests and verify they fail because the module and CLI option do not exist.
- [ ] Implement `normalize_log_level()` and `configure_logging()`.
- [ ] Wire `--log-level` before subcommands and pass the effective level into `Settings`.
- [ ] Re-run focused tests and commit.

### Task 3: Runtime and Listener Logs

**Files:**
- Modify: `src/telegram_ai_assistant/runtime.py`
- Modify: `src/telegram_ai_assistant/ingestion/listener.py`
- Test: `tests/test_runtime.py`, `tests/test_live_update_listener.py`

- [ ] Write tests that failures are logged to `stderr` without secret exception messages.
- [ ] Write listener tests for debug skipped-chat logs and info saved-message logs without text.
- [ ] Run focused tests and verify they fail because logs are missing.
- [ ] Add module loggers and sanitized operational log calls.
- [ ] Re-run focused tests and commit.

### Task 4: Documentation and Verification

**Files:**
- Modify: `docs/operations/local-runbook.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_operations_docs.py`

- [ ] Add runbook examples for `LOG_LEVEL` and `--log-level`.
- [ ] Add changelog entry.
- [ ] Run docs tests and commit.
- [ ] Run full unit tests, CLI smoke checks, `docker compose config`, and `git diff --check`.
