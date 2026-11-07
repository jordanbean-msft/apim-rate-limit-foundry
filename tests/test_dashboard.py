import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from azure.core.exceptions import AzureError
from azure.monitor.query import LogsBatchQuery, LogsQueryResult, LogsTable
from pydantic import ValidationError

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import Engine
from apim_rate_limit_foundry.reports.dashboard import DashboardService

UUID = "00000000-0000-0000-0000-000000000001"
BASE = f"/subscriptions/{UUID}/resourceGroups/demo/providers"
WORKSPACE = f"{BASE}/Microsoft.OperationalInsights/workspaces/logs"
DASHBOARD = f"{BASE}/Microsoft.Portal/dashboards/dashboard"
ADMIN = {
    "X-Local-Tenant-Id": "tenant-1",
    "X-Local-Principal-Id": "admin",
    "X-Local-Roles": "RateLimit.Admin",
}


def dashboard_part(index: int, *, scope: str = WORKSPACE, chart: str = "Line") -> dict:
    return {
        "position": {"x": index % 2, "y": index // 2},
        "metadata": {
            "type": "Extension/Microsoft_OperationsManagementSuite_Workspace/PartType/LogsDashboardPart",
            "inputs": [
                {"name": "Scope", "value": {"resourceIds": [scope]}},
                {"name": "PartId", "value": str(index)},
                {"name": "PartTitle", "value": f"Native chart {index}"},
                {"name": "SpecificChart", "value": chart},
                {
                    "name": "Query",
                    "value": "AppTraces | summarize count() by bin(TimeGenerated, 1m)\n| render timechart",
                },
                {
                    "name": "Dimensions",
                    "value": {
                        "xAxis": {"name": "TimeGenerated", "type": "datetime"},
                        "yAxis": [{"name": "Count", "type": "long"}],
                    },
                },
            ],
        },
    }


def dashboard_service(parts: dict) -> DashboardService:
    settings = Settings(
        _env_file=None,
        azure_dashboard_id=DASHBOARD,
        log_analytics_workspace_id=UUID,
        log_analytics_workspace_resource_id=WORKSPACE,
    )
    service = DashboardService(settings, AsyncMock())
    service.arm = MagicMock()
    service.arm.send_request = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            text=lambda: json.dumps({"properties": {"lenses": {"0": {"parts": parts}}}}),
        )
    )
    service.logs = MagicMock()
    service.logs.query_batch = AsyncMock()
    return service


def query_result(rows: list) -> LogsQueryResult:
    return LogsQueryResult(
        tables=[
            LogsTable(
                name="PrimaryResult",
                columns=["Category", "Count"],
                columns_types=["string", "long"],
                rows=rows,
            )
        ]
    )


async def test_native_tiles_queries_and_period_are_reused_without_browser_query_access() -> None:
    service = dashboard_service({"1": dashboard_part(1), "0": dashboard_part(0, chart="")})
    service.logs.query_batch.return_value = [query_result([["allowed", 8]]), query_result([])]
    with patch(
        "apim_rate_limit_foundry.reports.dashboard.LogsBatchQuery", wraps=LogsBatchQuery
    ) as make_query:
        tiles = await service.fetch("7d")
    assert all(call.kwargs["timespan"] == timedelta(days=7) for call in make_query.call_args_list)
    assert [tile["title"] for tile in tiles] == ["Native chart 0", "Native chart 1"]
    assert tiles[0]["rows"] == [["allowed", 8]] and tiles[1]["rows"] == []
    assert tiles[0]["columns"] == [
        {"name": "Category", "type": "string"},
        {"name": "Count", "type": "long"},
    ]
    assert all("query" not in tile and "workspace" not in tile for tile in tiles)
    queries = service.logs.query_batch.call_args.args[0]
    assert all(query.workspace == UUID for query in queries)
    assert "AppTraces | summarize" in queries[0].body["query"]
    assert "render" not in queries[0].body["query"]
    assert queries[0].body["query"].endswith("| top 1001 by TimeGenerated desc")


