from typing import Any, Literal

from pydantic import BaseModel

from apim_rate_limit_foundry.models.responses.dashboard_column import DashboardColumn


class DashboardTile(BaseModel):
    """Bounded query result for one deployed dashboard tile; the KQL is never returned.

    Row cells align by index with ``columns``. Errors and truncation are per tile.
    """

    id: str
    title: str
    chart: Literal["Line", "Pie", "Column", "StackedColumn", ""]
    x_axis: str | None
    y_axis: str | None
    split_by: str | None
    columns: list[DashboardColumn]
    rows: list[list[Any]]
    error: str | None
    truncated: bool
