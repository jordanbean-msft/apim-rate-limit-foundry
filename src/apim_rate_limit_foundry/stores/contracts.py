from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

Record = dict[str, Any]


class Repository(Protocol):
    async def get(self, collection: str, record_id: str) -> Record | None: ...
    async def list(self, collection: str) -> list[Record]: ...
    async def create(self, collection: str, record_id: str, record: Record) -> Record: ...
    async def create_if_absent(
        self, collection: str, record_id: str, record: Record
    ) -> tuple[Record, bool]: ...
    async def mutate(
        self, collection: str, record_id: str, record: Record | None, audit: Record
    ) -> None: ...
    async def close(self) -> None: ...


class CounterStore(Protocol):
    def locked(self) -> AbstractAsyncContextManager[None]: ...
    async def project(self, records: list[Record]) -> None: ...
    async def close(self) -> None: ...


class Conflict(ValueError):  # noqa: N818
    pass


class RecoveryRequired(RuntimeError):  # noqa: N818
    pass