async def test_unexpected_workspace_is_rejected_before_any_query() -> None:
    service = dashboard_service({"0": dashboard_part(0, scope=WORKSPACE + "-other")})
    with pytest.raises(ValueError, match="unexpected workspace"):
        await service.fetch("24h")
    service.logs.query_batch.assert_not_called()


async def test_arm_array_lenses_and_parts_match_the_native_rest_representation() -> None:
    service = dashboard_service({})
    service.arm.send_request.return_value.text = lambda: json.dumps(
        {"properties": {"lenses": [{"parts": [dashboard_part(0)]}]}}
    )
    service.logs.query_batch.return_value = [query_result([["allowed", 1]])]
    tiles = await service.fetch("24h")
    assert len(tiles) == 1 and tiles[0]["id"] == "0"


async def test_batches_partial_failures_and_result_bounds() -> None:
    service = dashboard_service({str(index): dashboard_part(index) for index in range(22)})
    result = query_result([["allowed", index] for index in range(1001)])
    service.logs.query_batch.side_effect = [
        [result] * 19 + [None],
        AzureError("Sensitive backend details must not reach the browser"),
    ]
    tiles = await service.fetch("1h")
    assert [len(call.args[0]) for call in service.logs.query_batch.call_args_list] == [20, 2]
    assert len(tiles) == 22 and len(tiles[0]["rows"]) == 1000
    assert tiles[0]["truncated"] is True
    assert all(tile["error"] and tile["rows"] == [] for tile in tiles[19:])
    assert "Sensitive" not in json.dumps(tiles)


async def test_dashboard_api_requires_admin_and_rejects_client_query_inputs(
    settings: Settings, engine: Engine
) -> None:
    service = MagicMock(spec=DashboardService)
    service.fetch = AsyncMock(return_value=[{"id": "native-tile", "rows": []}])
    app = create_app(settings, engine, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for role, expected in (("", 401), ("RateLimit.Reader", 403), ("RateLimit.Gateway", 403)):
            headers = {**ADMIN, "X-Local-Roles": role} if role else {}
            assert (await client.get("/api/dashboard", headers=headers)).status_code == expected
        service.fetch.assert_not_called()
        response = await client.get("/api/dashboard?period=1h", headers=ADMIN)
        assert response.status_code == 200 and response.json()[0]["id"] == "native-tile"
        service.fetch.assert_awaited_once_with("1h")
        for query in ("period=30d", "period=1h&period=7d", "query=AppTraces", "workspace=other"):
            assert (await client.get(f"/api/dashboard?{query}", headers=ADMIN)).status_code in (
                400,
                422,
            )
        service.fetch.side_effect = AzureError("private diagnostic detail")
        response = await client.get("/api/dashboard", headers=ADMIN)
        assert response.status_code == 503 and "private" not in response.text


@pytest.mark.parametrize("cloud", ["commercial", "government"])
def test_dashboard_configuration_is_complete_and_cloud_bound(cloud: str) -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(_env_file=None, azure_dashboard_id=DASHBOARD)
    with pytest.raises(ValidationError, match="fixed Azure resource"):
        Settings(
            _env_file=None,
            azure_dashboard_id="https://attacker.example",
            log_analytics_workspace_id=UUID,
            log_analytics_workspace_resource_id=WORKSPACE,
        )
    with pytest.raises(ValidationError, match="must be a UUID"):
        Settings(
            _env_file=None,
            azure_dashboard_id=DASHBOARD,
            log_analytics_workspace_id="-" * 36,
            log_analytics_workspace_resource_id=WORKSPACE,
        )
    settings = Settings(_env_file=None, azure_cloud=cloud)
    if cloud == "government":
        assert settings.logs_endpoint == "https://api.loganalytics.us"
        assert settings.management_endpoint == "https://management.usgovcloudapi.net"
    else:
        assert settings.logs_endpoint == "https://api.loganalytics.io"
        assert settings.management_endpoint == "https://management.azure.com"
