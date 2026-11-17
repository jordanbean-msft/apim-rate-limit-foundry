from pydantic import BaseModel


class DashboardColumn(BaseModel):
    """Name and Log Analytics type of one result column."""

    name: str
    type: str
