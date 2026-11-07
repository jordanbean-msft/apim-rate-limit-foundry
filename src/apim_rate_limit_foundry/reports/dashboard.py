import asyncio
import json
import re
from datetime import timedelta
from typing import Literal

from azure.core import AsyncPipelineClient
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError, HttpResponseError
from azure.core.pipeline.policies import AsyncBearerTokenCredentialPolicy
from azure.monitor.query import LogsBatchQuery, LogsQueryResult
from azure.monitor.query.aio import LogsQueryClient

from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.stores.contracts import Record

DashboardPeriod = Literal["1h", "24h", "7d"]
MAX_ROWS = 1000


class DashboardService:
    """Render the deployed dashboard using only its fixed workspace and queries."""

    def __init__(self, settings: Settings, credential: AsyncTokenCredential) -> None:
        self.settings = settings
        self.arm: AsyncPipelineClient = AsyncPipelineClient(
            base_url=settings.management_endpoint,
            connection_timeout=5,
            read_timeout=10,
            policies=[
                AsyncBearerTokenCredentialPolicy(
                    credential, f"{settings.management_endpoint}/.default"
                )
            ],
        )
        self.logs = LogsQueryClient(
            credential,
            endpoint=settings.logs_endpoint,
            connection_timeout=5,
            read_timeout=25,
            retry_total=0,
        )

    def _tiles(self, document: Record) -> list[Record]:
        tiles = []
        lenses = document["properties"]["lenses"]
        for lens in lenses.values() if isinstance(lenses, dict) else lenses:
            lens_parts = lens["parts"]
            indexed_parts = (
                lens_parts.items() if isinstance(lens_parts, dict) else enumerate(lens_parts)
            )
            parts = sorted(
                indexed_parts,
                key=lambda part: (part[1]["position"]["y"], part[1]["position"]["x"], part[0]),
            )
            for key, part in parts:
                metadata = part["metadata"]
                if metadata["type"] != (
                    "Extension/Microsoft_OperationsManagementSuite_Workspace/PartType/LogsDashboardPart"
                ):
                    continue
                inputs = {item["name"]: item.get("value") for item in metadata["inputs"]}
                scopes = inputs.get("Scope", {}).get("resourceIds", [])
                if [scope.lower() for scope in scopes] != [
                    self.settings.log_analytics_workspace_resource_id.lower()
                ]:
                    raise ValueError("Dashboard tile has an unexpected workspace")
                chart = inputs.get("SpecificChart", "")
                if chart not in ("", "Line", "Pie", "Column", "StackedColumn"):
                    raise ValueError("Unsupported dashboard visualization")
                dimensions = inputs.get("Dimensions", {})
                x_axis = dimensions.get("xAxis") or {}
                y_axis: Record = next(iter(dimensions.get("yAxis", [])), {}) or {}
                split_by: Record = next(iter(dimensions.get("splitBy", [])), {}) or {}
                query = inputs["Query"]
                if not isinstance(query, str) or not query.strip():
                    raise ValueError("Dashboard query is empty")
                # The native render hint must remain last; this API returns data, not a render frame.
                query = re.split(r"(?m)^\s*\|\s*render\b", query, maxsplit=1)[0].rstrip()
                query += (
                    f"\n| top {MAX_ROWS + 1} by {x_axis['name']} desc"
                    if x_axis.get("type") == "datetime"
                    else f"\n| take {MAX_ROWS + 1}"
                )
                tiles.append(
                    {
                        "id": inputs.get("PartId") or str(key),
                        "title": inputs.get("PartTitle", "Dashboard"),
                        "chart": chart,
                        "x_axis": x_axis.get("name"),
                        "y_axis": y_axis.get("name"),
                        "split_by": split_by.get("name"),
                        "query": query,
                    }
                )
        if not tiles or len(tiles) > 40:
            raise ValueError("Dashboard must have between one and forty log tiles")
        return tiles

    async def _batch(self, tiles: list[Record], period: DashboardPeriod) -> list[Record]:
        duration = {"1h": timedelta(hours=1), "24h": timedelta(days=1), "7d": timedelta(days=7)}
        requests = [
            LogsBatchQuery(
                self.settings.log_analytics_workspace_id,
                tile["query"],
                timespan=duration[period],
                server_timeout=20,
            )
            for tile in tiles
        ]
        try:
            results = await self.logs.query_batch(requests)
        except AzureError:
            results = []
        output = []
        for index, tile in enumerate(tiles):
            item = {key: value for key, value in tile.items() if key != "query"}
            item.update(columns=[], rows=[], error=None, truncated=False)
            result = results[index] if index < len(results) else None
            if not isinstance(result, LogsQueryResult):
                item["error"] = "Telemetry is unavailable or incomplete. Refresh to retry."
            else:
                table = next(
                    (table for table in result.tables if table.name == "PrimaryResult"), None
                )
                if table is None:
                    item["error"] = "Telemetry returned no result table. Refresh to retry."
                else:
                    item["columns"] = [
                        {"name": name, "type": kind}
                        for name, kind in zip(table.columns, table.columns_types, strict=True)
                    ]
                    item["rows"] = [list(row) for row in table.rows[:MAX_ROWS]]
                    item["truncated"] = len(table.rows) > MAX_ROWS
            output.append(item)
        return output

    async def fetch(self, period: DashboardPeriod) -> list[Record]:
        async with asyncio.timeout(35):
            request = self.arm.get(
                f"{self.settings.management_endpoint}{self.settings.azure_dashboard_id}",
                params={"api-version": "2020-09-01-preview"},
            )
            response = await self.arm.send_request(request)
            if response.status_code != 200:
                raise HttpResponseError(response=response)
            tiles = self._tiles(json.loads(response.text()))
            batches = await asyncio.gather(
                *(
                    self._batch(tiles[index : index + 20], period)
                    for index in range(0, len(tiles), 20)
                )
            )
            return [tile for batch in batches for tile in batch]

    async def close(self) -> None:
        await self.logs.close()
        await self.arm.close()
