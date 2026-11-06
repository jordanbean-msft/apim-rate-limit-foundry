import uvicorn

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.monitoring import configure_monitoring


def main() -> None:
    settings = Settings()
    configure_monitoring(settings)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
