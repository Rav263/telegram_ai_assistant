from __future__ import annotations

from typing import Any

from .domain import RuntimeEvent
from .health import HealthReport


SAFE_LOG_METADATA_KEYS = (
    "error_type",
    "candidate_count",
    "endpoint_scheme",
    "endpoint_host",
    "endpoint_path",
    "http_status",
    "transport_error_type",
    "count",
    "failures",
)
SAFE_HEALTH_DETAIL_KEYS = ("database", "endpoint", "models", "error", "mode")


class BotServices:
    def __init__(self, *, runtime_event_repository: Any, health_report_provider: Any | None = None):
        self.runtime_event_repository = runtime_event_repository
        self.health_report_provider = health_report_provider

    def logs(self) -> str:
        events = self.runtime_event_repository.latest_events(limit=10)
        if not events:
            return "No warning/error runtime events."

        lines = ["Latest warning/error runtime events:"]
        for event in events:
            lines.append(_format_runtime_event(event))
        return "\n".join(lines)

    def health(self) -> str:
        if self.health_report_provider is None:
            return "Health service is not configured."
        report = self.health_report_provider()
        return _format_health_report(report)

    def summary(self) -> str:
        return "Command /summary is not implemented yet."

    def tasks(self) -> str:
        return "Command /tasks is not implemented yet."

    def review(self) -> str:
        return "Command /review is not implemented yet."

    def backfill(self) -> str:
        return "Command /backfill is not implemented yet."

    def blacklist(self) -> str:
        return "Command /blacklist is not implemented yet."

    def settings(self) -> str:
        return "Command /settings is not implemented yet."

    def handle_review_callback(self, action: str, target_id: str) -> None:
        return None

    def handle_status_callback(self, action: str, target_id: str) -> None:
        return None

    def handle_backfill_callback(self, action: str, target_id: str) -> None:
        return None


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


def _format_health_report(report: HealthReport) -> str:
    lines = [f"Health: {report.status.value}"]
    for component in report.components:
        details = _format_safe_health_details(component.details or {})
        suffix = f" {details}" if details else ""
        lines.append(f"{component.name}: {component.status.value}{suffix}")
    return "\n".join(lines)


def _format_safe_health_details(details: Any) -> str:
    parts = []
    for key in SAFE_HEALTH_DETAIL_KEYS:
        if key in details:
            parts.append(f"{key}={details[key]}")
    return " ".join(parts)
