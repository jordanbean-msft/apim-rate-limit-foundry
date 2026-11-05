import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = {
            key: getattr(record, key)
            for key in ("reservation_id", "allowed", "service", "error_type")
            if hasattr(record, key)
        }
        return json.dumps({"level": record.levelname, "event": record.getMessage(), **context})


def configure_logging() -> None:
    logger = logging.getLogger("apim_rate_limit_foundry")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
