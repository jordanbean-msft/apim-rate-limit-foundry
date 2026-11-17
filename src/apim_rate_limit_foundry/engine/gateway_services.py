"""Compose the budget services around one set of stores and a best-effort background writer."""

from dataclasses import dataclass

from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine.admission_resolver import AdmissionResolver
from apim_rate_limit_foundry.engine.admission_service import AdmissionService
from apim_rate_limit_foundry.engine.budget_status_reporter import BudgetStatusReporter
from apim_rate_limit_foundry.engine.chargeback_aggregator import ChargebackAggregator
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.configuration_service import ConfigurationService
from apim_rate_limit_foundry.engine.configuration_validator import ConfigurationValidator
from apim_rate_limit_foundry.engine.report_service import ReportService
from apim_rate_limit_foundry.engine.usage_recorder import UsageRecorder
from apim_rate_limit_foundry.export.usage_event_publisher import UsageEventPublisher
from apim_rate_limit_foundry.stores.contracts import CounterStore, Repository


@dataclass(frozen=True)
class GatewayServices:
    """The wired services and the stores they share; callers use each service directly.

    Warm admission and accounting depend on operational storage, not Table reads or
    writes. Durable configuration is loaded on cache misses; history is mirrored
    best-effort. Redis errors propagate rather than triggering a ledger fallback.
    """

    settings: Settings
    repository: Repository
    counters: CounterStore
    background: BackgroundWriter
    publisher: UsageEventPublisher | None
    admission: AdmissionService
    usage: UsageRecorder
    configuration: ConfigurationService
    reports: ReportService

    @classmethod
    def create(
        cls,
        repository: Repository,
        counters: CounterStore,
        settings: Settings,
        publisher: UsageEventPublisher | None = None,
    ) -> "GatewayServices":
        """Build this process's services around one shared best-effort mirror."""
        background = BackgroundWriter()
        reader = ConfigurationReader(repository, counters)
        return cls(
            settings=settings,
            repository=repository,
            counters=counters,
            background=background,
            publisher=publisher,
            admission=AdmissionService(
                repository, counters, background, reader, AdmissionResolver(settings)
            ),
            usage=UsageRecorder(
                repository, counters, background, BudgetStatusReporter(counters), publisher
            ),
            configuration=ConfigurationService(
                repository, counters, reader, ConfigurationValidator(repository, reader)
            ),
            reports=ReportService(repository, counters, reader, ChargebackAggregator()),
        )

    async def close(self) -> None:
        """Drain best-effort jobs before closing the clients those jobs still need.

        The writer's bounded drain is not a guarantee of persistence at shutdown.
        """
        await self.background.close()
        if self.publisher is not None:
            await self.publisher.close()
        await self.repository.close()
        await self.counters.close()
