"""Restore explicit, non-secret azd configuration for a manual CI deployment."""

import json
import re
import subprocess

from pydantic_settings import BaseSettings, SettingsConfigDict


class CISettings(BaseSettings):
    azure_env_name: str
    azure_cloud: str
    azure_subscription_id: str
    azure_tenant_id: str
    azd_env_json: str

    model_config = SettingsConfigDict(extra="ignore")


def main() -> None:
    settings = CISettings()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", settings.azure_env_name):
        raise ValueError("Invalid azd environment name")
    if settings.azure_cloud not in {"AzureCloud", "AzureUSGovernment"}:
        raise ValueError("Unsupported Azure cloud")
    values = json.loads(settings.azd_env_json)
    if not isinstance(values, dict) or not values:
        raise ValueError("AZD_ENV_JSON must be a non-empty JSON object of azd variables")
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not isinstance(value, str):
            raise ValueError("azd configuration must contain uppercase keys and string values")
    for key, expected in {
        "AZURE_ENV_NAME": settings.azure_env_name,
        "AZURE_CLOUD": settings.azure_cloud,
        "AZURE_SUBSCRIPTION_ID": settings.azure_subscription_id,
        "AZURE_TENANT_ID": settings.azure_tenant_id,
    }.items():
        if key in values and values[key] != expected:
            raise ValueError(f"{key} conflicts with the selected workflow environment")
        values[key] = expected
    subprocess.run(
        ["azd", "env", "new", settings.azure_env_name, "--no-prompt"],
        check=True,
    )
    for key, value in values.items():
        subprocess.run(["azd", "env", "set", key, value], check=True)


if __name__ == "__main__":
    main()
