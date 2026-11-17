from typing import Literal

from pydantic import BaseModel


class Health(BaseModel):
    """Process health and Azure cloud selection; not a dependency probe."""

    status: Literal["ok"]
    cloud: Literal["commercial", "government"]
