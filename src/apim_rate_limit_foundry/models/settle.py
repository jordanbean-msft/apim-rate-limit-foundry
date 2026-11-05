from typing import Literal

from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier
from apim_rate_limit_foundry.models.usage import Usage


class Settle(Contract):
    reservation_id: Identifier
    usage: Usage
    status: Literal["actual", "conservative"]
