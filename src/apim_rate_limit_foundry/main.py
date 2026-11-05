import uvicorn

from apim_rate_limit_foundry.api import create_app
from apim_rate_limit_foundry.telemetry import configure_logging


def main() -> None:
    configure_logging()
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
