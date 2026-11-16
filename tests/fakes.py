from collections.abc import Callable, Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from apim_rate_limit_foundry.accounting import usage_partition, utc_month
from apim_rate_limit_foundry.engine import USAGE_COLLECTION, Engine
from apim_rate_limit_foundry.stores.contracts import Record


class FakePost:
    """Stand-in for aiohttp's request manager: awaitable and an async context manager."""

    def __init__(self, response: Any) -> None:
        self.response = response

    def __await__(self) -> Generator[Any, None, Any]:
        async def resolve() -> Any:
            return self.response

        return resolve().__await__()

    async def __aenter__(self) -> Any:
        return self.response

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeHttpSession:
    """Shared aiohttp session fake that records calls and answers through a handler."""

    def __init__(self, handler: Callable[..., Any] | None = None) -> None:
        self.handler = handler or (lambda url, **kwargs: SimpleNamespace(status=204))
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close = AsyncMock()

    def post(self, url: str, **kwargs: Any) -> FakePost:
        self.calls.append((url, kwargs))
        return FakePost(self.handler(url, **kwargs))


async def persisted_usage(engine: Engine, tenant_id: str = "tenant-1") -> list[Record]:
    """Read the current month's mirrored usage history for one tenant."""
    return await engine.repository.list(
        USAGE_COLLECTION, usage_partition(tenant_id, utc_month()[0])
    )
