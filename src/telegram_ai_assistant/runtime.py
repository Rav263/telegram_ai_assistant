from __future__ import annotations

from .config import Settings


PROCESS_NAMES = ("ingestor", "worker", "bot", "scheduler", "all")


def run_process(process_name: str, settings: Settings) -> int:
    if process_name not in PROCESS_NAMES:
        raise ValueError(f"unknown process: {process_name}")
    raise NotImplementedError(f"process runner is not wired yet: {process_name}")
