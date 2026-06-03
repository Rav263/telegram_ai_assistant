from __future__ import annotations

from typing import Any

from .domain import RuntimeEvent


SAFE_LOG_METADATA_KEYS = (
    "error_type",
    "candidate_count",
    "count",
    "failures",
)


class BotServices:
    def __init__(self, *, runtime_event_repository: Any):
        self.runtime_event_repository = runtime_event_repository

    def logs(self) -> str:
        events = self.runtime_event_repository.latest_events(limit=10)
        if not events:
            return "No warning/error runtime events."

        lines = ["Latest warning/error runtime events:"]
        for event in events:
            lines.append(_format_runtime_event(event))
        return "\n".join(lines)


def _format_runtime_event(event: RuntimeEvent) -> str:
    metadata = _format_safe_metadata(event.metadata)
    suffix = f" {metadata}" if metadata else ""
    return (
        f"{event.created_at.isoformat()} "
        f"[{event.severity.upper()}] "
        f"{event.component} {event.event_type}{suffix}"
    )


def _format_safe_metadata(metadata: dict[str, object]) -> str:
    parts = []
    for key in SAFE_LOG_METADATA_KEYS:
        if key in metadata:
            parts.append(f"{key}={metadata[key]}")
    return " ".join(parts)
