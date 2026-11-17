"""Signals for finalized usage, kept apart from the pricing and replay logic."""

import logging

from apim_rate_limit_foundry.models.priced_usage import PricedUsage
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import Record
from apim_rate_limit_foundry.telemetry import emit


class UsageTelemetry:
    """Emit the events and metrics describing one accepted or replayed usage record."""

    @staticmethod
    def recorded(request_id: str, model: str, priced: PricedUsage, event_data: Record) -> None:
        """Emit the accepted-usage event, plus a warning when counts exceeded model bounds."""
        usage = priced.counts
        emit(
            "usage_recorded",
            **event_data,
            reason=priced.reason,
            replayed=False,
            uncached_input_tokens=usage.uncached_input_tokens if usage else None,
            total_tokens=usage.input_tokens + usage.output_tokens if usage else None,
            cache_hit=usage.cached_input_tokens > 0 if usage else None,
        )
        if priced.out_of_bounds:
            emit(
                "usage_out_of_bounds",
                level=logging.WARNING,
                request_id=request_id,
                model=model,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                cost_micro_usd=priced.cost_micro_usd,
            )
        rate_metrics.usage(event_data, False)

    @staticmethod
    def replayed(saved_event: Record) -> None:
        """Report an identical retry with the originally saved event."""
        emit("usage_record_replayed", **saved_event, replayed=True)
        rate_metrics.usage(saved_event, True)
