"""Authorized caller rollups over immutable admissions, never per-policy debits."""

from datetime import datetime
from typing import Literal

from apim_rate_limit_foundry.accounting import digest, window
from apim_rate_limit_foundry.caller_reference import caller_ref
from apim_rate_limit_foundry.models import Price, Reserve
from apim_rate_limit_foundry.models.caller_usage import CallerUsage
from apim_rate_limit_foundry.reports.usage_summary import UsageSummaryService
from apim_rate_limit_foundry.stores.contracts import Repository


class CallerUsageService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def summarize(
        self,
        period: Literal["hour", "day"],
        tenant: str,
        principal: str,
        admin: bool,
    ) -> list[CallerUsage]:
        labels: dict[tuple[str, str], str] = {}
        for assignment in sorted(
            await self.repository.list("assignments"), key=lambda row: row["id"]
        ):
            if (
                assignment.get("_deleted")
                or not assignment.get("display_label")
                or "subscription_id" not in assignment
            ):
                continue
            identity = (assignment["tenant_id"], assignment["subscription_id"])
            if admin or (
                assignment["tenant_id"] == tenant
                and principal in assignment.get("reader_principal_ids", [])
            ):
                # Multiple assignments may bind the same caller: first labeled ID wins.
                labels.setdefault(identity, assignment["display_label"])

        summaries: dict[str, CallerUsage] = {}
        seen: set[tuple[str, str, str]] = set()
        visible = {
            (assignment["tenant_id"], assignment["subscription_id"])
            for assignment in await self.repository.list("assignments")
            if assignment.get("tenant_id") == tenant
            and "subscription_id" in assignment
            and principal in assignment.get("reader_principal_ids", [])
        }
        for record in await self.repository.list("usage"):
            stored_request = record["data"].get("request", {})
            subscription_id = record.get("subscription_id") or stored_request.get("subscription_id")
            if not subscription_id:
                continue
            identity = (record["tenant_id"], subscription_id)
            if not admin and identity not in visible:
                continue
            admission = (*identity, record["id"])
            if admission in seen:
                continue
            seen.add(admission)
            data = record["data"]
            request = Reserve.model_validate(data["request"])
            timestamp = datetime.fromisoformat(record["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError("Durable admission timestamp must include a timezone")
            start, end = window(period, timestamp)
            reference = caller_ref(*identity)
            summary_id = digest(
                reference,
                request.service,
                request.model,
                request.effective_protocol or "",
                str(request.streaming),
                period,
                start.isoformat(),
            )
            if summary_id not in summaries:
                summaries[summary_id] = CallerUsage(
                    id=summary_id,
                    tenant_id=identity[0],
                    subscription_id=identity[1],
                    caller_ref=reference,
                    display_label=labels.get(identity),
                    service=request.service,
                    model=request.model,
                    api_protocol=request.effective_protocol,
                    streaming=request.streaming,
                    period=period,
                    start_at=start,
                    end_at=end,
                )
            summary = summaries[summary_id]
            summary.request_count += 1
            if not data["allowed"]:
                summary.denied_requests += 1
                for policy_id in set(data.get("denied_policy_ids", [])):
                    summary.denied_policy_counts[policy_id] = (
                        summary.denied_policy_counts.get(policy_id, 0) + 1
                    )
                continue
            summary.admitted_requests += 1
            settlement = await self.repository.get("settlements", record["id"])
            usage, charge, estimated = UsageSummaryService.contribution(
                request, Price.model_validate(data["price"]), settlement
            )
            summary.cost_micro_usd += charge
            summary.estimated_requests += int(estimated)
            if estimated:
                summary.conservative_cost_micro_usd += charge
            else:
                summary.actual_cost_micro_usd += charge
            for field in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens_5m",
                "cache_write_input_tokens_1h",
                "pages",
                "text_records",
            ):
                setattr(summary, field, getattr(summary, field) + getattr(usage, field))
        return sorted(
            summaries.values(),
            key=lambda row: (
                row.start_at,
                row.tenant_id,
                row.subscription_id,
                row.service,
                row.model,
                row.api_protocol or "",
                row.streaming,
            ),
        )
