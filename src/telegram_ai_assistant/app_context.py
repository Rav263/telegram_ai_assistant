from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import Settings
from .db.connection import PostgresConnectionFactory
from .db.migrations import apply_schema


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
