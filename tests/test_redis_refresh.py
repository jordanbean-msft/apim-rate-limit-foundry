import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.redis import RedisCounters


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> list[Mock]:
    created: list[Mock] = []

    def build(**kwargs: object) -> Mock:
        client = Mock(password=kwargs["password"], aclose=AsyncMock(), get=AsyncMock())
        created.append(client)
        return client

    monkeypatch.setattr("apim_rate_limit_foundry.stores.redis.Redis", build)
    return created


def counters(settings: Settings, credential: AsyncMock) -> RedisCounters:
    return RedisCounters(settings, credential)


def credential_issuing(*tokens: str) -> AsyncMock:
    credential = AsyncMock()
    credential.get_token.side_effect = [
        SimpleNamespace(token=token, expires_on=9_999_999_999) for token in tokens
    ]
    return credential


async def test_refresh_installs_the_new_client_before_closing_the_old_one(
    settings: Settings, clients: list[Mock]
) -> None:
    store = counters(settings, credential_issuing("first", "second"))
    first = await store.connection()
    store.expires = 0

    second = await store.connection()

    assert (first.password, second.password) == ("first", "second")
    assert store.client is second
    first.aclose.assert_not_awaited()


async def test_replaced_client_is_closed_at_the_following_refresh_and_on_close(
    settings: Settings, clients: list[Mock]
) -> None:
    store = counters(settings, credential_issuing("one", "two", "three"))
    first = await store.connection()
    store.expires = 0
    second = await store.connection()
    store.expires = 0
    third = await store.connection()

    first.aclose.assert_awaited_once()
    second.aclose.assert_not_awaited()
    await store.close()
    second.aclose.assert_awaited_once()
    third.aclose.assert_awaited_once()
    assert first.aclose.await_count == 1


async def test_commands_keep_using_the_valid_client_while_one_caller_refreshes(
    settings: Settings, clients: list[Mock]
) -> None:
    release = asyncio.Event()
    token_requested = asyncio.Event()
    credential = credential_issuing("first")
    store = counters(settings, credential)
    first = await store.connection()
    first.get.return_value = None

    async def slow_token(*scopes: str) -> SimpleNamespace:
        token_requested.set()
        await release.wait()
        return SimpleNamespace(token="second", expires_on=9_999_999_999)

    credential.get_token.side_effect = slow_token
    store.expires = time.time() + 60
    refresh = asyncio.create_task(store.connection())
    await token_requested.wait()

    async with asyncio.timeout(1):
        assert await store.request("served-by-the-valid-client") is None
    first.get.assert_awaited()
    release.set()

    assert (await refresh).password == "second"
    assert credential.get_token.await_count == 2


async def test_an_expired_client_waits_for_the_refresh(
    settings: Settings, clients: list[Mock]
) -> None:
    credential = credential_issuing("first", "second")
    store = counters(settings, credential)
    await store.connection()
    store.expires = 0

    waiting = await asyncio.gather(store.connection(), store.connection())

    assert {client.password for client in waiting} == {"second"}
    assert credential.get_token.await_count == 2


async def test_concurrent_callers_share_one_refresh(
    settings: Settings, clients: list[Mock]
) -> None:
    credential = credential_issuing("only")
    store = counters(settings, credential)

    results = await asyncio.gather(*(store.connection() for _ in range(10)))

    assert len({id(client) for client in results}) == 1
    assert credential.get_token.await_count == 1
    assert len(clients) == 1


async def test_failed_token_refresh_keeps_the_current_client_open(
    settings: Settings, clients: list[Mock]
) -> None:
    credential = credential_issuing("first")
    store = counters(settings, credential)
    first = await store.connection()
    store.expires = 0
    credential.get_token.side_effect = OSError("identity offline")

    with pytest.raises(OSError):
        await store.connection()

    assert store.client is first
    first.aclose.assert_not_awaited()


async def test_cloud_redis_requires_a_credential(settings: Settings) -> None:
    with pytest.raises(ValueError, match="credential"):
        await RedisCounters(settings, None).connection()


async def test_callers_queued_behind_a_refresh_reuse_its_new_client(
    settings: Settings, clients: list[Mock]
) -> None:
    credential = credential_issuing("first")
    store = counters(settings, credential)
    await store.connection()
    store.expires = 0

    async def yielding_token(*scopes: str) -> SimpleNamespace:
        await asyncio.sleep(0)
        return SimpleNamespace(token="second", expires_on=9_999_999_999)

    credential.get_token.side_effect = yielding_token

    first, second = await asyncio.gather(store.connection(), store.connection())

    assert first is second and first.password == "second"
    assert credential.get_token.await_count == 2
