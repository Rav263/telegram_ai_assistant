from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import Settings
from .db.connection import PostgresConnectionFactory
from .db.migrations import apply_schema
from .health import HealthChecker, HealthReport, lm_studio_health_check, postgres_health_check
from .ingestion.live import LiveIngestor
from .ingestion.telethon_adapter import TelethonIngestionAdapter


SchemaApplier = Callable[[Any], None]


def default_telegram_client_factory(settings: Settings):
    return lambda: TelethonIngestionAdapter.connect(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    connection_factory: Any
    schema_applier: SchemaApplier = apply_schema
    health_transport: Callable[[str], bytes] | None = None
    ingestor_factory: Any = LiveIngestor
    telegram_client_factory: Callable[[Settings], Any] = default_telegram_client_factory

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "AppContext":
        settings = Settings.from_env(environment)
        return cls.from_settings(settings)

    @classmethod
    def from_settings(cls, settings: Settings) -> "AppContext":
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

    async def run_ingestor_once(self):
        ingestor = self.ingestor_factory(
            account_id=self.settings.telegram_ingest_account_id,
            chat_id=self.settings.telegram_ingest_chat_id,
            limit=self.settings.telegram_ingest_limit,
            debug_messages=self.settings.telegram_ingest_debug_messages,
            bootstrap_mode=self.settings.telegram_ingest_bootstrap_mode,
            bootstrap_days=self.settings.telegram_ingest_bootstrap_days,
            connection_factory=self.connection_factory,
            client_factory=self.telegram_client_factory(self.settings),
        )
        return await ingestor.run_once()
