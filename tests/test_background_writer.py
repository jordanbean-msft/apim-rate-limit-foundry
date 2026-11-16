import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from apim_rate_limit_foundry.background_writer import BackgroundWriter


@pytest.fixture(autouse=True)
def capture_background_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("apim_rate_limit_foundry"), "propagate", True)


async def test_background_queue_drops_excess_work_without_waiting_and_keeps_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = BackgroundWriter(capacity=1)
    release = asyncio.Event()
    started = asyncio.Event()
    completed: list[str] = []

    async def first() -> None:
        started.set()
        await release.wait()
        completed.append("first")

    async def second() -> None:
        completed.append("second")

    dropped = AsyncMock()
    writer.submit("usage_v2", "first", first)
    await started.wait()
    writer.submit("usage_v2", "second", second)
    writer.submit("usage_v2", "dropped", dropped)
    assert completed == []
    assert "background_write_dropped" in caplog.text
    release.set()
    await writer.close()
    assert completed == ["first", "second"]
    dropped.assert_not_awaited()


async def test_failed_background_write_is_logged_and_does_not_stop_later_writes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = BackgroundWriter()
    success = AsyncMock()
    writer.submit("usage_v2", "failed", AsyncMock(side_effect=OSError("offline")))
    writer.submit("usage_v2", "next", success)
    await writer.close()
    success.assert_awaited_once()
    assert "background_write_failed" in caplog.text


async def test_shutdown_abandons_a_blocked_write_within_the_drain_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = BackgroundWriter()
    blocked = asyncio.Event()
    writer.submit("usage_v2", "blocked", blocked.wait)

    async with asyncio.timeout(3):
        await writer.close()

    assert writer.task is not None and writer.task.cancelled()
    assert "background_writes_abandoned" in caplog.text


@pytest.mark.parametrize("error", [RuntimeError("bug"), KeyError("missing"), TypeError("bad")])
async def test_any_job_exception_is_logged_and_the_queue_keeps_draining(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    writer = BackgroundWriter()
    survivor = AsyncMock()
    writer.submit("usage_v2", "broken", AsyncMock(side_effect=error))
    writer.submit("usage_v2", "survivor", survivor)

    await writer.close()

    survivor.assert_awaited_once()
    assert writer.queue.empty()
    assert "background_write_failed" in caplog.text
    assert "background_worker_failed" not in caplog.text
    assert writer.task is not None and writer.task.exception() is None
