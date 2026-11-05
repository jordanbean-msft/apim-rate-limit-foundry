import logging
import os

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    log_level: str = "INFO"
    port: int = 8000
    host: str = "0.0.0.0"

    # Environment detection for authentication strategy
    # Set to "development" for local dev, anything else uses ManagedIdentityCredential
    azure_environment: str = os.getenv("AZURE_ENVIRONMENT", "development")

    model_config = {"env_file": ".env", "extra": "ignore"}


def get_settings() -> Settings:
    return Settings()
