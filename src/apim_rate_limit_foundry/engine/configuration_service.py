"""Validate, persist and delete configuration records with audit and cache invalidation."""

from uuid import uuid4

from pydantic import BaseModel, ValidationError

from apim_rate_limit_foundry.engine.catalog import CONFIG_MODELS, is_legacy
from apim_rate_limit_foundry.engine.configuration_reader import ConfigurationReader
from apim_rate_limit_foundry.engine.configuration_validator import ConfigurationValidator
from apim_rate_limit_foundry.engine.events import event
from apim_rate_limit_foundry.models import Assignment, Budget, Organization
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository


class ConfigurationService:
    """Administer durable configuration; the cache is invalidated after each commit."""

    def __init__(
        self,
        repository: Repository,
        counters: CounterStore,
        reader: ConfigurationReader,
        validator: ConfigurationValidator,
    ) -> None:
        """Bind stores, the reader used for dependency checks and the hierarchy validator."""
        self.repository = repository
        self.counters = counters
        self.reader = reader
        self.validator = validator

    async def save(
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
        await self._check_existing(collection, model, record_id, actor_tenant)
        if "tenant_id" in normalized and normalized["tenant_id"] != actor_tenant:
            raise ValueError("Configuration tenant must match the administrator")
        await self._validate_hierarchy(parsed)
        await self._commit(collection, record_id, normalized, "put", actor_tenant, actor)
        return normalized

    async def delete(self, collection: str, record_id: str, actor_tenant: str, actor: str) -> None:
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
            if is_legacy(collection, current):
                raise Conflict(
                    "Legacy configuration must be archived, not deleted by the new API"
                ) from error
        if current.get("tenant_id", actor_tenant) != actor_tenant:
            raise ValueError("Configuration tenant must match the administrator")
        if collection == "organizations":
            await self._reject_organization_dependents(record_id)
        await self._commit(collection, record_id, None, "delete", actor_tenant, actor)

    async def _check_existing(
        self, collection: str, model: type[BaseModel], record_id: str, actor_tenant: str
    ) -> None:
        """Refuse to replace another tenant's record or an archived legacy schema."""
        existing = await self.repository.get(collection, record_id)
        if not existing or existing.get("_deleted"):
            return
        if existing.get("tenant_id") not in (None, actor_tenant):
            raise Conflict("Configuration record belongs to another tenant")
        try:
            model.model_validate(existing)
        except ValidationError as error:
            if is_legacy(collection, existing):
                raise Conflict(
                    "Legacy configuration must be archived before replacement"
                ) from error

    async def _validate_hierarchy(self, parsed: BaseModel) -> None:
        """Apply the cross-record rule matching the parsed record's type."""
        if isinstance(parsed, Assignment):
            await self.validator.validate_assignment(parsed)
        if isinstance(parsed, Organization):
            await self.validator.validate_organization(parsed)
        if isinstance(parsed, Budget):
            await self.validator.validate_budget(parsed)

    async def _reject_organization_dependents(self, organization_id: str) -> None:
        """Block deleting a department with child teams or a unit with active assignments."""
        organizations = await self.reader.configuration("organizations")
        assignments = await self.reader.configuration("assignments")
        if any(row.get("department_id") == organization_id for row in organizations):
            raise ValueError("Organization units with child teams cannot be deleted")
        if any(
            row.get("enabled") is True
            and organization_id in (row.get("team_id"), row.get("department_id"))
            for row in assignments
        ):
            raise ValueError("Organization units with active assignments cannot be deleted")

    async def _commit(
        self,
        collection: str,
        record_id: str,
        record: Record | None,
        action: str,
        actor_tenant: str,
        actor: str,
    ) -> None:
        """Write the record with its audit event, then invalidate shared configuration."""
        audit = event(
            "configuration",
            uuid4().hex,
            actor_tenant,
            actor,
            {"action": action, "collection": collection, "record_id": record_id},
        )
        await self.repository.mutate(collection, record_id, record, audit)
        await self.counters.invalidate_configuration()
