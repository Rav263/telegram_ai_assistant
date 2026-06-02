from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import Settings
from .db.connection import PostgresConnectionFactory
from .db.migrations import apply_schema
from .health import HealthChecker, HealthReport, lm_studio_health_check, postgres_health_check


SchemaApplier = Callable[[Any], None]


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    connection_factory: Any
    schema_applier: SchemaApplier = apply_schema
    health_transport: Callable[[str], bytes] | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "AppContext":
        settings = Settings.from_env(environment)
        return cls(
            settings=settings,
            connection_factory=PostgresConnectionFactory(settings.database_url),
        )

    def migrate(self) -> None:
        with self.connection_factory.connection() as connection:
            self.schema_applier(connection)

    def online_health_report(self) -> HealthReport:
        lm_studio_transport = self.health_transport
        checker = HealthChecker(
            {
                "postgres": lambda: postgres_health_check(self.connection_factory),
                "lm_studio": lambda: self._lm_studio_health_check(lm_studio_transport),
            }
        )
        return checker.check()

    def _lm_studio_health_check(self, transport: Callable[[str], bytes] | None):
        if transport is None:
            return lm_studio_health_check(self.settings.lm_studio_base_url)
        return lm_studio_health_check(self.settings.lm_studio_base_url, transport)
