from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .config import ConfigError, Settings
from .bot_api import TelegramBotApi
from .bot_router import BotRouter
from .bot_runtime import BotRuntime
from .bot_services import BotServices
from .db.connection import PostgresConnectionFactory
from .db.migrations import apply_schema
from .db.repositories import (
    BackfillJobQueryRepository,
    BotRuntimeStateRepository,
    CandidateRepository,
    ItemRepository,
    ItemQueryRepository,
    LLMRunRepository,
    MessageProcessingRepository,
    ReviewRepository,
    RuntimeEventRepository,
)
from .extraction import ExtractionService
from .health import HealthChecker, HealthReport, lm_studio_health_check, postgres_health_check
from .ingestion.backfill import BackfillService
from .ingestion.chat_policy import ChatIngestionPolicy
from .ingestion.listener import LiveUpdateListener
from .ingestion.live import LiveIngestor
from .ingestion.telethon_adapter import TelethonIngestionAdapter, mtproxy_client_kwargs
from .llm_client import LMStudioClient
from .security import BotAccessController
from .worker import Worker, WorkerResult


SchemaApplier = Callable[[Any], None]


def default_telegram_client_factory(settings: Settings):
    return lambda: TelethonIngestionAdapter.connect(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        **mtproxy_client_kwargs(
            host=settings.telegram_mtproxy_host,
            port=settings.telegram_mtproxy_port,
            secret=settings.telegram_mtproxy_secret,
        ),
    )


def default_lm_studio_client_factory(settings: Settings):
    return LMStudioClient(
        base_url=settings.lm_studio_base_url,
        model=settings.lm_studio_model,
        max_tokens=settings.lm_studio_max_tokens,
    )


def default_bot_api_factory(settings: Settings):
    return TelegramBotApi(token=settings.telegram_bot_token)


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    connection_factory: Any
    schema_applier: SchemaApplier = apply_schema
    health_transport: Callable[[str], bytes] | None = None
    ingestor_factory: Any = LiveIngestor
    backfill_factory: Any = BackfillService
    listener_factory: Any = LiveUpdateListener
    worker_factory: Any = Worker
    extraction_service_factory: Any = ExtractionService
    bot_api_factory: Callable[[Settings], Any] = default_bot_api_factory
    bot_runtime_factory: Any = BotRuntime
    telegram_client_factory: Callable[[Settings], Any] = default_telegram_client_factory
    lm_studio_client_factory: Callable[[Settings], Any] = default_lm_studio_client_factory

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

    def run_worker_once(self) -> WorkerResult:
        with self.connection_factory.connection() as connection:
            extraction_service = self.extraction_service_factory(
                llm_client=self.lm_studio_client_factory(self.settings),
            )
            worker = self.worker_factory(
                message_source=MessageProcessingRepository(connection),
                candidate_repository=CandidateRepository(connection),
                extraction_service=extraction_service,
                item_repository=ItemRepository(
                    connection,
                    account_id=self.settings.telegram_ingest_account_id,
                ),
                review_repository=ReviewRepository(
                    connection,
                    account_id=self.settings.telegram_ingest_account_id,
                ),
                llm_run_repository=LLMRunRepository(connection),
                runtime_event_repository=RuntimeEventRepository(connection),
                item_auto_apply_threshold=self.settings.worker_item_auto_apply_threshold,
                status_auto_apply_threshold=self.settings.worker_status_auto_apply_threshold,
            )
            return merge_worker_results(
                worker.process_messages(limit=self.settings.worker_batch_size),
                worker.process_candidates(limit=self.settings.worker_batch_size),
            )

    def run_bot_forever(self, *, stop_requested: Callable[[], bool] | None = None):
        with self.connection_factory.connection() as connection:
            runtime_event_repository = RuntimeEventRepository(connection)
            bot_api = self.bot_api_factory(self.settings)
            item_query_repository = ItemQueryRepository(
                connection,
                account_id=self.settings.telegram_ingest_account_id,
            )
            review_repository = ReviewRepository(
                connection,
                account_id=self.settings.telegram_ingest_account_id,
            )
            router = BotRouter(
                access=BotAccessController(self.settings.telegram_allowed_user_id),
                bot_api=bot_api,
                services=BotServices(
                    runtime_event_repository=runtime_event_repository,
                    health_report_provider=self.online_health_report,
                    item_query_repository=item_query_repository,
                    item_repository=ItemRepository(
                        connection,
                        account_id=self.settings.telegram_ingest_account_id,
                    ),
                    summary_query_repository=item_query_repository,
                    review_repository=review_repository,
                    backfill_job_query_repository=BackfillJobQueryRepository(
                        connection,
                        account_id=self.settings.telegram_ingest_account_id,
                    ),
                    settings_snapshot=self.settings,
                ),
            )
            runtime = self.bot_runtime_factory(
                bot_api=bot_api,
                router=router,
                runtime_event_repository=runtime_event_repository,
                state_repository=BotRuntimeStateRepository(connection),
                commit=connection.commit,
            )
            return runtime.run_forever(stop_requested=stop_requested)


def merge_worker_results(*results: WorkerResult) -> WorkerResult:
    return WorkerResult(
        scored_messages=sum(result.scored_messages for result in results),
        queued_candidates=sum(result.queued_candidates for result in results),
        processed_candidates=sum(result.processed_candidates for result in results),
        extracted_items=sum(result.extracted_items for result in results),
        saved_items=sum(result.saved_items for result in results),
        review_items=sum(result.review_items for result in results),
        review_status_changes=sum(result.review_status_changes for result in results),
        failures=sum(result.failures for result in results),
    )
