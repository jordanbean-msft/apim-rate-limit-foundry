"""Structured stdout logging and the privacy filter shared with the cloud exporter."""

import json
import logging

from apim_rate_limit_foundry.telemetry.context import LOGGER_NAME
from apim_rate_limit_foundry.telemetry.sanitizer import safe_attributes, safe_event

_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_NOISY_LOGGERS = ("azure.core.pipeline.policies.http_logging_policy", "azure.identity")


class JsonFormatter(logging.Formatter):
    """Write the same restricted event schema to stdout as to cloud telemetry."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "event": safe_event(record.msg),
                **safe_attributes(record.__dict__),
            }
        )


class SafeTelemetryFilter(logging.Filter):
    """Sanitize before either stdout formatting or the OTel handler sees the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Remove unsafe extras and exception material in-place before any exporter."""
        attributes = safe_attributes(record.__dict__)
        for name in tuple(record.__dict__):
            if name not in _LOG_RECORD_FIELDS:
                del record.__dict__[name]
        record.__dict__.update(attributes)
        record.msg = safe_event(record.msg)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging() -> None:
    """Idempotently configure domain handlers and suppress noisy credential loggers."""
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(JsonFormatter())
        logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        if not any(isinstance(f, SafeTelemetryFilter) for f in handler.filters):
            handler.addFilter(SafeTelemetryFilter())
    # The explicit distro handler exports this logger, not the Functions root logger.
    logger.propagate = False
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
