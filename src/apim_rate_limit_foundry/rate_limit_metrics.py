"""Low-cardinality metrics for live Redis decisions and accepted usage."""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from opentelemetry.metrics import Meter, get_meter

from apim_rate_limit_foundry.telemetry import emit


def _best_effort[**P](function: Callable[P, None]) -> Callable[P, None]:
    """Log instrumentation errors without allowing metrics to reject valid traffic."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            function(*args, **kwargs)
        except Exception as error:
            emit(
                "metric_record_failed",
                level=logging.WARNING,
                error_type=type(error).__name__,
            )

    return wrapped


class RateLimitMetrics:
    """Operational counters/histograms without request, user or tenant dimensions."""

    def __init__(self, meter: Meter) -> None:
        self.requests = meter.create_counter("limiter.http.requests", unit="{request}")
        self.duration = meter.create_histogram("limiter.http.duration", unit="ms")
        self.decisions = meter.create_counter("limiter.budget.decisions", unit="{decision}")
        self.records = meter.create_counter("limiter.usage.records", unit="{record}")
        self.tokens = meter.create_counter("limiter.usage.tokens", unit="{token}")
        self.cost = meter.create_counter("limiter.usage.cost", unit="{microUSD}")

    @_best_effort
    def request(
        self, method: str, route: str, status: int, duration_ms: float, outcome: str
    ) -> None:
        """Record one HTTP outcome and elapsed milliseconds for a templated route."""
        attributes: dict[str, str | int] = {
            "http_method": method,
            "route": route,
            "http_status": status,
            "status": outcome,
        }
        self.requests.add(1, attributes)
        self.duration.record(duration_ms, attributes)

    @_best_effort
    def decision(
        self, model: str, protocol: str, streaming: bool, allowed: bool, replayed: bool
    ) -> None:
        """Count decision evaluations, explicitly distinguishing replay observations."""
        self.decisions.add(
            1,
            {
                "model": model,
                "api_protocol": protocol,
                "streaming": streaming,
                "allowed": allowed,
                "replayed": replayed,
            },
        )

    @_best_effort
    def usage(self, event: dict[str, Any], replayed: bool) -> None:
        """Count all usage observations; add tokens for fresh actual usage and cost for any charge.

        Cached and cache-write input are subsets of input, so they are removed from
        uncached tokens before summing categories. Unknown usage adds no tokens but
        its estimated upper-bound cost is recorded under that ``cost_basis``.
        """
        attributes = {key: event[key] for key in ("model", "api_protocol", "streaming", "status")}
        self.records.add(1, {**attributes, "replayed": replayed})
        if replayed:
            return
        if event["status"] == "actual":
            cached = event["cached_input_tokens"]
            cache_write = event.get("cache_write_tokens") or 0
            for kind, count in (
                ("uncached_input", event["input_tokens"] - cached - cache_write),
                ("cached_input", cached),
                ("cache_write_input", cache_write),
                ("output", event["output_tokens"]),
            ):
                self.tokens.add(count, {**attributes, "token_type": kind})
        if event["cost_micro_usd"] is not None:
            cost_basis = event.get("cost_basis") or "provider_usage"
            self.cost.add(event["cost_micro_usd"], {**attributes, "cost_basis": cost_basis})


rate_metrics = RateLimitMetrics(get_meter(__name__))
