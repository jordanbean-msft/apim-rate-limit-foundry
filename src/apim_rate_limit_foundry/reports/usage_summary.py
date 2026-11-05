from datetime import datetime
from typing import Literal

from apim_rate_limit_foundry.accounting import cost, digest, window
from apim_rate_limit_foundry.models import Price, Reserve, Usage, UsageSummary
from apim_rate_limit_foundry.stores.contracts import Record, Repository


class UsageSummaryService:
    """Rebuild UTC admission-time rollups so late settlement replaces, never adds, charges."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    @staticmethod
    def _contribution(
        request: Reserve, price: Price, settlement: Record | None
    ) -> tuple[Usage, int, bool]:
        if settlement is None or settlement["data"]["status"] != "actual":
            return request.usage, cost(price, request.usage, True), True
        data = settlement["data"]
        usage = Usage.model_validate(data["usage"])
        cached_reported = data.get("cached_input_reported", bool(usage.cached_input_tokens))
        estimated = bool(data["estimated"]) or (
            request.service == "foundry" and usage.input_tokens > 0 and not cached_reported
        )
        return usage, cost(price, usage, not cached_reported), estimated

    async def summarize(
        self,
        period: Literal["hour", "day"],
        tenant: str,
        principal: str,
        admin: bool,
    ) -> list[UsageSummary]:
        summaries: dict[str, UsageSummary] = {}
        seen: set[str] = set()
        for record in await self.repository.list("usage"):
            if not admin and (record["tenant_id"] != tenant or record["principal_id"] != principal):
                continue
            if record["id"] in seen:
                continue
            seen.add(record["id"])
            request = Reserve.model_validate(record["data"]["request"])
            timestamp = datetime.fromisoformat(record["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError("Durable admission timestamp must include a timezone")
            start, end = window(period, timestamp)
            summary_id = digest(
                record["tenant_id"],
                record["principal_id"],
                request.service,
                request.model,
                period,
                start.isoformat(),
            )
            if summary_id not in summaries:
                summaries[summary_id] = UsageSummary(
                    id=summary_id,
                    tenant_id=record["tenant_id"],
                    principal_id=record["principal_id"],
                    service=request.service,
                    model=request.model,
                    period=period,
                    start_at=start,
                    end_at=end,
                )
            summary = summaries[summary_id]
            summary.request_count += 1
            if not record["data"]["allowed"]:
                summary.denied_requests += 1
                continue
            summary.admitted_requests += 1
            settlement = await self.repository.get("settlements", record["id"])
            usage, charge, estimated = self._contribution(
                request,
                Price.model_validate(record["data"]["price"]),
                settlement,
            )
            summary.estimated_requests += int(estimated)
            summary.cost_micro_usd += charge
            summary.input_tokens += usage.input_tokens
            summary.output_tokens += usage.output_tokens
            summary.cached_input_tokens += usage.cached_input_tokens
            summary.pages += usage.pages
            summary.text_records += usage.text_records
        return sorted(
            summaries.values(),
            key=lambda row: (row.start_at, row.tenant_id, row.principal_id, row.service, row.model),
        )
