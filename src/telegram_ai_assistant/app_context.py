from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import ConfigError, Settings
from .db.connection import PostgresConnectionFactory
from .db.migrations import apply_schema
from .health import HealthChecker, HealthReport, lm_studio_health_check, postgres_health_check
from .ingestion.backfill import BackfillService
from .ingestion.chat_policy import ChatIngestionPolicy
from .ingestion.listener import LiveUpdateListener
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
    backfill_factory: Any = BackfillService
    listener_factory: Any = LiveUpdateListener
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

    async def run_backfill_once(self):
        start_at = self.settings.telegram_backfill_start_at
        end_at = self.settings.telegram_backfill_end_at
        if self.settings.telegram_backfill_chat_id == 0:
            raise ConfigError("missing required setting: TELEGRAM_BACKFILL_CHAT_ID")
        if start_at is None:
            raise ConfigError("missing required setting: TELEGRAM_BACKFILL_START_AT")
        if end_at is None:
            raise ConfigError("missing required setting: TELEGRAM_BACKFILL_END_AT")

        backfill = self.backfill_factory(
            account_id=self.settings.telegram_ingest_account_id,
            chat_id=self.settings.telegram_backfill_chat_id,
            start_at=start_at,
            end_at=end_at,
            before_message_id=None,
            limit=self.settings.telegram_backfill_limit,
            connection_factory=self.connection_factory,
            client_factory=self.telegram_client_factory(self.settings),
        )
        return await backfill.run_once()

    async def run_listener_forever(self):
        listener = self.listener_factory(
            account_id=self.settings.telegram_ingest_account_id,
            connection_factory=self.connection_factory,
            client_factory=self.telegram_client_factory(self.settings),
            policy=ChatIngestionPolicy(
                allowed_channel_ids=self.settings.telegram_listener_allowed_channel_ids,
                denied_chat_ids=self.settings.telegram_listener_denied_chat_ids,
            ),
        )
        return await listener.run_forever()
