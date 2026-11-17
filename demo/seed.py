"""Seed fictional configuration and accounted usage into empty, isolated Table/Redis stores."""

import argparse
import asyncio
import json
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from pydantic_settings import DotEnvSettingsSource

from apim_rate_limit_foundry.accounting import normalize_openai_usage, usage_partition, utc_month
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import CONFIG_MODELS, USAGE_COLLECTION, GatewayServices
from apim_rate_limit_foundry.models.budget_check import BudgetCheck, UsageRecordRequest
from apim_rate_limit_foundry.runtime import Runtime
from apim_rate_limit_foundry.stores.contracts import LEDGER_PARTITION, Record
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository
from demo.settings import DemoSettings

DATA_FILE = Path(__file__).parent / "data" / "office.json"
COLLECTIONS = ("organizations", "assignments", "prices", "budgets")


def load_data(path: Path, tenant_id: str, principal_map: dict[str, str]) -> Record:
    """Validate seed inputs and substitute the explicitly selected tenant and principals."""
    data = json.loads(path.read_text())
    collections = data["collections"]
    principals = {row["principal_id"] for row in collections["assignments"]}
    if principal_map.keys() - principals:
        raise ValueError("Principal mapping contains an unknown fictional principal")
    mapped = [principal_map.get(principal, principal) for principal in principals]
    if len(set(mapped)) != len(mapped) or any(not value for value in mapped):
        raise ValueError("Principal mapping must contain distinct, non-empty identifiers")
    for collection in COLLECTIONS:
        records = []
        for source in collections[collection]:
            record = {**source}
            if "tenant_id" in record:
                record["tenant_id"] = tenant_id
            if collection == "assignments":
                record["principal_id"] = principal_map.get(
                    record["principal_id"], record["principal_id"]
                )
            if collection == "budgets" and record["subject_type"] == "user":
                record["subject_id"] = principal_map.get(record["subject_id"], record["subject_id"])
            records.append(
                CONFIG_MODELS[collection]
                .model_validate(record)
                .model_dump(mode="json", exclude_none=True)
            )
        collections[collection] = records
    for usage in collections["usage"]:
        usage["principal_id"] = principal_map.get(usage["principal_id"], usage["principal_id"])
    return data


def usage_inputs(source: Record, tenant_id: str) -> tuple[BudgetCheck, UsageRecordRequest]:
    """Convert fictional normalized counts to the real gateway's admission/usage contracts."""
    month, _ = utc_month()
    check = BudgetCheck.model_validate(
        {
            "request_id": f"office-{month}-{source['request_id']}",
            "tenant_id": tenant_id,
            "principal_id": source["principal_id"],
            "subscription_id": source["subscription_id"],
            "model": source["model"],
            "api_protocol": source["api_protocol"],
            "streaming": source["streaming"],
        }
    )
    provider_usage = None
    if source["status"] == "actual":
        input_name, output_name, details_name = (
            ("prompt_tokens", "completion_tokens", "prompt_tokens_details")
            if check.api_protocol == "openai-chat"
            else ("input_tokens", "output_tokens", "input_tokens_details")
        )
        provider_usage = {
            input_name: source["input_tokens"],
            output_name: source["output_tokens"],
            details_name: {"cached_tokens": source["cached_input_tokens"]},
        }
        normalize_openai_usage(provider_usage, check.api_protocol)
    usage = UsageRecordRequest(
        request_id=check.request_id,
        status=source["status"],
        provider_usage=provider_usage,
    )
    return check, usage


async def seed_data(gateway: GatewayServices, data: Record, tenant_id: str) -> None:
    """Use normal services and synchronously verify durable history as well as Redis acceptance."""
    for collection in COLLECTIONS:
        for record in data["collections"][collection]:
            await gateway.configuration.save(
                collection, record["id"], record, tenant_id, "office-seed"
            )
    for source in data["collections"]["usage"]:
        check, usage = usage_inputs(source, tenant_id)
        decision = await gateway.admission.check(check)
        if not decision["allowed"]:
            raise ValueError(f"Demo request was denied: {check.request_id}")
        await gateway.usage.record(usage)
        request = await gateway.counters.request(check.request_id)
        saved = await gateway.counters.usage(check.request_id)
        if request is None or saved is None:
            raise RuntimeError("Demo accounting was not retained in Redis")
        # Normal requests mirror best-effort; seeding must confirm both durable records.
        for collection, record, partition in (
            ("requests", request, LEDGER_PARTITION),
            (USAGE_COLLECTION, saved, usage_partition(tenant_id, saved["data"]["month"])),
        ):
            await gateway.repository.create(collection, record["id"], record, partition)
            if await gateway.repository.get(collection, record["id"], partition) != record:
                raise RuntimeError("Demo history did not persist as expected")


