"""Coordinate Redis-first budget decisions, usage accounting and eventual reports.

Warm admission and accounting depend on operational storage, not Table reads or
writes. Durable configuration is loaded on cache misses; history is mirrored
best-effort. Redis errors propagate rather than triggering a ledger fallback.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from apim_rate_limit_foundry.accounting import (
    cost_micro_usd,
    digest,
    normalize_openai_usage,
    utc_month,
)
from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models import Assignment, Budget, BudgetCheck, Organization, Price
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import emit, operation_span

CONFIG_MODELS: dict[str, type[Organization] | type[Assignment] | type[Budget] | type[Price]] = {
    "organizations": Organization,
    "assignments": Assignment,
    "budgets": Budget,
    "prices": Price,
}
USAGE_COLLECTION = "usage_v2"


def event(kind: str, record_id: str, tenant: str, principal: str, data: Record) -> Record:
    """Wrap a supplied payload with durable identity and a UTC creation timestamp."""
    return {
        "id": record_id,
        "kind": kind,
        "tenant_id": tenant,
        "principal_id": principal,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }


class Engine:
    """Apply tenant/hierarchy policy using injected durable and operational stores.

    Admission saves price, organization and model-bound snapshots for later
    accounting. Budgets are soft caps: checks inspect current spend but reserve
    nothing, so concurrent or in-flight requests can overshoot a limit.
    """

    def __init__(self, repository: Repository, counters: CounterStore, settings: Settings) -> None:
        """Bind stores and allocate this process's best-effort mirror and load lock."""
        self.repository = repository
        self.counters = counters
        self.settings = settings
        self.background = BackgroundWriter()
        self._configuration_lock = asyncio.Lock()

    async def _cached_configuration(self) -> Record:
        """Read shared configuration, loading all durable collections only on a miss.

        The lock coalesces misses within this engine, not across hosts. TTL expiry
        and admin invalidation bound normal staleness; this is not a distributed
        configuration transaction or lock against concurrent administrative writes.
        """
        snapshot = await self.counters.configuration()
        if snapshot is not None:
            return snapshot
        async with self._configuration_lock:
            snapshot = await self.counters.configuration()
            if snapshot is None:
                values = await asyncio.gather(
                    *(self.configuration(collection) for collection in CONFIG_MODELS)
                )
                snapshot = dict(zip(CONFIG_MODELS, values, strict=True))
                await self.counters.cache_configuration(snapshot)
                emit("configuration_cache_loaded")
        return snapshot

    async def configuration(self, collection: str) -> list[Record]:
        """List durable records, hiding tombstones and incompatible legacy schemas.

        Known configuration collections are validated and normalized. Tenant
        scoping is the responsibility of the calling operation.
        """
        model = CONFIG_MODELS.get(collection)
        records = []
        for record in await self.repository.list(collection):
            if record.get("_deleted"):
                continue
            if model is not None:
                try:
                    record = model.model_validate(record).model_dump(mode="json", exclude_none=True)
                except ValidationError:
                    # Legacy application-scoped records remain archived, not reinterpreted.
                    continue
            records.append(record)
        return records

    async def save_configuration(
        self, collection: str, record_id: str, record: Record, actor_tenant: str, actor: str
    ) -> Record:
        """Validate and durably replace configuration with an atomic audit record.

        Enforce actor tenant, ID and hierarchy constraints before writing, then
        invalidate shared configuration. Invalidation failure propagates after
        the durable write has already committed; no rollback is attempted.
        """
        model = CONFIG_MODELS.get(collection)
        if model is None:
            raise ValueError("Unsupported configuration collection")
        try:
            parsed = model.model_validate(record)
        except ValidationError as error:
            raise ValueError("Invalid configuration record") from error
        normalized = parsed.model_dump(mode="json", exclude_none=True)
        if normalized["id"] != record_id:
            raise ValueError("Path ID must match body ID")
        existing = await self.repository.get(collection, record_id)
        if existing and not existing.get("_deleted"):
            if existing.get("tenant_id") not in (None, actor_tenant):
                raise Conflict("Configuration record belongs to another tenant")
            try:
                model.model_validate(existing)
            except ValidationError as error:
                raise Conflict(
                    "Legacy configuration must be archived before replacement"
                ) from error
        if "tenant_id" in normalized and normalized["tenant_id"] != actor_tenant:
            raise ValueError("Configuration tenant must match the administrator")
        if isinstance(parsed, Assignment):
            await self._validate_assignment(parsed)
        if isinstance(parsed, Organization):
            await self._validate_organization(parsed)
        if isinstance(parsed, Budget):
            if parsed.tenant_id != actor_tenant:
                raise ValueError("Budget tenant must match the administrator")
            await self._validate_budget(parsed)
        audit = event(
            "configuration",
            uuid4().hex,
            actor_tenant,
            actor,
            {"action": "put", "collection": collection, "record_id": record_id},
        )
        await self.repository.mutate(collection, record_id, normalized, audit)
        await self.counters.invalidate_configuration()
        return normalized

    async def delete_configuration(
        self, collection: str, record_id: str, actor_tenant: str, actor: str
    ) -> None:
        """Durably tombstone a valid configuration record and invalidate its cache.

        Missing/deleted IDs are no-ops. Reject cross-tenant records, legacy
        schemas and organization deletions with children or active assignments.
        The audit and tombstone commit together before cache invalidation.
        """
        if collection not in CONFIG_MODELS:
            raise ValueError("Unsupported configuration collection")
        current = await self.repository.get(collection, record_id)
        if current is None or current.get("_deleted"):
            return
        try:
            CONFIG_MODELS[collection].model_validate(current)
        except ValidationError as error:
            raise Conflict(
                "Legacy configuration must be archived, not deleted by the new API"
            ) from error
        if current.get("tenant_id", actor_tenant) != actor_tenant:
            raise ValueError("Configuration tenant must match the administrator")
        if collection == "organizations":
            dependents = await self.configuration("organizations")
            assignments = await self.configuration("assignments")
            if any(row.get("department_id") == record_id for row in dependents):
                raise ValueError("Organization units with child teams cannot be deleted")
            if any(
                row.get("enabled") is True
                and record_id in (row.get("team_id"), row.get("department_id"))
                for row in assignments
            ):
                raise ValueError("Organization units with active assignments cannot be deleted")
        audit = event(
            "configuration",
            uuid4().hex,
            actor_tenant,
            actor,
            {"action": "delete", "collection": collection, "record_id": record_id},
        )
        await self.repository.mutate(collection, record_id, None, audit)
        await self.counters.invalidate_configuration()

    async def _validate_assignment(self, assignment: Assignment) -> None:
        """Require one active user assignment and an enabled same-tenant parent chain."""
        for existing in await self.configuration("assignments"):
            if existing.get("id") != assignment.id and (
                existing.get("tenant_id") == assignment.tenant_id
                and existing.get("principal_id") == assignment.principal_id
                and existing.get("enabled") is True
                and assignment.enabled
            ):
                raise ValueError("An active assignment already exists for this user")
        organizations = [
            Organization.model_validate(r) for r in await self.configuration("organizations")
        ]
        team = next(
            (
                item
                for item in organizations
                if item.id == assignment.team_id
                and item.kind == "team"
                and item.tenant_id == assignment.tenant_id
                and item.enabled
            ),
            None,
        )
        department = next(
            (
                item
                for item in organizations
                if item.id == assignment.department_id
                and item.kind == "department"
                and item.tenant_id == assignment.tenant_id
                and item.enabled
            ),
            None,
        )
        if team is None or department is None or team.department_id != department.id:
            raise ValueError("Assignment requires an enabled team and its enabled department")

    async def _validate_organization(self, organization: Organization) -> None:
        """Require a team's parent to be an enabled department in the same tenant."""
        if organization.kind != "team":
            return
        parent = await self.repository.get("organizations", organization.department_id or "")
        if (
            parent is None
            or parent.get("_deleted")
            or parent.get("kind") != "department"
            or parent.get("enabled") is not True
            or parent.get("tenant_id") != organization.tenant_id
        ):
            raise ValueError("Team parent must be an enabled department in the same tenant")

    async def _validate_budget(self, budget: Budget) -> None:
        """Reject budget subjects without an active matching user or organization."""
        if budget.subject_type == "user":
            valid = any(
                row.get("tenant_id") == budget.tenant_id
                and row.get("principal_id") == budget.subject_id
                and row.get("enabled") is True
                for row in await self.configuration("assignments")
            )
        else:
            organization = await self.repository.get("organizations", budget.subject_id)
            expected_kind = "team" if budget.subject_type == "team" else "department"
            valid = bool(
                organization
                and not organization.get("_deleted")
                and organization.get("kind") == expected_kind
                and organization.get("tenant_id") == budget.tenant_id
                and organization.get("enabled") is True
            )
        if not valid:
            raise ValueError("Budget subject must be an active user or organization unit")

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

    async def _check(self, check: BudgetCheck) -> Record:
        """Replay a compatible context or evaluate all applicable current-month caps."""
        request_key = digest(check.tenant_id, check.request_id)
        fingerprint = digest(
            check.tenant_id,
            check.principal_id,
            check.subscription_id,
            check.model,
            check.api_protocol,
            str(check.streaming),
        )
        saved = await self.counters.request(check.request_id)
        if saved is not None:
            return await self._replay_decision(check, fingerprint, saved)
        configuration = await self._cached_configuration()
        assignment = await self._assignment(
            check.tenant_id, check.principal_id, configuration["assignments"]
        )
        if assignment is None:
            raise ValueError("Unknown or unassigned user")
        organization = await self._organization_context(assignment, configuration["organizations"])
        deployment = (
            self.settings.registered_model(check.api_protocol, check.model)
            if self.settings.model_registry
            else None
        )
        price = await self._get_price(check, configuration["prices"])
        month, reset = utc_month()
        matching = self._matching_budgets(check, assignment, configuration["budgets"])
        keys = {budget.id: _budget_counter_key(budget, month) for budget in matching}
        totals = await self.counters.totals(month, list(keys.values()))
        spend_by_budget = {budget_id: totals[key] for budget_id, key in keys.items()}
        # Compare completed spend only: even a zero cap denies, but no tokens or
        # money are reserved between this read and subsequent provider dispatch.
        denied = [
            budget.id for budget in matching if spend_by_budget[budget.id] >= budget.limit_micro_usd
        ]
        allowed = not denied
        reason = "allowed" if allowed else "budget_exhausted"
        decision = {
            "allowed": allowed,
            "request_id": check.request_id,
            "reason": reason,
            "denied_budget_ids": denied,
            "reset_at": reset.isoformat(),
            "retry_after": max(1, int((reset - datetime.now(UTC)).total_seconds())),
        }
        # Pin admission-time facts so reassignment, price edits or month rollover
        # cannot retroactively change this request's accounting attribution.
        data = {
            "fingerprint": fingerprint,
            "check": check.model_dump(mode="json"),
            "assignment": assignment.model_dump(mode="json"),
            "organization": organization,
            "price": price.model_dump(mode="json"),
            "price_version": price.version,
            "model_bounds": (
                {
                    "max_input_tokens": deployment.max_input_tokens,
                    "max_output_tokens": deployment.max_output_tokens,
                }
                if deployment
                else None
            ),
            "month": month,
            "decision": {key: value for key, value in decision.items() if key != "request_id"},
        }
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
        for budget in matching:
            spent = spend_by_budget[budget.id]
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
                user_ref=_opaque(check.tenant_id, check.principal_id),
                team_id=assignment.team_id,
                department_id=assignment.department_id,
            )
        emit(
            "budget_decision",
            allowed=allowed,
            reason=reason,
            model=check.model,
            user_ref=_opaque(check.tenant_id, check.principal_id),
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
        rate_metrics.decision(check.model, check.api_protocol, check.streaming, allowed, False)
        return decision

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
            user_ref=_opaque(check.tenant_id, check.principal_id),
            team_id=data["organization"]["team_id"],
            department_id=data["organization"]["department_id"],
            denied_budget_count=len(result["denied_budget_ids"]),
            replayed=True,
        )
        rate_metrics.decision(
            check.model, check.api_protocol, check.streaming, result["allowed"], True
        )
        return {**result, "request_id": check.request_id}

    async def _assignment(
        self, tenant_id: str, principal_id: str, records: list[Record] | None = None
    ) -> Assignment | None:
        """Resolve exactly one enabled tenant/user assignment, otherwise return None."""
        records = records if records is not None else await self.configuration("assignments")
        matches = [
            Assignment.model_validate(record)
            for record in records
            if record.get("tenant_id") == tenant_id
            and record.get("principal_id") == principal_id
            and record.get("enabled") is True
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    async def _organization_context(
        self, assignment: Assignment, records: list[Record] | None = None
    ) -> Record:
        """Validate the enabled parent chain and snapshot team chargeback dimensions."""
        organizations = {
            record["id"]: Organization.model_validate(record)
            for record in (
                records if records is not None else await self.configuration("organizations")
            )
        }
        team = organizations.get(assignment.team_id)
        department = organizations.get(assignment.department_id)
        if (
            team is None
            or department is None
            or not team.enabled
            or not department.enabled
            or team.kind != "team"
            or department.kind != "department"
            or team.tenant_id != assignment.tenant_id
            or department.tenant_id != assignment.tenant_id
            or team.department_id != department.id
        ):
            raise ValueError("Assigned organization is unavailable")
        return {
            "team_id": team.id,
            "department_id": department.id,
            "business_unit": team.business_unit,
            "cost_center": team.cost_center,
        }

    async def _get_price(self, check: BudgetCheck, records: list[Record] | None = None) -> Price:
        """Require one model price, pinned to the registry version when configured."""
        version: str | None = None
        if self.settings.model_registry:
            version = self.settings.registered_model(check.api_protocol, check.model).price_version
        matches = [
            Price.model_validate(record)
            for record in (records if records is not None else await self.configuration("prices"))
            if record.get("model") == check.model
            and (version is None or record.get("version") == version)
        ]
        if len(matches) != 1:
            raise ValueError("Exactly one matching price card is required")
        return matches[0]

    @staticmethod
    def _matching_budgets(
        check: BudgetCheck, assignment: Assignment, records: list[Record]
    ) -> list[Budget]:
        """Select enabled same-tenant user/team/department caps for model or wildcard."""
        subjects = {
            ("user", check.principal_id),
            ("team", assignment.team_id),
            ("department", assignment.department_id),
        }
        return [
            budget
            for record in records
            if (budget := Budget.model_validate(record)).enabled
            and budget.tenant_id == check.tenant_id
            and (budget.subject_type, budget.subject_id) in subjects
            and budget.model in ("*", check.model)
        ]

    async def record_usage(self, body: UsageRecordRequest) -> Record:
        """Finalize one request and return ``event`` plus its ``replayed`` flag.

        Acceptance atomically records usage and applicable spend in Redis; Table
        export is asynchronous and lossy. Identical retries return the saved event,
        while conflicting finalizations or missing/denied admission raise Conflict.
        """
        with operation_span("usage.record", request_id=body.request_id):
            return await self._record_usage(body)

    async def _record_usage(self, body: UsageRecordRequest) -> Record:
        """Normalize and price against admission snapshots, then atomically deduplicate."""
        fingerprint = _usage_fingerprint(body)
        prior = await self.counters.usage(body.request_id)
        if prior is not None:
            _validate_usage_replay(prior, body.status, fingerprint)
            emit("usage_record_replayed", **prior["data"]["event"], replayed=True)
            rate_metrics.usage(prior["data"]["event"], True)
            return {"event": prior["data"]["event"], "replayed": True}
        request = await self.counters.request(body.request_id)
        if request is None:
            raise Conflict("Budget check not found in operational cache")
        request_key = request["id"]

        data = request["data"]
        check = data["check"]
        if not data["decision"]["allowed"]:
            raise Conflict("Denied requests cannot be charged")
        usage = None
        cost = None
        status = body.status
        usage_reason = "provider_usage" if status == "actual" else "reported_unknown"
        # Invalid/missing provider usage stays explicitly unknown: never estimate
        # tokens or treat unknown charges as proven zero-cost provider activity.
        if body.status == "actual":
            if body.provider_usage is None:
                status = "usage_unknown"
                usage_reason = "provider_usage_missing"
            else:
                try:
                    usage = normalize_openai_usage(body.provider_usage, check["api_protocol"])
                    bounds = data.get("model_bounds")
                    if bounds and (
                        usage["input_tokens"] > bounds["max_input_tokens"]
                        or usage["output_tokens"] > bounds["max_output_tokens"]
                    ):
                        raise ValueError("Provider usage exceeds the pinned price range")
                    price = Price.model_validate(data["price"])
                    cost = cost_micro_usd(price, usage)
                except (ValueError, KeyError, TypeError):
                    status = "usage_unknown"
                    usage_reason = "provider_usage_invalid"
                    usage = None
                    cost = None
        elif body.provider_usage is not None:
            raise ValueError("Unknown usage must not include fabricated provider counters")

        month = data["month"]
        snapshot = data["organization"]
        # Always update six subject/model projections, even if a matching budget
        # does not yet exist. Later caps therefore see prior operational spend.
        counter_keys = [
            digest(check["tenant_id"], kind, subject_id, month, model)
            for kind, subject_id in (
                ("user", check["principal_id"]),
                ("team", snapshot["team_id"]),
                ("department", snapshot["department_id"]),
            )
            for model in ("*", check["model"])
        ]
        timestamp = datetime.now(UTC).isoformat()
        event_id = digest("usage-event-v2", check["tenant_id"], body.request_id)
        event_data: Record = {
            "event_version": 2,
            "event_name": "usage_recorded",
            "event_id": event_id,
            "request_id": body.request_id,
            "timestamp": timestamp,
            "month": month,
            "tenant_ref": _opaque(check["tenant_id"]),
            "user_ref": _opaque(check["tenant_id"], check["principal_id"]),
            "team_id": snapshot["team_id"],
            "department_id": snapshot["department_id"],
            "business_unit": snapshot["business_unit"],
            "cost_center": snapshot["cost_center"],
            "subscription_id": check["subscription_id"],
            "model": check["model"],
            "api_protocol": check["api_protocol"],
            "streaming": check["streaming"],
            "status": status,
            "input_tokens": usage["input_tokens"] if usage else None,
            "cached_input_tokens": usage["cached_input_tokens"] if usage else None,
            "output_tokens": usage["output_tokens"] if usage else None,
            "cost_micro_usd": cost,
            "price_version": data["price_version"],
        }
        record_data = {
            **event_data,
            "submitted_status": body.status,
            "usage_fingerprint": fingerprint,
            "counter_keys": counter_keys,
            "event": event_data,
        }
        usage_record = event(
            "usage", request_key, check["tenant_id"], check["principal_id"], record_data
        )
        # The store owns atomic increment-plus-replay protection; only its winner
        # schedules a durable mirror. Replay cannot repair a previously lost write.
        saved, created = await self.counters.record(body.request_id, usage_record)
        if not created:
            _validate_usage_replay(saved, body.status, fingerprint)
        if created:
            self.background.submit(
                USAGE_COLLECTION,
                request_key,
                lambda: self.repository.create(USAGE_COLLECTION, request_key, saved),
            )
            emit(
                "usage_recorded",
                **event_data,
                reason=usage_reason,
                replayed=False,
                uncached_input_tokens=(
                    usage["input_tokens"] - usage["cached_input_tokens"] if usage else None
                ),
                total_tokens=usage["input_tokens"] + usage["output_tokens"] if usage else None,
                cache_hit=usage["cached_input_tokens"] > 0 if usage else None,
            )
        else:
            emit("usage_record_replayed", **saved["data"]["event"], replayed=True)
        rate_metrics.usage(saved["data"]["event"], not created)
        return {"event": saved["data"]["event"], "replayed": not created}

    async def usage(self, tenant_id: str, principal_id: str, admin: bool) -> list[Record]:
        """Return eventually persisted events scoped to a tenant and, unless admin, user.

        Accepted Redis-only events may be delayed or permanently absent here.
        """
        records = await self.repository.list(USAGE_COLLECTION)
        return [
            record["data"]["event"]
            for record in records
            if record.get("tenant_id") == tenant_id
            and (admin or record.get("principal_id") == principal_id)
        ]

    async def budget_status(
        self, tenant_id: str, principal_id: str, admin: bool = False
    ) -> list[Record]:
        """Combine durable visible caps with live Redis current-month spend.

        Admins see all enabled tenant caps; users see their assigned hierarchy.
        This report may differ from durable chargeback history and does not
        reconstruct lost operational counters from Table.
        """
        assignments = [
            Assignment.model_validate(record)
            for record in await self.configuration("assignments")
            if record.get("tenant_id") == tenant_id
            and record.get("enabled") is True
            and (admin or record.get("principal_id") == principal_id)
        ]
        if not admin and not assignments:
            return []
        principals = {item.principal_id for item in assignments}
        teams = {item.team_id for item in assignments}
        departments = {item.department_id for item in assignments}
        month, _ = utc_month()
        budgets = [
            budget
            for record in await self.configuration("budgets")
            if (budget := Budget.model_validate(record)).enabled
            and budget.tenant_id == tenant_id
            and (
                admin
                or (budget.subject_type == "user" and budget.subject_id in principals)
                or (budget.subject_type == "team" and budget.subject_id in teams)
                or (budget.subject_type == "department" and budget.subject_id in departments)
            )
        ]
        keys = {budget.id: _budget_counter_key(budget, month) for budget in budgets}
        totals = await self.counters.totals(month, list(keys.values()))
        result = []
        for budget in budgets:
            actual = totals[keys[budget.id]]
            row = {
                "budget_id": budget.id,
                "name": budget.name,
                "subject_type": budget.subject_type,
                "subject_id": budget.subject_id,
                "model": budget.model,
                "limit_micro_usd": budget.limit_micro_usd,
                "spent_micro_usd": actual,
                "remaining_micro_usd": max(0, budget.limit_micro_usd - actual),
                "month": month,
            }
            result.append(row)
            assignment = next(
                (
                    item
                    for item in assignments
                    if (
                        (budget.subject_type == "user" and item.principal_id == budget.subject_id)
                        or (budget.subject_type == "team" and item.team_id == budget.subject_id)
                        or (
                            budget.subject_type == "department"
                            and item.department_id == budget.subject_id
                        )
                    )
                ),
                None,
            )
            team_id = (
                budget.subject_id
                if budget.subject_type == "team"
                else assignment.team_id
                if assignment
                else None
            )
            department_id = (
                budget.subject_id
                if budget.subject_type == "department"
                else assignment.department_id
                if assignment
                else None
            )
            if budget.subject_type == "team" and assignment is None:
                team = await self.repository.get("organizations", budget.subject_id)
                if team and not team.get("_deleted"):
                    department_id = team.get("department_id")
            emit(
                "budget_status",
                month=month,
                budget_id=budget.id,
                subject_type=budget.subject_type,
                subject_id=(
                    _opaque(tenant_id, budget.subject_id)
                    if budget.subject_type == "user"
                    else budget.subject_id
                ),
                model=budget.model,
                limit_micro_usd=budget.limit_micro_usd,
                spent_micro_usd=actual,
                remaining_micro_usd=row["remaining_micro_usd"],
                user_ref=(
                    _opaque(tenant_id, budget.subject_id) if budget.subject_type == "user" else None
                ),
                team_id=team_id,
                department_id=department_id,
            )
        return result

    async def chargeback(
        self, tenant_id: str, month: str, principal_id: str | None
    ) -> list[Record]:
        """Aggregate durable monthly events by their original chargeback dimensions.

        An optional principal filter narrows the tenant ledger. Unknown usage
        forms separate groups with null money/token totals and a request count;
        it is not silently included as zero-priced actual usage. Results reflect
        only successfully mirrored events, not guaranteed billing completeness.
        """
        records = await self.repository.list(USAGE_COLLECTION)
        groups: dict[tuple[str, ...], Record] = {}
        for record in records:
            data = record["data"]
            if (
                record.get("tenant_id") != tenant_id
                or data.get("month") != month
                or (principal_id and record.get("principal_id") != principal_id)
            ):
                continue
            key = tuple(
                str(data.get(field) or "")
                for field in (
                    "business_unit",
                    "cost_center",
                    "department_id",
                    "team_id",
                    "user_ref",
                    "subscription_id",
                    "model",
                    "month",
                    "status",
                )
            )
            unknown = data.get("status") == "usage_unknown"
            group = groups.setdefault(
                key,
                {
                    "business_unit": key[0],
                    "cost_center": key[1],
                    "department_id": key[2],
                    "team_id": key[3],
                    "user_ref": key[4],
                    "subscription_id": key[5],
                    "model": key[6],
                    "month": key[7],
                    "input_tokens": None if unknown else 0,
                    "cached_input_tokens": None if unknown else 0,
                    "output_tokens": None if unknown else 0,
                    "cost_micro_usd": None if unknown else 0,
                    "unknown_requests": 0,
                },
            )
            if unknown:
                group["unknown_requests"] += 1
            else:
                for field in (
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "cost_micro_usd",
                ):
                    group[field] += data[field]
        return list(groups.values())


def _budget_counter_key(budget: Budget, month: str) -> str:
    """Identify spend by subject/model/month rather than editable budget record ID."""
    return digest(budget.tenant_id, budget.subject_type, budget.subject_id, month, budget.model)


def _usage_fingerprint(body: UsageRecordRequest) -> str:
    """Hash submitted status and canonical provider JSON, ignoring object key order."""
    serialized = (
        json.dumps(body.provider_usage, sort_keys=True, separators=(",", ":"))
        if body.provider_usage is not None
        else ""
    )
    return digest(body.status, serialized)


def _validate_usage_replay(record: Record, status: str, fingerprint: str) -> None:
    """Reject retries differing from the original submission, even if both normalize alike."""
    if record["data"]["submitted_status"] != status:
        raise Conflict("Usage request already finalized differently")
    if record["data"]["usage_fingerprint"] != fingerprint:
        raise Conflict("Usage request replayed with different provider usage")


def _opaque(*parts: str) -> str:
    """Produce stable telemetry references without emitting raw tenant/user identifiers."""
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()
