"""Decide whether a request may dispatch and pin the facts its accounting will use."""

from datetime import UTC, datetime

from apim_rate_limit_foundry.accounting import digest, utc_month
from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.engine.admission_resolver import AdmissionResolver
from apim_rate_limit_foundry.engine.admission_telemetry import AdmissionTelemetry
from apim_rate_limit_foundry.engine.budget_status_reporter import BudgetStatusReporter
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.events import event
from apim_rate_limit_foundry.engine.spend import read_spend
from apim_rate_limit_foundry.models import BudgetCheck
from apim_rate_limit_foundry.models.admission_context import AdmissionContext
from apim_rate_limit_foundry.models.admission_decision import AdmissionDecision
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import operation_span


class AdmissionService:
    """Evaluate soft-cap budgets from Redis spend and pin one decision per request ID.

    Admission saves price, organization and model-bound snapshots for later
    accounting. Budgets are soft caps: checks inspect current spend but reserve
    nothing, so concurrent or in-flight requests can overshoot a limit.
    """

    def __init__(
        self,
        repository: Repository,
        counters: CounterStore,
        background: BackgroundWriter,
        reader: ConfigurationReader,
        resolver: AdmissionResolver,
    ) -> None:
        """Bind stores, the best-effort mirror, configuration reader and fact resolver."""
        self.repository = repository
        self.counters = counters
        self.background = background
        self.reader = reader
        self.resolver = resolver

    async def check(self, check: BudgetCheck) -> Record:
        """Return a traced allow/deny decision, or propagate invalid context/store errors.

        Responses contain request ID, reason, denied budget IDs, UTC reset and
        retry seconds. Success means Redis context acceptance, not Table durability
        or a reservation for the eventual provider charge.
        """
        with operation_span(
            "budget.check",
            request_id=check.request_id,
            model=check.model,
            api_protocol=check.api_protocol,
            subscription_id=check.subscription_id,
            streaming=check.streaming,
        ):
            return await self._check(check)

    async def has_assignment(self, tenant_id: str, principal_id: str) -> bool:
        """Report whether the user has exactly one enabled tenant assignment."""
        configuration = await self.reader.snapshot()
        assignment = self.resolver.assignment(tenant_id, principal_id, configuration["assignments"])
        return assignment is not None

    async def _check(self, check: BudgetCheck) -> Record:
        """Replay a compatible context or evaluate all applicable current-month caps."""
        fingerprint = self._fingerprint(check)
        saved = await self.counters.request(check.request_id)
        if saved is not None:
            return await self._replay_decision(check, fingerprint, saved)
        context, spend = await self._evaluate(check, fingerprint)
        request_key = digest(check.tenant_id, check.request_id)
        request = event(
            "request",
            request_key,
            check.tenant_id,
            check.principal_id,
            context.model_dump(mode="json"),
        )
        # First writer wins for this raw request ID, including denied decisions.
        # A concurrent loser must validate the winner instead of dispatching anew.
        saved, created = await self.counters.admit(check.request_id, request)
        if not created:
            return await self._replay_decision(check, fingerprint, saved)
        self.background.submit(
            "requests",
            request_key,
            lambda: self.repository.create("requests", request_key, request),
        )
        AdmissionTelemetry.evaluated(check, context, spend)
        AdmissionTelemetry.decided(check, context, replayed=False)
        return self._response(check, context)

    async def _evaluate(
        self, check: BudgetCheck, fingerprint: str
    ) -> tuple[AdmissionContext, dict[str, int]]:
        """Resolve the caller's facts and decide against current spend, pinning both."""
        configuration = await self.reader.snapshot()
        assignment = self.resolver.assignment(
            check.tenant_id, check.principal_id, configuration["assignments"]
        )
        if assignment is None:
            raise ValueError("Unknown or unassigned user")
        organization = self.resolver.organization_context(
            assignment, configuration["organizations"]
        )
        deployment = self.resolver.deployment(check)
        price = self.resolver.price(check, configuration["prices"])
        month, reset = utc_month()
        matching = self.resolver.matching_budgets(check, assignment, configuration["budgets"])
        spend = await read_spend(self.counters, matching, month)
        # Compare completed spend only: even a zero cap denies, but no tokens or
        # money are reserved between this read and subsequent provider dispatch.
        denied = [budget.id for budget in matching if spend[budget.id] >= budget.limit_micro_usd]
        # Pin admission-time facts so reassignment, price edits or month rollover
        # cannot retroactively change this request's accounting attribution.
        context = AdmissionContext(
            fingerprint=fingerprint,
            check=check,
            assignment=assignment,
            organization=organization,
            price=price,
            price_version=price.version,
            model_bounds=self.resolver.model_bounds(deployment),
            month=month,
            budgets=BudgetStatusReporter.pin(matching, month),
            decision=AdmissionDecision(
                allowed=not denied,
                reason="budget_exhausted" if denied else "allowed",
                denied_budget_ids=denied,
                reset_at=reset.isoformat(),
                retry_after=max(1, int((reset - datetime.now(UTC)).total_seconds())),
            ),
        )
        return context, spend

    @staticmethod
    def _fingerprint(check: BudgetCheck) -> str:
        """Hash the request attributes a retry of the same request ID must repeat."""
        return digest(
            check.tenant_id,
            check.principal_id,
            check.subscription_id,
            check.model,
            check.api_protocol,
            str(check.streaming),
        )

    @staticmethod
    def _response(check: BudgetCheck, context: AdmissionContext) -> Record:
        """Build the gateway response from a pinned decision."""
        return {**context.decision.model_dump(), "request_id": check.request_id}

    async def _replay_decision(self, check: BudgetCheck, fingerprint: str, saved: Record) -> Record:
        """Reuse the pinned decision only for identical, not-yet-finalized requests.

        Replays do not re-evaluate changed budgets or recompute reset timing.
        Protection lasts only while request/usage keys survive in operational storage.
        """
        context = AdmissionContext.model_validate(saved["data"])
        if context.fingerprint != fingerprint:
            raise Conflict("Request ID reused with different request")
        if await self.counters.usage(check.request_id) is not None:
            raise Conflict("Completed request IDs cannot be dispatched again")
        AdmissionTelemetry.decided(check, context, replayed=True)
        return self._response(check, context)
