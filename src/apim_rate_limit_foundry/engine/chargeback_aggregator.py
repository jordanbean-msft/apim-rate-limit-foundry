"""Aggregate durable usage events into chargeback groups."""

from apim_rate_limit_foundry.stores.contracts import Record

# Chargeback dimensions in report order; CSV export and grouping share them.
DIMENSION_FIELDS = (
    "business_unit",
    "cost_center",
    "department_id",
    "team_id",
    "user_ref",
    "subscription_id",
    "model",
    "month",
)
GROUP_FIELDS = (*DIMENSION_FIELDS, "status", "cost_basis")
TOTAL_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "cost_micro_usd",
)


class ChargebackAggregator:
    """Group events by their original chargeback dimensions.

    Unknown usage forms separate groups with null token totals, a request count and
    its estimated upper-bound cost (null only for history written before estimates
    existed); it is never counted as zero-priced actual usage.
    """

    def aggregate(self, records: list[Record], principal_id: str | None) -> list[Record]:
        """Group stored usage records, optionally narrowed to one principal."""
        groups: dict[tuple[str, ...], Record] = {}
        for record in records:
            if principal_id and record.get("principal_id") != principal_id:
                continue
            data = record["data"]
            key = tuple(str(data.get(field) or "") for field in GROUP_FIELDS)
            unknown = data.get("status") == "usage_unknown"
            group = groups.setdefault(key, self._new_group(key, unknown))
            if unknown:
                self._add_unknown(group, data)
            else:
                self._add_actual(group, data)
        return list(groups.values())

    @staticmethod
    def _new_group(key: tuple[str, ...], unknown: bool) -> Record:
        """Start a group whose totals are null for unknown usage and zero otherwise."""
        return {
            "business_unit": key[0],
            "cost_center": key[1],
            "department_id": key[2],
            "team_id": key[3],
            "user_ref": key[4],
            "subscription_id": key[5],
            "model": key[6],
            "month": key[7],
            "cost_basis": key[9] or ("unpriced" if unknown else "provider_usage"),
            **{field: None if unknown else 0 for field in TOTAL_FIELDS},
            "unknown_requests": 0,
        }

    @staticmethod
    def _add_unknown(group: Record, data: Record) -> None:
        group["unknown_requests"] += 1
        if data.get("cost_micro_usd") is not None:
            group["cost_micro_usd"] = (group["cost_micro_usd"] or 0) + data["cost_micro_usd"]

    @staticmethod
    def _add_actual(group: Record, data: Record) -> None:
        for field in TOTAL_FIELDS:
            group[field] += data.get(field) or 0
