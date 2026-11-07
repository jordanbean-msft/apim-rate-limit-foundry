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
            "anthropic-messages": "/anthropic/v1/messages",
        }
        if self.path != paths[self.api_protocol]:
            raise ValueError("Model path must match its protocol and provider deployment")
        if self.api_protocol == "anthropic-messages":
            if (
                re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.anthropic_version) is None
                or self.api_version
            ):
                raise ValueError("Messages requires anthropic_version, not api_version")
        elif (
            re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.api_version) is None
            or self.anthropic_version
        ):
            raise ValueError("OpenAI models require api_version, not anthropic_version")
        return self
