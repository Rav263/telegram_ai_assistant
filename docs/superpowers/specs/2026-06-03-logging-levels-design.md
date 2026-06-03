# Logging Levels Design

## Goal

Add configurable logging levels for local and Docker runs without changing the existing machine-readable command output.

## Design

The application will support a `LOG_LEVEL` environment setting with a default of `INFO`. The CLI will also expose a global `--log-level` option that overrides `LOG_LEVEL` for one command. Supported values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`, parsed case-insensitively.

Logging configuration belongs in a small `logging_config.py` module. It will configure the root logger once per command, write logs to `stderr`, and keep command result payloads on `stdout`. This preserves current shell and Docker behavior where JSON output can still be piped or parsed.

Runtime functions will log process lifecycle events and sanitized failures. The live listener will log start/stop events, skipped chat ids at debug level, and saved message ids at info level. Logs must not include Telegram message text, captions, bot tokens, API hashes, or raw exception messages.

## Operational Behavior

Examples:

```bash
telegram-ai-assistant --log-level debug run listener
LOG_LEVEL=warning telegram-ai-assistant run listener
```

Docker Compose will document `LOG_LEVEL` as an environment value supplied through `.env`. The default image command remains `telegram-ai-assistant run listener`, so production users can change verbosity without rebuilding the image.

## Testing

Tests will cover:

- default and custom `LOG_LEVEL` parsing;
- invalid log level validation;
- CLI `--log-level` override precedence;
- logging configuration writes to `stderr`;
- command JSON remains on `stdout`;
- listener logs operational ids only, not message text.
