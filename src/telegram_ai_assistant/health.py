from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum


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


def _aggregate_status(components: tuple[ComponentHealth, ...]) -> HealthStatus:
    statuses = {component.status for component in components}
    if HealthStatus.DOWN in statuses:
        return HealthStatus.DOWN
    if HealthStatus.DEGRADED in statuses:
        return HealthStatus.DEGRADED
    return HealthStatus.OK
