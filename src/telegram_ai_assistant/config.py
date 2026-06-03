from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


class ConfigError(ValueError):
    pass


BOOTSTRAP_MODES = frozenset({"recent", "start_now", "cursor"})
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class Settings:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    telegram_allowed_user_id: int
    database_url: str
    telegram_session_path: str = ""
    telegram_ingest_account_id: str = ""
    telegram_ingest_chat_id: int = 0
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_model: str = "local-model"
    backfill_days: int = 30
    telegram_ingest_limit: int = 100
    telegram_ingest_debug_messages: bool = False
    telegram_ingest_bootstrap_mode: str = "recent"
    telegram_ingest_bootstrap_days: int = 30
    telegram_backfill_chat_id: int = 0
    telegram_backfill_start_at: datetime | None = None
    telegram_backfill_end_at: datetime | None = None
    telegram_backfill_limit: int = 500
    telegram_listener_allowed_channel_ids: frozenset[int] = frozenset()
    telegram_listener_denied_chat_ids: frozenset[int] = frozenset()
    log_level: str = "INFO"
    worker_batch_size: int = 25
    worker_poll_interval_seconds: int = 10
    worker_item_auto_apply_threshold: float = 0.8
    worker_status_auto_apply_threshold: float = 0.8

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        telegram_backfill_start_at = _optional_datetime(env, "TELEGRAM_BACKFILL_START_AT")
        telegram_backfill_end_at = _optional_datetime(env, "TELEGRAM_BACKFILL_END_AT")
        if (
            telegram_backfill_start_at is not None
            and telegram_backfill_end_at is not None
            and telegram_backfill_end_at <= telegram_backfill_start_at
        ):
            raise ConfigError("TELEGRAM_BACKFILL_END_AT must be after TELEGRAM_BACKFILL_START_AT")

        return cls(
            telegram_api_id=_required_int(env, "TELEGRAM_API_ID"),
            telegram_api_hash=_required(env, "TELEGRAM_API_HASH"),
            telegram_bot_token=_required(env, "TELEGRAM_BOT_TOKEN"),
            telegram_allowed_user_id=_required_int(env, "TELEGRAM_ALLOWED_USER_ID"),
            telegram_session_path=_required(env, "TELEGRAM_SESSION_PATH"),
            telegram_ingest_account_id=_required(env, "TELEGRAM_INGEST_ACCOUNT_ID"),
            telegram_ingest_chat_id=_required_int(env, "TELEGRAM_INGEST_CHAT_ID"),
            database_url=_required(env, "DATABASE_URL"),
            lm_studio_base_url=env.get("LM_STUDIO_BASE_URL", cls.lm_studio_base_url),
            lm_studio_model=_optional_str(env, "LM_STUDIO_MODEL", cls.lm_studio_model),
            backfill_days=_optional_int(env, "BACKFILL_DAYS", cls.backfill_days),
            telegram_ingest_limit=_optional_int(
                env, "TELEGRAM_INGEST_LIMIT", cls.telegram_ingest_limit
            ),
            telegram_ingest_debug_messages=_optional_bool(
                env,
                "TELEGRAM_INGEST_DEBUG_MESSAGES",
                cls.telegram_ingest_debug_messages,
            ),
            telegram_ingest_bootstrap_mode=_optional_choice(
                env,
                "TELEGRAM_INGEST_BOOTSTRAP_MODE",
                cls.telegram_ingest_bootstrap_mode,
                BOOTSTRAP_MODES,
            ),
            telegram_ingest_bootstrap_days=_optional_positive_int(
                env,
                "TELEGRAM_INGEST_BOOTSTRAP_DAYS",
                cls.telegram_ingest_bootstrap_days,
            ),
            telegram_backfill_chat_id=_optional_int(env, "TELEGRAM_BACKFILL_CHAT_ID", 0),
            telegram_backfill_start_at=telegram_backfill_start_at,
            telegram_backfill_end_at=telegram_backfill_end_at,
            telegram_backfill_limit=_optional_positive_int(
                env,
                "TELEGRAM_BACKFILL_LIMIT",
                cls.telegram_backfill_limit,
            ),
            telegram_listener_allowed_channel_ids=_optional_int_set(
                env,
                "TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS",
            ),
            telegram_listener_denied_chat_ids=_optional_int_set(
                env,
                "TELEGRAM_LISTENER_DENIED_CHAT_IDS",
            ),
            log_level=_optional_log_level(env, "LOG_LEVEL", cls.log_level),
            worker_batch_size=_optional_positive_int(
                env,
                "WORKER_BATCH_SIZE",
                cls.worker_batch_size,
            ),
            worker_poll_interval_seconds=_optional_positive_int(
                env,
                "WORKER_POLL_INTERVAL_SECONDS",
                cls.worker_poll_interval_seconds,
            ),
            worker_item_auto_apply_threshold=_optional_probability_float(
                env,
                "WORKER_ITEM_AUTO_APPLY_THRESHOLD",
                cls.worker_item_auto_apply_threshold,
            ),
            worker_status_auto_apply_threshold=_optional_probability_float(
                env,
                "WORKER_STATUS_AUTO_APPLY_THRESHOLD",
                cls.worker_status_auto_apply_threshold,
            ),
        )


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        raise ConfigError(f"missing required setting: {name}")
    return value


def _required_int(env: Mapping[str, str], name: str) -> int:
    value = _required(env, name)
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"setting must be an integer: {name}") from exc


def _optional_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"setting must be an integer: {name}") from exc


def _optional_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"setting must be a boolean: {name}")


def _optional_choice(
    env: Mapping[str, str],
    name: str,
    default: str,
    allowed_values: frozenset[str],
) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ConfigError(f"setting must be one of {allowed}: {name}")
    return normalized


def _optional_positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = _optional_int(env, name, default)
    if value <= 0:
        raise ConfigError(f"setting must be a positive integer: {name}")
    return value


def _optional_str(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _optional_datetime(env: Mapping[str, str], name: str) -> datetime | None:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"setting must be an ISO datetime: {name}") from exc
    if parsed.tzinfo is None:
        raise ConfigError(f"setting must include timezone: {name}")
    return parsed


def _optional_int_set(env: Mapping[str, str], name: str) -> frozenset[int]:
    value = env.get(name)
    if value is None or not value.strip():
        return frozenset()
    result: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError as exc:
            raise ConfigError(f"setting must be a comma-separated list of integers: {name}") from exc
    return frozenset(result)


def _optional_log_level(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().upper()
    if normalized not in LOG_LEVELS:
        allowed = ", ".join(sorted(LOG_LEVELS))
        raise ConfigError(f"setting must be one of {allowed}: {name}")
    return normalized


def _optional_probability_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"setting must be a float between 0 and 1: {name}") from exc
    if parsed < 0.0 or parsed > 1.0:
        raise ConfigError(f"setting must be a float between 0 and 1: {name}")
    return parsed
