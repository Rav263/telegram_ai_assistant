from __future__ import annotations

import logging
import sys

from .config import ConfigError, LOG_LEVELS


def normalize_log_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in LOG_LEVELS:
        allowed = ", ".join(sorted(LOG_LEVELS))
        raise ConfigError(f"log level must be one of {allowed}")
    return normalized


def configure_logging(level: str) -> None:
    normalized = normalize_log_level(level)
    logging.basicConfig(
        level=getattr(logging, normalized),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
        force=True,
    )
