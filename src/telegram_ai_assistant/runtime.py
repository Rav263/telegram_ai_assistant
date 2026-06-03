from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any

from .app_context import AppContext
from .config import Settings
from .health import ComponentHealth, HealthChecker, HealthReport, HealthStatus
from .ingestion.backfill import BackfillRunResult
from .ingestion.live import IngestionRunResult


PROCESS_NAMES = ("ingestor", "backfill", "worker", "bot", "scheduler", "all")
Runner = Callable[[Settings], int]


def run_process(
    process_name: str,
    settings: Settings,
    *,
    runners: Mapping[str, Runner] | None = None,
) -> int:
    if process_name not in PROCESS_NAMES:
        raise ValueError(f"unknown process: {process_name}")
    process_runners = dict(DEFAULT_RUNNERS if runners is None else runners)
    return process_runners[process_name](settings)


def run_ingestor(settings: Settings, *, context_factory=AppContext.from_settings) -> int:
    try:
        result = asyncio.run(context_factory(settings).run_ingestor_once())
    except Exception as exc:
        print(f"ingestor failed: {type(exc).__name__}")
        return 1
    print(json.dumps(_ingestion_result_payload(result), ensure_ascii=False, sort_keys=True))
    return 0


def run_backfill(settings: Settings, *, context_factory=AppContext.from_settings) -> int:
    try:
        result = asyncio.run(context_factory(settings).run_backfill_once())
    except Exception as exc:
        print(f"backfill failed: {type(exc).__name__}")
        return 1
    print(json.dumps(_backfill_result_payload(result), ensure_ascii=False, sort_keys=True))
    return 0


def run_worker(settings: Settings) -> int:
    return 0


def run_bot(settings: Settings) -> int:
    return 0


def run_scheduler(settings: Settings) -> int:
    return 0


def run_all(settings: Settings) -> int:
    for process_name in ("ingestor", "worker", "bot", "scheduler"):
        run_process(process_name, settings)
    return 0


DEFAULT_RUNNERS: Mapping[str, Runner] = {
    "ingestor": run_ingestor,
    "backfill": run_backfill,
    "worker": run_worker,
    "bot": run_bot,
    "scheduler": run_scheduler,
    "all": run_all,
}


def offline_health_report() -> HealthReport:
    checker = HealthChecker(
        {
            "postgres": lambda: ComponentHealth("postgres", HealthStatus.OK, {"mode": "offline"}),
            "lm_studio": lambda: ComponentHealth("lm_studio", HealthStatus.OK, {"mode": "offline"}),
            "ingestor": lambda: ComponentHealth("ingestor", HealthStatus.OK, {"mode": "offline"}),
            "worker": lambda: ComponentHealth("worker", HealthStatus.OK, {"mode": "offline"}),
            "bot": lambda: ComponentHealth("bot", HealthStatus.OK, {"mode": "offline"}),
        }
    )
    return checker.check()


def _backfill_result_payload(result: BackfillRunResult) -> dict[str, Any]:
    payload = {
        "account_id": result.account_id,
        "chat_id": result.chat_id,
        "start_at": result.start_at.isoformat(),
        "end_at": result.end_at.isoformat(),
        "requested_before_message_id": result.requested_before_message_id,
        "next_before_message_id": result.next_before_message_id,
        "saved_count": result.saved_count,
    }
    if result.oldest_sent_at is not None:
        payload["oldest_sent_at"] = result.oldest_sent_at.isoformat()
    if result.newest_sent_at is not None:
        payload["newest_sent_at"] = result.newest_sent_at.isoformat()
    return payload


def _ingestion_result_payload(result: IngestionRunResult) -> dict[str, Any]:
    payload = {
        "account_id": result.account_id,
        "chat_id": result.chat_id,
        "requested_min_id": result.requested_min_id,
        "saved_count": result.saved_count,
        "latest_message_id": result.latest_message_id,
        "bootstrap_mode": result.bootstrap_mode,
    }
    if result.oldest_sent_at is not None:
        payload["oldest_sent_at"] = result.oldest_sent_at.isoformat()
    if result.newest_sent_at is not None:
        payload["newest_sent_at"] = result.newest_sent_at.isoformat()
    if result.debug_messages:
        payload["debug_messages"] = [
            {
                "telegram_message_id": message.telegram_message_id,
                "sender_id": message.sender_id,
                "direction": message.direction.value,
                "sent_at": message.sent_at.isoformat(),
                "text": message.text,
                "caption": message.caption,
            }
            for message in result.debug_messages
        ]
    return payload
