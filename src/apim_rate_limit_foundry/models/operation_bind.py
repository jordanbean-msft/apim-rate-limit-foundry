from apim_rate_limit_foundry.models.operation_check import OperationCheck
from apim_rate_limit_foundry.models.types import Identifier


class OperationBind(OperationCheck):
    reservation_id: Identifier
