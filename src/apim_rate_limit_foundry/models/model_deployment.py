import re

from pydantic import Field, model_validator

from apim_rate_limit_foundry.models.stream_backend import StreamBackend
from apim_rate_limit_foundry.models.types import ApiProtocol


class ModelDeployment(StreamBackend):
    api_protocol: ApiProtocol
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    price_version: str = Field(pattern=r"^[A-Za-z0-9._-]{1,200}$")
    max_input_tokens: int = Field(strict=True, ge=1)
    max_output_tokens: int = Field(strict=True, ge=1)

    @model_validator(mode="after")
    def protocol_endpoint(self) -> "ModelDeployment":
        paths = {
            "openai-chat": f"/openai/deployments/{self.model}/chat/completions",
            "openai-responses": "/openai/v1/responses",
        }
        if self.path != paths[self.api_protocol]:
            raise ValueError("Model path must match its protocol and provider deployment")
        if self.api_version and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.api_version) is None:
            raise ValueError("OpenAI api_version must be a safe identifier")
        return self
