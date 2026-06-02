from __future__ import annotations

from collections.abc import Callable, Mapping

from .config import Settings
from .health import ComponentHealth, HealthChecker, HealthReport, HealthStatus


PROCESS_NAMES = ("ingestor", "worker", "bot", "scheduler", "all")
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


def run_ingestor(settings: Settings) -> int:
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