async def require_empty_stores(repository: TableRepository, counters: RedisCounters) -> None:
    """Reject existing state before writes; callers must stop all other writers during seeding."""
    client = await counters.connection()
    if await client.dbsize():
        raise ValueError("Refusing to seed non-empty Redis; use a dedicated empty store")
    try:
        async for _ in repository.client.list_entities(results_per_page=1):
            raise ValueError("Refusing to seed non-empty Table Storage; use a new table")
    except ResourceNotFoundError:
        await repository.client.create_table()


async def apply_data(data: Record, tenant_id: str, settings: Settings) -> None:
    """Rehearse offline, then write once to explicitly configured persistent stores."""
    if settings.local_store_enabled and not (
        settings.local_redis_url and settings.local_table_connection_string
    ):
        raise ValueError("Demo deployment requires persistent Table Storage and Redis, not memory")
    rehearsal = GatewayServices.create(MemoryRepository(), MemoryCounters(settings), settings)
    try:
        await seed_data(rehearsal, data, tenant_id)
    finally:
        await rehearsal.close()
    runtime = Runtime(settings)
    try:
        repository, counters = runtime.gateway.repository, runtime.gateway.counters
        if not isinstance(repository, TableRepository) or not isinstance(counters, RedisCounters):
            raise ValueError("Demo deployment requires persistent Table Storage and Redis")
        await require_empty_stores(repository, counters)
        await seed_data(runtime.gateway, data, tenant_id)
        # Verify the same read path the portal uses, including live monthly counter projections.
        history = await runtime.gateway.reports.usage(tenant_id, "", admin=True)
        if len(history) != len(data["collections"]["usage"]):
            raise RuntimeError("Demo usage history verification failed")
        await runtime.gateway.reports.budget_status(tenant_id, "", admin=True)
    finally:
        await runtime.close()


def main() -> None:
    """Preview without connections; require explicit opt-in before opening persistent stores."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--data", type=Path, default=DATA_FILE)
    parser.add_argument("--settings-file", type=Path, default=Path("demo/.env"))
    parser.add_argument("--principal-map", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-isolated-stores", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.confirm_isolated_stores:
        parser.error("--apply requires --confirm-isolated-stores and stopped application writers")
    principal_map = json.loads(args.principal_map.read_text()) if args.principal_map else {}
    if not isinstance(principal_map, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in principal_map.items()
    ):
        raise ValueError("Principal mapping must be a JSON object of string identifiers")
    data = load_data(args.data, args.tenant_id, principal_map)
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "tenant_id": args.tenant_id,
                    "configuration": {key: data["collections"][key] for key in COLLECTIONS},
                    "usage": data["collections"]["usage"],
                    "notice": "No stores opened. Prices and usage are fictional.",
                }
            )
        )
        return
    if not args.settings_file.is_file():
        raise ValueError("Provide an explicit demo settings file before applying data")
    values = DotEnvSettingsSource(DemoSettings, env_file=args.settings_file)()
    settings = DemoSettings(
        **{
            **values,
            "event_hub_fqdn": "",
            "event_hub_name": "",
            "telemetry_enabled": False,
        }
    )
    if not settings.local_store_enabled and settings.azure_tenant_id != args.tenant_id:
        raise ValueError("--tenant-id must match AZURE_TENANT_ID for Azure stores")
    asyncio.run(apply_data(data, args.tenant_id, settings))
    print(json.dumps({"mode": "applied", "tenant_id": args.tenant_id, "status": "verified"}))


if __name__ == "__main__":
    main()
