"""Central environment settings and fail-closed deployment invariants."""

import os
import re
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apim_rate_limit_foundry.models.model_deployment import ModelDeployment
from apim_rate_limit_foundry.models.types import SAFE_NAME, ApiProtocol


class Settings(BaseSettings):
    """Load case-insensitive environment/.env values and reject unsafe combinations.

    Costs use integer micro-USD elsewhere; cache lifetimes below are seconds.
    Model registry keys bind a caller-visible protocol/alias to a trusted backend.
    SecretStr settings must not be serialized into telemetry or API responses.
    """

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
    # Configuration TTL bounds stale reads after invalidation races; it is not spend durability.
    configuration_cache_seconds: int = Field(default=60, ge=1, le=3600)
    # Expiry also ends operational replay protection and admission-context availability.
    request_cache_seconds: int = Field(default=86400, ge=300, le=604800)
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
    applicationinsights_connection_string: SecretStr | None = None
    telemetry_enabled: bool = True
    otel_service_name: str = "rate-limiter"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0, le=1)
    # Process CPU/memory/request-rate counters carry no request data; Live Metrics is opt-in.
    otel_performance_counters_enabled: bool = True
    otel_live_metrics_enabled: bool = False
    model_registry: dict[str, ModelDeployment] = Field(default_factory=dict)
    event_hub_fqdn: str = ""
    event_hub_name: str = ""
    gateway_client_id: str = ""
    stream_max_event_bytes: int = Field(default=65536, ge=8192, le=1048576)
    stream_max_body_bytes: int = Field(default=131072, ge=1024, le=1048576)
    stream_timeout_seconds: int = Field(default=180, ge=10, le=210)
    dashboard_query_timeout_seconds: int = Field(default=20, ge=5, le=120)
    azure_dashboard_id: str = ""
    log_analytics_workspace_id: str = ""
    log_analytics_workspace_resource_id: str = ""

    @model_validator(mode="after")
    def secure_platform(self) -> "Settings":
        """Reject cloud bypasses, partial local stores and inconsistent resource/model IDs."""
        self._validate_platform()
        self._validate_dashboard()
        for key, deployment in self.model_registry.items():
            self._validate_deployment(key, deployment)
        return self

    def _validate_platform(self) -> None:
        """Require platform auth and a registry in Azure, and paired local/export endpoints."""
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
        if self.in_azure and not self.model_registry:
            raise ValueError("MODEL_REGISTRY is required in Azure")
        if bool(self.event_hub_fqdn) != bool(self.event_hub_name):
            raise ValueError("EVENT_HUB_FQDN and EVENT_HUB_NAME must be configured together")
        if has_local_redis != has_local_table:
            raise ValueError(
                "LOCAL_REDIS_URL and LOCAL_TABLE_CONNECTION_STRING are required together"
            )
        if (has_local_redis or has_local_table) and not self.local_store_enabled:
            raise ValueError("Local persistent endpoints require LOCAL_STORE_ENABLED=true")

    def _validate_dashboard(self) -> None:
        """Fix both the ARM dashboard and query workspace; callers cannot supply targets."""
        dashboard_config = (
            self.azure_dashboard_id,
            self.log_analytics_workspace_id,
            self.log_analytics_workspace_resource_id,
        )
        if not any(dashboard_config):
            return
        if not all(dashboard_config):
            raise ValueError("Dashboard and both workspace IDs must be configured together")
        uuid_pattern = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
        for resource_id, resource_type in (
            (self.azure_dashboard_id, "Microsoft.Portal/dashboards"),
            (
                self.log_analytics_workspace_resource_id,
                "Microsoft.OperationalInsights/workspaces",
            ),
        ):
            if not re.fullmatch(
                rf"/subscriptions/{uuid_pattern}/resourceGroups/[^/?#]+"
                rf"/providers/{re.escape(resource_type)}/[^/?#]+",
                resource_id,
                re.IGNORECASE,
            ):
                raise ValueError("Dashboard settings require fixed Azure resource IDs")
        if not re.fullmatch(uuid_pattern, self.log_analytics_workspace_id, re.IGNORECASE):
            raise ValueError("The workspace customer ID must be a UUID")

    def _validate_deployment(self, key: str, deployment: ModelDeployment) -> None:
        """Check one registry entry's key shape, limits and sovereign-cloud endpoints."""
        # Keep protocol aliases separate even when they target the same model deployment.
        protocol, separator, alias = key.partition(":")
        if (
            not separator
            or protocol != deployment.api_protocol
            or re.fullmatch(SAFE_NAME, alias) is None
        ):
            raise ValueError("Model registry keys must be protocol:alias with a safe alias")
        if (
            deployment.max_input_tokens > self.max_input_tokens
            or deployment.max_output_tokens > self.max_output_tokens
        ):
            raise ValueError("Registered model limits must not exceed the Function limits")
        if self.azure_cloud == "government" and (
            not deployment.endpoint.host
            or not deployment.endpoint.host.endswith(
                (".openai.azure.us", ".cognitiveservices.azure.us", ".services.ai.azure.us")
            )
            or deployment.audience.host != "cognitiveservices.azure.us"
        ):
            raise ValueError(
                "Government models require sovereign endpoints and Cognitive Services audience"
            )

    def registered_model(self, protocol: ApiProtocol, alias: str) -> ModelDeployment:
        """Resolve only configured protocol/alias pairs; never accept arbitrary endpoints."""
        deployment = self.model_registry.get(f"{protocol}:{alias}")
        if deployment is None:
            raise ValueError("Unknown model alias or incompatible API protocol")
        return deployment

    @property
    def in_azure(self) -> bool:
        """Detect platform markers without mistaking Core Tools loopback for Azure.

        Site/instance markers take precedence so a loopback-looking hostname
        cannot enable local authentication or stores on a real cloud host.
        """
        markers = {key for key in os.environ if key.startswith("WEBSITE_")}
        if self.website_site_name or self.website_instance_id or markers - {"WEBSITE_HOSTNAME"}:
            return True
        if not self.website_hostname:
            return "WEBSITE_HOSTNAME" in markers
        # Core Tools supplies only this loopback marker; real site/instance markers
        # above must still prohibit local bypass, regardless of environment labels.
        local_host = re.fullmatch(
            r"(?:localhost|127\.0\.0\.1):([0-9]{1,5})", self.website_hostname, re.IGNORECASE
        )
        return local_host is None or not 1 <= int(local_host.group(1)) <= 65535

    def _by_cloud(self, commercial: str, government: str) -> str:
        """Pick the endpoint for the configured Azure cloud."""
        return government if self.azure_cloud == "government" else commercial

    @property
    def authority(self) -> str:
        """Entra authority host."""
        return self._by_cloud(
            "https://login.microsoftonline.com", "https://login.microsoftonline.us"
        )

    @property
    def management_endpoint(self) -> str:
        """Azure Resource Manager endpoint."""
        return self._by_cloud(
            "https://management.azure.com", "https://management.usgovcloudapi.net"
        )

    @property
    def logs_endpoint(self) -> str:
        """Log Analytics query endpoint."""
        return self._by_cloud("https://api.loganalytics.io", "https://api.loganalytics.us")

    @property
    def storage_audience(self) -> str:
        """Entra audience for Azure Table Storage."""
        return self._by_cloud("https://storage.azure.com", "https://storage.azure.us")

    @property
    def redis_scope(self) -> str:
        """Return the Entra Redis scope, requiring explicit sovereign-cloud verification."""
        if self.redis_token_scope:
            return self.redis_token_scope
        if self.azure_cloud == "government":
            raise ValueError("REDIS_TOKEN_SCOPE must be explicitly verified for Azure Government")
        return "https://redis.azure.com/.default"
