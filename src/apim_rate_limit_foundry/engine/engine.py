"""Thin facade composing the configuration, admission, usage and report services."""

from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine.admission_resolver import AdmissionResolver
from apim_rate_limit_foundry.engine.admission_service import AdmissionService
from apim_rate_limit_foundry.engine.chargeback_aggregator import ChargebackAggregator
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.configuration_service import ConfigurationService
from apim_rate_limit_foundry.engine.configuration_validator import ConfigurationValidator
from apim_rate_limit_foundry.engine.report_service import ReportService
from apim_rate_limit_foundry.engine.usage_recorder import UsageRecorder
from apim_rate_limit_foundry.models import BudgetCheck
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.stores.contracts import CounterStore, Record, Repository


class Engine:
    """Apply tenant/hierarchy policy using injected durable and operational stores.

    Warm admission and accounting depend on operational storage, not Table reads or
    writes. Durable configuration is loaded on cache misses; history is mirrored
    best-effort. Redis errors propagate rather than triggering a ledger fallback.
    The facade only wires services and delegates; behavior lives in each service.
    """

    def __init__(self, repository: Repository, counters: CounterStore, settings: Settings) -> None:
        """Bind stores and build this process's services around one best-effort mirror."""
        self.repository = repository
        self.counters = counters
        self.settings = settings
        self.background = BackgroundWriter()
        resolver = AdmissionResolver(settings)
        reader = ConfigurationReader(repository, counters)
        self._reader = reader
        self._configuration = ConfigurationService(
            repository, counters, reader, ConfigurationValidator(repository, reader)
        )
        self._admission = AdmissionService(repository, counters, self.background, reader, resolver)
        self._usage = UsageRecorder(repository, counters, self.background, resolver)
        self._reports = ReportService(repository, counters, reader, ChargebackAggregator())

    async def configuration(self, collection: str) -> list[Record]:
        """List durable records, hiding tombstones and legacy application-scoped schemas."""
        return await self._reader.configuration(collection)

    async def save_configuration(
        self, collection: str, record_id: str, record: Record, actor_tenant: str, actor: str
    ) -> Record:
        """Validate and durably replace configuration with an atomic audit record."""
        return await self._configuration.save(collection, record_id, record, actor_tenant, actor)

    async def delete_configuration(
        self, collection: str, record_id: str, actor_tenant: str, actor: str
    ) -> None:
        """Durably tombstone a valid configuration record and invalidate its cache."""
        await self._configuration.delete(collection, record_id, actor_tenant, actor)

    async def check(self, check: BudgetCheck) -> Record:
        """Return a traced allow/deny decision, or propagate invalid context/store errors."""
        return await self._admission.check(check)

    async def has_assignment(self, tenant_id: str, principal_id: str) -> bool:
        """Report whether the user has exactly one enabled tenant assignment."""
        return await self._admission.has_assignment(tenant_id, principal_id)

    async def record_usage(self, body: UsageRecordRequest) -> Record:
        """Finalize one request and return ``event`` plus its ``replayed`` flag."""
        return await self._usage.record(body)

    async def usage(
        self, tenant_id: str, principal_id: str, admin: bool, month: str | None = None
    ) -> list[Record]:
        """Return eventually persisted events for one UTC month (default: current)."""
        return await self._reports.usage(tenant_id, principal_id, admin, month)

    async def budget_status(
        self, tenant_id: str, principal_id: str, admin: bool = False
    ) -> list[Record]:
        """Combine durable visible caps with live Redis current-month spend."""
        return await self._reports.budget_status(tenant_id, principal_id, admin)

    async def chargeback(
        self, tenant_id: str, month: str, principal_id: str | None
    ) -> list[Record]:
        """Aggregate durable monthly events by their original chargeback dimensions."""
        return await self._reports.chargeback(tenant_id, month, principal_id)
