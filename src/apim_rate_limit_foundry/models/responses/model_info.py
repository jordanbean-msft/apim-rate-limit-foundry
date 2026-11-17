from pydantic import BaseModel

from apim_rate_limit_foundry.models.types import ApiProtocol


class ModelInfo(BaseModel):
    """Registered protocol/alias with its deployment, price version and token bounds."""

    id: str
    model: str
    api_protocol: ApiProtocol
    deployment_name: str
    price_version: str
    max_input_tokens: int
    max_output_tokens: int
