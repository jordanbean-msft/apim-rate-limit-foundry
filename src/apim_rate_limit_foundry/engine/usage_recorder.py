"""Finalize admitted requests into replay-protected, priced usage events."""

import json
from datetime import UTC, datetime

from apim_rate_limit_foundry.accounting import digest, price_usage, usage_partition
from apim_rate_limit_foundry.background_writer import BackgroundWriter
from apim_rate_limit_foundry.engine.budget_status_reporter import BudgetStatusReporter
from apim_rate_limit_foundry.engine.catalog import USAGE_COLLECTION
from apim_rate_limit_foundry.engine.events import event
from apim_rate_limit_foundry.engine.keys import opaque
from apim_rate_limit_foundry.engine.usage_telemetry import UsageTelemetry
from apim_rate_limit_foundry.export.usage_event_publisher import UsageEventPublisher
from apim_rate_limit_foundry.models.admission_context import AdmissionContext
from apim_rate_limit_foundry.models.budget_check import UsageRecordRequest
from apim_rate_limit_foundry.models.priced_usage import PricedUsage
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository
from apim_rate_limit_foundry.telemetry import operation_span


class UsageRecorder:
    """Price usage against admission snapshots and record it exactly once in Redis."""

    def __init__(
        self,
        repository: Repository,
        counters: CounterStore,
        background: BackgroundWriter,
        budget_status: BudgetStatusReporter,
        publisher: UsageEventPublisher | None = None,
    ) -> None:
        """Bind stores, the best-effort mirror, budget reporting and the optional export."""
        self.repository = repository
        self.counters = counters
        self.background = background
        self.budget_status = budget_status
        self.publisher = publisher

    async def record(self, body: UsageRecordRequest) -> Record:
        """Finalize one request and return ``event`` plus its ``replayed`` flag.

        Acceptance atomically records usage and applicable spend in Redis; Table
        mirror and export are asynchronous and lossy. Identical retries return the
        saved event, while conflicting finalizations or missing/denied admission
        raise Conflict.
        """
        with operation_span("usage.record", request_id=body.request_id):
            return await self._record(body)

    async def _record(self, body: UsageRecordRequest) -> Record:
        """Normalize and price against admission snapshots, then atomically deduplicate."""
        fingerprint = self._fingerprint(body)
        prior = await self.counters.usage(body.request_id)
        if prior is not None:
            return self._replayed(prior, body.status, fingerprint)
        request = await self.counters.request(body.request_id)
        if request is None:
            raise Conflict("Budget check not found in operational cache")
        context = AdmissionContext.model_validate(request["data"])
        priced = self._price(body, context)
        event_data = self._event_data(body, context, priced)
        # Reports read the flat fields, while replay reads the nested ``event``.
        record_data = {
            **event_data,
            "submitted_status": body.status,
            "usage_fingerprint": fingerprint,
            "counter_keys": self._counter_keys(context),
            "event": event_data,
        }
        check = context.check
        usage_record = event(
            "usage", request["id"], check.tenant_id, check.principal_id, record_data
        )
        # The store owns atomic increment-plus-replay protection; only its winner
        # schedules the durable mirror and export. Replay cannot repair a lost write.
        saved, created = await self.counters.record(body.request_id, usage_record)
        if not created:
            return self._replayed(saved, body.status, fingerprint)
        self._mirror(request["id"], saved, check.tenant_id, context.month)
        self._export(body.request_id, event_data)
        UsageTelemetry.recorded(body.request_id, check.model, priced, event_data)
        if priced.cost_micro_usd is not None:
            await self.budget_status.report(context)
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
    def _replayed(saved: Record, status: str, fingerprint: str) -> Record:
        """Return the saved event for an identical retry, rejecting any differing one.

        Differences are rejected even if both submissions would normalize alike.
        """
        if saved["data"]["submitted_status"] != status:
            raise Conflict("Usage request already finalized differently")
        if saved["data"]["usage_fingerprint"] != fingerprint:
            raise Conflict("Usage request replayed with different provider usage")
        UsageTelemetry.replayed(saved["data"]["event"])
        return {"event": saved["data"]["event"], "replayed": True}

    @staticmethod
    def _price(body: UsageRecordRequest, context: AdmissionContext) -> PricedUsage:
        """Price provider usage with the admission snapshot, charging unknown usage its bound.

        Invalid/missing usage is never treated as free: it is flagged unknown and
        charged the upper bound pinned at admission so budgets still decrement.
        """
        if not context.decision.allowed:
            raise Conflict("Denied requests cannot be charged")
        if body.status == "usage_unknown" and body.provider_usage is not None:
            raise ValueError("Unknown usage must not include fabricated provider counters")
        return price_usage(
            body.status,
            body.provider_usage,
            context.check.api_protocol,
            context.price,
            context.model_bounds,
        )

    @staticmethod
    def _counter_keys(context: AdmissionContext) -> list[str]:
        """Name the six subject/model projections updated for every accepted usage.

        They are updated even when no matching budget exists yet, so later caps see
        prior operational spend.
        """
        check = context.check
        return [
            digest(check.tenant_id, kind, subject_id, context.month, model)
            for kind, subject_id in (
                ("user", check.principal_id),
                ("team", context.organization.team_id),
                ("department", context.organization.department_id),
            )
            for model in ("*", check.model)
        ]

    @staticmethod
    def _event_data(
        body: UsageRecordRequest, context: AdmissionContext, priced: PricedUsage
    ) -> Record:
        """Assemble the finalized usage event from admission snapshots and priced counts."""
        check = context.check
        organization = context.organization
        usage = priced.counts
        return {
            "event_version": 2,
            "event_name": "usage_recorded",
            "event_id": digest("usage-event-v2", check.tenant_id, body.request_id),
            "request_id": body.request_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "month": context.month,
            "tenant_ref": opaque(check.tenant_id),
            "user_ref": opaque(check.tenant_id, check.principal_id),
            "team_id": organization.team_id,
            "department_id": organization.department_id,
            "business_unit": organization.business_unit,
            "cost_center": organization.cost_center,
            "subscription_id": check.subscription_id,
            "model": check.model,
            "api_protocol": check.api_protocol,
            "streaming": check.streaming,
            "status": priced.status,
            "input_tokens": usage.input_tokens if usage else None,
            "cached_input_tokens": usage.cached_input_tokens if usage else None,
            "cache_write_tokens": usage.cache_write_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "cost_micro_usd": priced.cost_micro_usd,
            "cost_basis": priced.cost_basis,
            "out_of_bounds": priced.out_of_bounds,
            "price_version": context.price_version,
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

    def _export(self, request_id: str, usage_event: Record) -> None:
        """Schedule the lossy downstream copy; a replayed request never reaches here."""
        publisher = self.publisher
        if publisher is not None:
            self.background.submit(
                "usage_event", request_id, lambda: publisher.publish(usage_event)
            )
