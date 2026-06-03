from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ConfigError(ValueError):
    pass


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
    backfill_days: int = 30
    telegram_ingest_limit: int = 100
    telegram_ingest_debug_messages: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
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
            backfill_days=_optional_int(env, "BACKFILL_DAYS", cls.backfill_days),
            telegram_ingest_limit=_optional_int(
                env, "TELEGRAM_INGEST_LIMIT", cls.telegram_ingest_limit
            ),
            telegram_ingest_debug_messages=_optional_bool(
                env,
                "TELEGRAM_INGEST_DEBUG_MESSAGES",
                cls.telegram_ingest_debug_messages,
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
