"""Finalize admitted requests into replay-protected, priced usage events."""

import json
import logging
from datetime import UTC, datetime

from apim_rate_limit_foundry.accounting import digest, price_usage, usage_partition
from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.engine.admission_resolver import AdmissionResolver
from apim_rate_limit_foundry.engine.catalog import USAGE_COLLECTION
from apim_rate_limit_foundry.engine.events import event
from apim_rate_limit_foundry.engine.keys import opaque
from apim_rate_limit_foundry.models import Price
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.models.priced_usage import PricedUsage
from apim_rate_limit_foundry.rate_limit_metrics import rate_metrics
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import emit, operation_span


class UsageRecorder:
    """Price usage against admission snapshots and record it exactly once in Redis."""

    def __init__(
        self,
        repository: Repository,
        counters: CounterStore,
        background: BackgroundWriter,
        resolver: AdmissionResolver,
    ) -> None:
        """Bind stores, the best-effort mirror and the bounds resolver."""
        self.repository = repository
        self.counters = counters
        self.background = background
        self.resolver = resolver

    async def record(self, body: UsageRecordRequest) -> Record:
        """Finalize one request and return ``event`` plus its ``replayed`` flag.

        Acceptance atomically records usage and applicable spend in Redis; Table
        export is asynchronous and lossy. Identical retries return the saved event,
        while conflicting finalizations or missing/denied admission raise Conflict.
        """
        with operation_span("usage.record", request_id=body.request_id):
            return await self._record(body)

    async def _record(self, body: UsageRecordRequest) -> Record:
        """Normalize and price against admission snapshots, then atomically deduplicate."""
        fingerprint = self._fingerprint(body)
        prior = await self.counters.usage(body.request_id)
        if prior is not None:
            self._validate_replay(prior, body.status, fingerprint)
            return self._replayed(prior["data"]["event"])
        request = await self.counters.request(body.request_id)
        if request is None:
            raise Conflict("Budget check not found in operational cache")
        data = request["data"]
        priced = self._price(body, data)
        event_data = self._event_data(body, data, priced)
        record_data = {
            **event_data,
            "submitted_status": body.status,
            "usage_fingerprint": fingerprint,
            "counter_keys": self._counter_keys(data),
            "event": event_data,
        }
        check = data["check"]
        usage_record = event(
            "usage", request["id"], check["tenant_id"], check["principal_id"], record_data
        )
        # The store owns atomic increment-plus-replay protection; only its winner
        # schedules a durable mirror. Replay cannot repair a previously lost write.
        saved, created = await self.counters.record(body.request_id, usage_record)
        if not created:
            self._validate_replay(saved, body.status, fingerprint)
            return self._replayed(saved["data"]["event"])
        self._mirror(request["id"], saved, check["tenant_id"], data["month"])
        self._emit_recorded(body, check, priced, event_data)
        rate_metrics.usage(saved["data"]["event"], False)
        return {"event": saved["data"]["event"], "replayed": False}

    @staticmethod
    def _fingerprint(body: UsageRecordRequest) -> str:
        """Hash submitted status and canonical provider JSON, ignoring object key order."""
        serialized = (
            json.dumps(body.provider_usage, sort_keys=True, separators=(",", ":"))
            if body.provider_usage is not None
            else ""
        )
        return digest(body.status, serialized)

    @staticmethod
    def _validate_replay(record: Record, status: str, fingerprint: str) -> None:
        """Reject retries differing from the original submission, even if both normalize alike."""
        if record["data"]["submitted_status"] != status:
            raise Conflict("Usage request already finalized differently")
        if record["data"]["usage_fingerprint"] != fingerprint:
            raise Conflict("Usage request replayed with different provider usage")

    @staticmethod
    def _replayed(saved_event: Record) -> Record:
        """Report an identical retry with the originally saved event."""
        emit("usage_record_replayed", **saved_event, replayed=True)
        rate_metrics.usage(saved_event, True)
        return {"event": saved_event, "replayed": True}

    def _price(self, body: UsageRecordRequest, data: Record) -> PricedUsage:
        """Price provider usage with the admission snapshot, charging unknown usage its bound.

        Invalid/missing usage is never treated as free: it is flagged unknown and
        charged the upper bound pinned at admission so budgets still decrement.
        """
        if not data["decision"]["allowed"]:
            raise Conflict("Denied requests cannot be charged")
        if body.status == "usage_unknown" and body.provider_usage is not None:
            raise ValueError("Unknown usage must not include fabricated provider counters")
        return price_usage(
            body.status,
            body.provider_usage,
            data["check"]["api_protocol"],
            Price.model_validate(data["price"]),
            self.resolver.pinned_bounds(data),
        )

    @staticmethod
    def _counter_keys(data: Record) -> list[str]:
        """Name the six subject/model projections updated for every accepted usage.

        They are updated even when no matching budget exists yet, so later caps see
        prior operational spend.
        """
        check = data["check"]
        snapshot = data["organization"]
        return [
            digest(check["tenant_id"], kind, subject_id, data["month"], model)
            for kind, subject_id in (
                ("user", check["principal_id"]),
                ("team", snapshot["team_id"]),
                ("department", snapshot["department_id"]),
            )
            for model in ("*", check["model"])
        ]

    @staticmethod
    def _event_data(body: UsageRecordRequest, data: Record, priced: PricedUsage) -> Record:
        """Assemble the finalized usage event from admission snapshots and priced counts."""
        check = data["check"]
        snapshot = data["organization"]
        usage = priced.counts
        return {
            "event_version": 2,
            "event_name": "usage_recorded",
            "event_id": digest("usage-event-v2", check["tenant_id"], body.request_id),
            "request_id": body.request_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "month": data["month"],
            "tenant_ref": opaque(check["tenant_id"]),
            "user_ref": opaque(check["tenant_id"], check["principal_id"]),
            "team_id": snapshot["team_id"],
            "department_id": snapshot["department_id"],
            "business_unit": snapshot["business_unit"],
            "cost_center": snapshot["cost_center"],
            "subscription_id": check["subscription_id"],
            "model": check["model"],
            "api_protocol": check["api_protocol"],
            "streaming": check["streaming"],
            "status": priced.status,
            "input_tokens": usage.input_tokens if usage else None,
            "cached_input_tokens": usage.cached_input_tokens if usage else None,
            "cache_write_tokens": usage.cache_write_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "cost_micro_usd": priced.cost_micro_usd,
            "cost_basis": priced.cost_basis,
            "out_of_bounds": priced.out_of_bounds,
            "price_version": data["price_version"],
        }

    def _mirror(self, request_key: str, saved: Record, tenant_id: str, month: str) -> None:
        """Schedule the lossy durable copy of an accepted usage record."""
        self.background.submit(
            USAGE_COLLECTION,
            request_key,
            lambda: self.repository.create(
                USAGE_COLLECTION, request_key, saved, usage_partition(tenant_id, month)
            ),
        )

    @staticmethod
    def _emit_recorded(
        body: UsageRecordRequest, check: Record, priced: PricedUsage, event_data: Record
    ) -> None:
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
                request_id=body.request_id,
                model=check["model"],
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                cost_micro_usd=priced.cost_micro_usd,
            )
