"""Application-owned tracing, separate from framework-global auto collectors."""

from opentelemetry import trace

from apim_rate_limit_foundry.telemetry.context import LOGGER_NAME

provider: trace.TracerProvider | None = None


def get_tracer() -> trace.Tracer:
    """Use the configured private provider, or the default no-op provider locally."""
    return (
        provider.get_tracer(LOGGER_NAME) if provider is not None else trace.get_tracer(LOGGER_NAME)
    )
