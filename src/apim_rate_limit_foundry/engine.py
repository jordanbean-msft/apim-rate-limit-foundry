import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from azure.core.exceptions import AzureError
from pydantic import ValidationError
from redis.exceptions import RedisError

from apim_rate_limit_foundry.accounting import (
    cost_micro_usd,
    digest,
    normalize_openai_usage,
    utc_month,
)
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models import Assignment, Budget, BudgetCheck, Organization, Price
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import emit

CONFIG_MODELS: dict[str, type[Organization] | type[Assignment] | type[Budget] | type[Price]] = {
    "organizations": Organization,
    "assignments": Assignment,
    "budgets": Budget,
    "prices": Price,
}
USAGE_COLLECTION = "usage_v2"


def event(kind: str, record_id: str, tenant: str, principal: str, data: Record) -> Record:
    return {
        "id": record_id,
        "kind": kind,
        "tenant_id": tenant,
        "principal_id": principal,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }


class Engine:
    def __init__(self, repository: Repository, counters: CounterStore, settings: Settings) -> None:
        self.repository = repository
        self.counters = counters
        self.settings = settings

    async def configuration(self, collection: str) -> list[Record]:
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
        return normalized

    async def delete_configuration(
        self, collection: str, record_id: str, actor_tenant: str, actor: str
    ) -> None:
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

    async def _validate_assignment(self, assignment: Assignment) -> None:
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
        request_key = digest(check.tenant_id, check.request_id)
        fingerprint = digest(
            check.tenant_id,
            check.principal_id,
            check.subscription_id,
            check.model,
            check.api_protocol,
            str(check.streaming),
        )
        async with self.counters.locked():
            saved = await self.repository.get("requests", request_key)
            if saved is not None:
                data = saved["data"]
                if data["fingerprint"] != fingerprint:
                    raise Conflict("Request ID reused with different request")
                if await self.repository.get(USAGE_COLLECTION, request_key) is not None:
                    raise Conflict("Completed request IDs cannot be dispatched again")
                result = data["decision"]
                return {**result, "request_id": check.request_id}

            assignment = await self._assignment(check.tenant_id, check.principal_id)
            if assignment is None:
                raise ValueError("Unknown or unassigned user")
            organization = await self._organization_context(assignment)
            deployment = (
                self.settings.registered_model(check.api_protocol, check.model)
                if self.settings.model_registry
                else None
            )
            price = await self._get_price(check)
            month, reset = utc_month()
            usage_records = await self.repository.list(USAGE_COLLECTION)
            await self.counters.project(usage_records)
            matching = self._matching_budgets(
                check, assignment, await self.configuration("budgets")
            )
            spend_by_budget = self._spend_by_budget(matching, usage_records, month, check.model)
            denied = [
                budget.id
                for budget in matching
                if spend_by_budget.get(budget.id, 0) >= budget.limit_micro_usd
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
            await self.repository.create(
                "requests",
                request_key,
                event("request", request_key, check.tenant_id, check.principal_id, data),
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
            )
            return decision

    async def _assignment(self, tenant_id: str, principal_id: str) -> Assignment | None:
        matches = [
            Assignment.model_validate(record)
            for record in await self.configuration("assignments")
            if record.get("tenant_id") == tenant_id
            and record.get("principal_id") == principal_id
            and record.get("enabled") is True
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    async def _organization_context(self, assignment: Assignment) -> Record:
        organizations = {
            record["id"]: Organization.model_validate(record)
            for record in await self.configuration("organizations")
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

    async def _get_price(self, check: BudgetCheck) -> Price:
        version: str | None = None
        if self.settings.model_registry:
            version = self.settings.registered_model(check.api_protocol, check.model).price_version
        matches = [
            Price.model_validate(record)
            for record in await self.configuration("prices")
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

    @staticmethod
    def _spend_by_budget(
        budgets: list[Budget], usage_records: list[Record], month: str, model: str
    ) -> dict[str, int]:
        spend = {budget.id: 0 for budget in budgets}
        for record in usage_records:
            data = record.get("data", {})
            amount = data.get("cost_micro_usd")
            if (
                record.get("kind") != "usage"
                or data.get("month") != month
                or data.get("status") != "actual"
                or not isinstance(amount, int)
            ):
                continue
            for budget in budgets:
                if (
                    budget.tenant_id == record.get("tenant_id")
                    and (budget.model == "*" or budget.model == model)
                    and (budget.model == "*" or data.get("model") == budget.model)
                    and (
                        (
                            budget.subject_type == "user"
                            and budget.subject_id == record.get("principal_id")
                        )
                        or (
                            budget.subject_type == "team"
                            and budget.subject_id == data.get("team_id")
                        )
                        or (
                            budget.subject_type == "department"
                            and budget.subject_id == data.get("department_id")
                        )
                    )
                ):
                    spend[budget.id] += amount
        return spend

    async def record_usage(self, body: UsageRecordRequest) -> Record:
        candidates = await self.repository.list("requests")
        matches = [
            record["id"]
            for record in candidates
            if record.get("data", {}).get("check", {}).get("request_id") == body.request_id
        ]
        if len(matches) != 1:
            raise Conflict("Budget check not found")
        request_key = matches[0]
        request = await self.repository.get("requests", request_key)
        if request is None:
            raise Conflict("Budget check not found")
        fingerprint = _usage_fingerprint(body)
        prior = await self.repository.get(USAGE_COLLECTION, request_key)
        if prior is not None:
            _validate_usage_replay(prior, body.status, fingerprint)
            await self._refresh_projection()
            return {"event": prior["data"]["event"], "replayed": True}

        data = request["data"]
        check = data["check"]
        if not data["decision"]["allowed"]:
            raise Conflict("Denied requests cannot be charged")
        usage = None
        cost = None
        status = body.status
        if body.status == "actual":
            if body.provider_usage is None:
                status = "usage_unknown"
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
                    usage = None
                    cost = None
        elif body.provider_usage is not None:
            raise ValueError("Unknown usage must not include fabricated provider counters")

        month = data["month"]
        snapshot = data["organization"]
        projection_keys = [
            digest(check["tenant_id"], kind, subject_id, month)
            for kind, subject_id in (
                ("user", check["principal_id"]),
                ("team", snapshot["team_id"]),
                ("department", snapshot["department_id"]),
            )
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
            "projection_keys": projection_keys,
            "event": event_data,
        }
        durable = event(
            "usage", request_key, check["tenant_id"], check["principal_id"], record_data
        )
        saved, created = await self.repository.create_if_absent(
            USAGE_COLLECTION, request_key, durable
        )
        if not created:
            _validate_usage_replay(saved, body.status, fingerprint)
        await self._refresh_projection()
        if created:
            emit("usage_recorded", **event_data)
        return {"event": saved["data"]["event"], "replayed": not created}

    async def _refresh_projection(self) -> None:
        try:
            async with self.counters.locked():
                await self.counters.project(await self.repository.list(USAGE_COLLECTION))
        except (OSError, TimeoutError, AzureError, RedisError):
            emit(
                "usage_projection_rebuild_deferred", level=logging.WARNING, error_type="projection"
            )

    async def rebuild_counters(self) -> int:
        async with self.counters.locked():
            records = await self.repository.list(USAGE_COLLECTION)
            await self.counters.project(records)
            return len(records)

    async def usage(self, tenant_id: str, principal_id: str, admin: bool) -> list[Record]:
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
        records = await self.repository.list(USAGE_COLLECTION)
        result = []
        for budget in budgets:
            actual = 0
            for record in records:
                data = record["data"]
                if (
                    data.get("month") == month
                    and data.get("status") == "actual"
                    and isinstance(data.get("cost_micro_usd"), int)
                    and record.get("tenant_id") == tenant_id
                    and (
                        (
                            budget.subject_type == "user"
                            and record.get("principal_id") == budget.subject_id
                        )
                        or (
                            budget.subject_type == "team"
                            and data.get("team_id") == budget.subject_id
                        )
                        or (
                            budget.subject_type == "department"
                            and data.get("department_id") == budget.subject_id
                        )
                    )
                    and (budget.model == "*" or data.get("model") == budget.model)
                ):
                    actual += data["cost_micro_usd"]
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


def _usage_fingerprint(body: UsageRecordRequest) -> str:
    serialized = (
        json.dumps(body.provider_usage, sort_keys=True, separators=(",", ":"))
        if body.provider_usage is not None
        else ""
    )
    return digest(body.status, serialized)


def _validate_usage_replay(record: Record, status: str, fingerprint: str) -> None:
    if record["data"]["submitted_status"] != status:
        raise Conflict("Usage request already finalized differently")
    if record["data"]["usage_fingerprint"] != fingerprint:
        raise Conflict("Usage request replayed with different provider usage")


def _opaque(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()
