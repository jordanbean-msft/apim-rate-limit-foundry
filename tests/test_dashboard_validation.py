from unittest.mock import AsyncMock

import pytest

from tests.test_dashboard import dashboard_part, dashboard_service, query_result


async def test_dashboard_ignores_parts_that_are_not_log_tiles() -> None:
    markdown = {
        "position": {"x": 0, "y": 0},
        "metadata": {"type": "Extension/HubsExtension/PartType/MarkdownPart"},
    }
    service = dashboard_service({"0": markdown, "1": dashboard_part(1)})
    service.logs.query_batch.return_value = [query_result([["allowed", 1]])]

    tiles = await service.fetch("24h")

    assert [tile["id"] for tile in tiles] == ["1"]


async def test_dashboard_rejects_unsupported_visualizations_before_querying() -> None:
    service = dashboard_service({"0": dashboard_part(0, chart="Scatter")})

    with pytest.raises(ValueError, match="Unsupported dashboard visualization"):
        await service.fetch("24h")

    service.logs.query_batch.assert_not_called()


async def test_dashboard_rejects_tiles_with_blank_queries() -> None:
    part = dashboard_part(0)
    for item in part["metadata"]["inputs"]:
        if item["name"] == "Query":
            item["value"] = "   "
    service = dashboard_service({"0": part})

    with pytest.raises(ValueError, match="query is empty"):
        await service.fetch("24h")


@pytest.mark.parametrize("count", [0, 41])
async def test_dashboard_requires_between_one_and_forty_log_tiles(count: int) -> None:
    service = dashboard_service({str(i): dashboard_part(i) for i in range(count)})

    with pytest.raises(ValueError, match="between one and forty"):
        await service.fetch("24h")


async def test_closing_the_dashboard_releases_both_transports() -> None:
    service = dashboard_service({"0": dashboard_part(0)})
    service.logs.close = AsyncMock()
    service.arm.close = AsyncMock()

    await service.close()

    service.logs.close.assert_awaited_once()
    service.arm.close.assert_awaited_once()
