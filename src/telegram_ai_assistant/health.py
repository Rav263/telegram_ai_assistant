from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.request import urlopen


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True)
class ComponentHealth:
    name: str
    status: HealthStatus
    details: Mapping[str, str] | None = None


@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    components: tuple[ComponentHealth, ...]

    def component(self, name: str) -> ComponentHealth:
        for component in self.components:
            if component.name == name:
                return component
        raise KeyError(name)


class HealthChecker:
    def __init__(self, components: Mapping[str, Callable[[], ComponentHealth]]):
        self.components = dict(components)

    def check(self) -> HealthReport:
        component_results = tuple(self._check_component(name, check) for name, check in self.components.items())
        return HealthReport(
            status=_aggregate_status(component_results),
            components=component_results,
        )

    def _check_component(self, name: str, check: Callable[[], ComponentHealth]) -> ComponentHealth:
        try:
            result = check()
        except Exception as exc:
            return ComponentHealth(
                name=name,
                status=HealthStatus.DOWN,
                details={"error": str(exc)},
            )
        if result.name != name:
            return ComponentHealth(name=name, status=result.status, details=result.details)
        return result


def postgres_health_check(connection_factory: Any) -> ComponentHealth:
    try:
        with connection_factory.connection() as connection:
            cursor = connection.execute("SELECT 1")
            row = cursor.fetchone()
    except Exception as exc:
        return ComponentHealth("postgres", HealthStatus.DOWN, {"error": type(exc).__name__})
    if tuple(row or ()) != (1,):
        return ComponentHealth("postgres", HealthStatus.DEGRADED, {"database": "unexpected result"})
    return ComponentHealth("postgres", HealthStatus.OK, {"database": "connected"})


def default_lm_studio_transport(url: str) -> bytes:
    with urlopen(url, timeout=2) as response:
        return response.read()


def lm_studio_health_check(
    base_url: str,
    transport: Callable[[str], bytes] = default_lm_studio_transport,
) -> ComponentHealth:
    models_url = f"{base_url.rstrip('/')}/models"
    payload = json.loads(transport(models_url).decode("utf-8"))
    models = payload.get("data", [])
    model_count = len(models) if isinstance(models, list) else 0
    return ComponentHealth(
        "lm_studio",
        HealthStatus.OK,
        {"endpoint": models_url, "models": str(model_count)},
    )


def _aggregate_status(components: tuple[ComponentHealth, ...]) -> HealthStatus:
    statuses = {component.status for component in components}
    if HealthStatus.DOWN in statuses:
        return HealthStatus.DOWN
    if HealthStatus.DEGRADED in statuses:
        return HealthStatus.DEGRADED
    return HealthStatus.OK
