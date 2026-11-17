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
        self.out_of_bounds = meter.create_counter("limiter.usage.out_of_bounds", unit="{record}")
        self.denials = meter.create_counter("limiter.budget.denials", unit="{denial}")
        self.utilization = meter.create_histogram("limiter.budget.utilization", unit="%")
        self.stream_outcomes = meter.create_counter("limiter.stream.outcomes", unit="{stream}")
        self.provider_duration = meter.create_histogram("limiter.provider.duration", unit="ms")
        self.event_publishes = meter.create_counter("limiter.usage.event_publishes", unit="{event}")
        self.background_writes = meter.create_counter("limiter.background.writes", unit="{write}")

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
    def budget(
        self, subject_type: str, model: str, spent: int, limit: int, denied: bool, stage: str
    ) -> None:
        """Record one budget's utilization percentage and count each exhausted cap.

        Dimensions are the hierarchy level and wildcard/model alias, never the
        budget, user or team identifier. ``stage`` is ``admission`` or ``usage``;
        only admission can deny. Percentages may exceed 100 for soft caps.
        """
        attributes = {"subject_type": subject_type, "model": model, "stage": stage}
        if limit > 0:
            self.utilization.record(100 * spent / limit, attributes)
        if denied:
            self.denials.add(1, {"subject_type": subject_type, "model": model})

    @_best_effort
    def stream_outcome(self, protocol: str, outcome: str) -> None:
        """Count how each provider stream ended, including unaccounted provider throttles."""
        self.stream_outcomes.add(1, {"api_protocol": protocol, "outcome": outcome})

    @_best_effort
    def provider_response(
        self, protocol: str, status: int | None, duration_ms: float, error_type: str | None = None
    ) -> None:
        """Record provider time-to-headers by HTTP status, or by exception type on failure."""
        attributes: dict[str, str | int] = {"api_protocol": protocol}
        if status is not None:
            attributes["http_status"] = status
        if error_type is not None:
            attributes["error_type"] = error_type
        self.provider_duration.record(duration_ms, attributes)

    @_best_effort
    def event_publish(self, outcome: str) -> None:
        """Count Event Hub usage-event sends as accepted or failed (not consumer processing)."""
        self.event_publishes.add(1, {"outcome": outcome})

    @_best_effort
    def background_write(self, collection: str, outcome: str) -> None:
        """Count best-effort mirror/export jobs as completed, failed or dropped."""
        self.background_writes.add(1, {"collection": collection, "outcome": outcome})

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
        if event.get("out_of_bounds"):
            self.out_of_bounds.add(1, attributes)
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
