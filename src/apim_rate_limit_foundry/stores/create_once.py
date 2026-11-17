"""Shared ``create`` for repositories that implement ``create_if_absent``."""

from abc import ABC, abstractmethod

from apim_rate_limit_foundry.stores.contracts import LEDGER_PARTITION, Record


class CreateOnceRepository(ABC):
    """Derive the create-once ``create`` from each backend's atomic ``create_if_absent``."""

    @abstractmethod
    async def create_if_absent(
        self, collection: str, record_id: str, record: Record, partition: str = LEDGER_PARTITION
    ) -> tuple[Record, bool]:
        """Return (winning record, created) without replacing an existing record."""

    async def create(
        self, collection: str, record_id: str, record: Record, partition: str = LEDGER_PARTITION
    ) -> Record:
        """Return the create-once winner; duplicate IDs never overwrite history."""
        saved, _ = await self.create_if_absent(collection, record_id, record, partition)
        return saved
