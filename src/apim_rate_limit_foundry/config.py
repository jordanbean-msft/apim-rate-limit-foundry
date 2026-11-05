import os
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    azure_cloud: Literal["commercial", "government"] = "commercial"
    azure_tenant_id: str = ""
    azure_client_id: str | None = None
    table_endpoint: str = ""
    table_name: str = "RateLimiter"
    redis_host: str = ""
    redis_port: int = 6380
    redis_username: str = ""
    redis_token_scope: str | None = None
    local_auth_enabled: bool = False
    local_store_enabled: bool = False
    local_redis_url: str | None = None
    local_table_connection_string: SecretStr | None = None
    port: int = Field(default=8000, ge=1, le=65535)
    website_site_name: str = ""
    website_hostname: str = ""
    website_instance_id: str = ""
    website_auth_enabled: bool = False
    max_input_tokens: int = 131072
    max_output_tokens: int = 32768
    max_pages: int = 2000
    max_text_records: int = 1000

    @model_validator(mode="after")
    def secure_platform(self) -> "Settings":
        has_local_redis = bool(self.local_redis_url)
        has_local_table = bool(
            self.local_table_connection_string
            and self.local_table_connection_string.get_secret_value()
        )
        if self.in_azure and (
            self.local_auth_enabled
            or self.local_store_enabled
            or has_local_redis
            or has_local_table
        ):
            raise ValueError("Local bypass is prohibited in Azure")
        if self.in_azure and not self.website_auth_enabled:
            raise ValueError("Platform Easy Auth must be required")
        if has_local_redis != has_local_table:
            raise ValueError(
                "LOCAL_REDIS_URL and LOCAL_TABLE_CONNECTION_STRING are required together"
            )
        if (has_local_redis or has_local_table) and not self.local_store_enabled:
            raise ValueError("Local persistent endpoints require LOCAL_STORE_ENABLED=true")
        return self

    @property
    def in_azure(self) -> bool:
        return bool(
            self.website_site_name
            or self.website_hostname
            or self.website_instance_id
            or any(key.startswith("WEBSITE_") for key in os.environ)
        )

    @property
    def authority(self) -> str:
        return (
            "https://login.microsoftonline.us"
            if self.azure_cloud == "government"
            else "https://login.microsoftonline.com"
        )

    @property
    def redis_scope(self) -> str:
        if self.redis_token_scope:
            return self.redis_token_scope
        if self.azure_cloud == "government":
            raise ValueError("REDIS_TOKEN_SCOPE must be explicitly verified for Azure Government")
        return "https://redis.azure.com/.default"
