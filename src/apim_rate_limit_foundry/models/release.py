from apim_rate_limit_foundry.models.contract import Contract
from apim_rate_limit_foundry.models.types import Identifier


class Release(Contract):
    reservation_id: Identifier
