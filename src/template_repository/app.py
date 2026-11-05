import logging
import logging.config
import pathlib
from contextlib import asynccontextmanager
from typing import ClassVar

from fastapi import FastAPI

from template_repository.config import get_settings


class _ColoredFormatter(logging.Formatter):
    """Formatter that colorizes timestamp, level, logger name, and message."""

    _RESET = "\033[0m"
    _DIM = "\033[2m"  # dim gray — for timestamp
    _BLUE = "\033[34m"  # blue — for logger name
    _LEVEL_COLORS: ClassVar[dict[int, str]] = {
        logging.DEBUG: "\033[36m",  # cyan
        logging.INFO: "\033[32m",  # green
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",  # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    # For WARNING and above the message body also gets the level color
    _COLORED_MSG_LEVELS = frozenset({logging.WARNING, logging.ERROR, logging.CRITICAL})

    def format(self, record: logging.LogRecord) -> str:
        color = self._LEVEL_COLORS.get(record.levelno, self._RESET)
        r = logging.makeLogRecord(record.__dict__)
        r.levelname = f"{color}{r.levelname:<8}{self._RESET}"
        r.name = f"{self._BLUE}{r.name}{self._RESET}"
        if record.levelno in self._COLORED_MSG_LEVELS:
            r.msg = f"{color}{r.msg}{self._RESET}"
        formatted = super().format(r)
        # Dim the leading timestamp (everything before the first space after the time)
        time_end = formatted.index(" ", 11)  # skip past "YYYY-MM-DD "
        return f"{self._DIM}{formatted[:time_end]}{self._RESET}{formatted[time_end:]}"


# Ensure the logs directory exists before configuring file handler
_LOG_DIR = pathlib.Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

_settings = get_settings()
logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": _ColoredFormatter,
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "plain": {
                "class": "logging.Formatter",
                "format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
            "file": {
                "class": "logging.FileHandler",
                "formatter": "plain",
                "filename": str(_LOG_DIR / "app.log"),
                "mode": "w",  # truncate on each start
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": _settings.log_level.upper(),
        },
    }
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logger.info("Application startup")
        yield
        # Shutdown
        logger.info("Application shutdown")

    app = FastAPI(title="template-repository", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
