"""Deployment settings for the optional loader, without the application's .env file."""

from pydantic_settings import SettingsConfigDict

from apim_rate_limit_foundry.config import Settings


class DemoSettings(Settings):
    """Reuse store configuration while keeping the demo deployment's file explicit."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")
