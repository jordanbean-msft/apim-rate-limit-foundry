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
            return request.usage, cost(price, request.usage, True, request.effective_protocol), True
        data = settlement["data"]
        usage = Usage.model_validate(data["usage"])
        cached_reported = data.get("cached_input_reported", bool(usage.cached_input_tokens))
        writes_reported = request.effective_protocol != "anthropic-messages" or data.get(
            "cache_write_input_reported",
            False,
        )
        conservative_input = not cached_reported or not writes_reported
        estimated = bool(data["estimated"]) or (
            request.service == "foundry" and usage.input_tokens > 0 and conservative_input
        )
        return usage, cost(price, usage, conservative_input, request.effective_protocol), estimated

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
            dimensions = [
                record["tenant_id"],
                record["principal_id"],
                request.service,
                request.model,
                period,
                start.isoformat(),
            ]
            if request.effective_protocol not in (None, "openai-chat"):
                dimensions.append(request.effective_protocol)
            summary_id = digest(*dimensions)
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
                    api_protocol=request.effective_protocol,
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
            summary.cache_write_input_tokens_5m += usage.cache_write_input_tokens_5m
            summary.cache_write_input_tokens_1h += usage.cache_write_input_tokens_1h
            summary.pages += usage.pages
            summary.text_records += usage.text_records
        return sorted(
            summaries.values(),
            key=lambda row: (row.start_at, row.tenant_id, row.principal_id, row.service, row.model),
        )
