"""Explicit configuration for the opt-in, real-inference tracing client."""

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InferenceSettings(BaseSettings):
    """Keep test credentials outside arguments, source, application settings and logs."""

    model_config = SettingsConfigDict(
        env_prefix="INFERENCE_", env_file=None, extra="ignore", hide_input_in_errors=True
    )

    gateway: AnyHttpUrl
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    access_token: SecretStr = Field(min_length=1)
    subscription_key: SecretStr = Field(min_length=1)
    applicationinsights_connection_string: SecretStr = Field(min_length=1)
    timeout_seconds: int = Field(default=120, gt=0, le=600)

    @field_validator("gateway")
    @classmethod
    def https_origin(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        """Credentials may only be sent to a configured HTTPS origin."""
        if (
            value.scheme != "https"
            or value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in ("", "/")
        ):
            raise ValueError("INFERENCE_GATEWAY must be an HTTPS origin")
        return value
