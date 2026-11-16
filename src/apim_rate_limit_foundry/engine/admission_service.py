"""Decide whether a request may dispatch and pin the facts its accounting will use."""

from datetime import UTC, datetime

from apim_rate_limit_foundry.accounting import digest, utc_month
from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.engine.admission_resolver import AdmissionResolver
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.events import event
from apim_rate_limit_foundry.engine.keys import budget_counter_key, opaque
from apim_rate_limit_foundry.models import Assignment, Budget, BudgetCheck, Price
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import emit, operation_span


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
        records = await self.reader.configuration("assignments")
        return self.resolver.assignment(tenant_id, principal_id, records) is not None

    async def _check(self, check: BudgetCheck) -> Record:
        """Replay a compatible context or evaluate all applicable current-month caps."""
        fingerprint = self._fingerprint(check)
        saved = await self.counters.request(check.request_id)
        if saved is not None:
            return await self._replay_decision(check, fingerprint, saved)
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
        spend = await self._spend(matching, month)
        # Compare completed spend only: even a zero cap denies, but no tokens or
        # money are reserved between this read and subsequent provider dispatch.
        denied = [budget.id for budget in matching if spend[budget.id] >= budget.limit_micro_usd]
        decision = self._decision(check, denied, reset)
        # Pin admission-time facts so reassignment, price edits or month rollover
        # cannot retroactively change this request's accounting attribution.
        data = {
            "fingerprint": fingerprint,
            "check": check.model_dump(mode="json"),
            "assignment": assignment.model_dump(mode="json"),
            "organization": organization,
            "price": price.model_dump(mode="json"),
            "price_version": price.version,
            "model_bounds": self.resolver.model_bounds(deployment).model_dump(),
            "month": month,
            "decision": {key: value for key, value in decision.items() if key != "request_id"},
        }
        request_key = digest(check.tenant_id, check.request_id)
        context = event("request", request_key, check.tenant_id, check.principal_id, data)
        # First writer wins for this raw request ID, including denied decisions.
        # A concurrent loser must validate the winner instead of dispatching anew.
        saved, created = await self.counters.admit(check.request_id, context)
        if not created:
            return await self._replay_decision(check, fingerprint, saved)
        self.background.submit(
            "requests",
            request_key,
            lambda: self.repository.create("requests", request_key, context),
        )
        self._emit_evaluations(check, assignment, matching, spend, denied, month, decision)
        self._emit_decision(check, assignment, matching, denied, month, price, decision)
        rate_metrics.decision(
            check.model, check.api_protocol, check.streaming, decision["allowed"], False
        )
        return decision

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

    async def _spend(self, budgets: list[Budget], month: str) -> dict[str, int]:
        """Read current completed spend for each matching budget, keyed by budget ID."""
        keys = {budget.id: budget_counter_key(budget, month) for budget in budgets}
        totals = await self.counters.totals(month, list(keys.values()))
        return {budget_id: totals[key] for budget_id, key in keys.items()}

    @staticmethod
    def _decision(check: BudgetCheck, denied: list[str], reset: datetime) -> Record:
        """Build the gateway response for a set of exhausted budget IDs."""
        allowed = not denied
        return {
            "allowed": allowed,
            "request_id": check.request_id,
            "reason": "allowed" if allowed else "budget_exhausted",
            "denied_budget_ids": denied,
            "reset_at": reset.isoformat(),
            "retry_after": max(1, int((reset - datetime.now(UTC)).total_seconds())),
        }

    @staticmethod
    def _emit_evaluations(
        check: BudgetCheck,
        assignment: Assignment,
        matching: list[Budget],
        spend: dict[str, int],
        denied: list[str],
        month: str,
        decision: Record,
    ) -> None:
        """Emit one evaluation event per matching budget."""
        for budget in matching:
            spent = spend[budget.id]
            emit(
                "budget_evaluated",
                budget_id=budget.id,
                budget_model=budget.model,
                subject_type=budget.subject_type,
                month=month,
                limit_micro_usd=budget.limit_micro_usd,
                spent_micro_usd=spent,
                remaining_micro_usd=max(0, budget.limit_micro_usd - spent),
                allowed=budget.id not in denied,
                reason="budget_exhausted" if budget.id in denied else "within_budget",
                reset_at=decision["reset_at"],
                user_ref=opaque(check.tenant_id, check.principal_id),
                team_id=assignment.team_id,
                department_id=assignment.department_id,
            )

    @staticmethod
    def _emit_decision(
        check: BudgetCheck,
        assignment: Assignment,
        matching: list[Budget],
        denied: list[str],
        month: str,
        price: Price,
        decision: Record,
    ) -> None:
        """Emit the summary event for a freshly admitted (not replayed) decision."""
        emit(
            "budget_decision",
            allowed=decision["allowed"],
            reason=decision["reason"],
            model=check.model,
            user_ref=opaque(check.tenant_id, check.principal_id),
            team_id=assignment.team_id,
            department_id=assignment.department_id,
            denied_budget_ids=denied,
            budget_ids=[budget.id for budget in matching],
            budget_count=len(matching),
            denied_budget_count=len(denied),
            month=month,
            price_version=price.version,
            reset_at=decision["reset_at"],
            retry_after=decision["retry_after"],
            replayed=False,
        )

    async def _replay_decision(self, check: BudgetCheck, fingerprint: str, saved: Record) -> Record:
        """Reuse the pinned decision only for identical, not-yet-finalized requests.

        Replays do not re-evaluate changed budgets or recompute reset timing.
        Protection lasts only while request/usage keys survive in operational storage.
        """
        data = saved["data"]
        if data["fingerprint"] != fingerprint:
            raise Conflict("Request ID reused with different request")
        if await self.counters.usage(check.request_id) is not None:
            raise Conflict("Completed request IDs cannot be dispatched again")
        result = data["decision"]
        emit(
            "budget_decision",
            **result,
            month=data["month"],
            price_version=data["price_version"],
            user_ref=opaque(check.tenant_id, check.principal_id),
            team_id=data["organization"]["team_id"],
            department_id=data["organization"]["department_id"],
            denied_budget_count=len(result["denied_budget_ids"]),
            replayed=True,
        )
        rate_metrics.decision(
            check.model, check.api_protocol, check.streaming, result["allowed"], True
        )
        return {**result, "request_id": check.request_id}
