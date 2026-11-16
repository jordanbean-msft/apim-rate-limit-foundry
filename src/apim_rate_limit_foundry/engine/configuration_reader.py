"""Read durable configuration and the shared cached snapshot used by warm admission."""

import asyncio
import logging

from pydantic import ValidationError

from apim_rate_limit_foundry.engine.catalog import CONFIG_MODELS, is_legacy
from apim_rate_limit_foundry.stores.contracts import (
    CounterStore,
    InvalidConfiguration,
    Record,
    Repository,
)
from apim_rate_limit_foundry.telemetry import emit


class ConfigurationReader:
    """List validated configuration and coalesce shared-snapshot loads for this process."""

    def __init__(self, repository: Repository, counters: CounterStore) -> None:
        """Bind stores and allocate the per-process load lock."""
        self.repository = repository
        self.counters = counters
        self._lock = asyncio.Lock()

    async def snapshot(self) -> Record:
        """Read shared configuration, loading all durable collections only on a miss.

        The lock coalesces misses within this reader, not across hosts. TTL expiry
        and admin invalidation bound normal staleness; this is not a distributed
        configuration transaction or lock against concurrent administrative writes.
        """
        snapshot = await self.counters.configuration()
        if snapshot is not None:
            return snapshot
        async with self._lock:
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
        """List durable records, hiding tombstones and legacy application-scoped schemas.

        Known configuration collections are validated and normalized. A record
        lacking its collection's current-schema marker field is archived legacy data
        and skipped. A current-schema record that fails validation is logged and
        raises ``InvalidConfiguration``: silently dropping it could remove a budget
        cap. Tenant scoping is the responsibility of the calling operation.
        """
        records = []
        for record in await self.repository.list(collection):
            if record.get("_deleted"):
                continue
            normalized = self._normalize(collection, record)
            if normalized is not None:
                records.append(normalized)
        return records

    @staticmethod
    def _normalize(collection: str, record: Record) -> Record | None:
        """Validate a known collection's record; None marks archived legacy data."""
        model = CONFIG_MODELS.get(collection)
        if model is None:
            return record
        try:
            return model.model_validate(record).model_dump(mode="json", exclude_none=True)
        except ValidationError as error:
            if is_legacy(collection, record):
                # Legacy application-scoped records remain archived, not reinterpreted.
                return None
            emit(
                "configuration_record_invalid",
                level=logging.WARNING,
                collection=collection,
                record_id=record.get("id"),
            )
            raise InvalidConfiguration(
                f"Invalid {collection} configuration record: {record.get('id')}"
            ) from error
