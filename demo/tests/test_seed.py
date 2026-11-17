import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables.aio import TableClient
from redis.asyncio import Redis

from apim_rate_limit_foundry.accounting import digest, usage_partition, utc_month
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.engine import USAGE_COLLECTION, GatewayServices
from apim_rate_limit_foundry.engine.keys import opaque
from apim_rate_limit_foundry.stores.memory import MemoryCounters, MemoryRepository
from apim_rate_limit_foundry.stores.redis import RedisCounters
from apim_rate_limit_foundry.stores.table import TableRepository
from demo import seed


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        local_store_enabled=True,
        local_redis_url=None,
        local_table_connection_string=None,
        model_registry=json.loads(Path("examples/model-registry.json").read_text()),
    )


def test_preview_never_opens_stores_or_settings(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["seed", "--tenant-id", "local-tenant"])
    runtime = Mock(side_effect=AssertionError("Must not open stores"))
    monkeypatch.setattr(seed, "Runtime", runtime)
    monkeypatch.setattr(
        seed, "DemoSettings", Mock(side_effect=AssertionError("Must not load settings"))
    )

    seed.main()

    preview = json.loads(capsys.readouterr().out)
    assert preview["mode"] == "dry_run"
    assert len(preview["configuration"]["assignments"]) == 7
    runtime.assert_not_called()


def test_apply_requires_explicit_isolation_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["seed", "--tenant-id", "local-tenant", "--apply"])
    runtime = Mock()
    monkeypatch.setattr(seed, "Runtime", runtime)

    with pytest.raises(SystemExit) as error:
        seed.main()

    assert error.value.code == 2
    runtime.assert_not_called()


def test_apply_requires_its_own_settings_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed",
            "--tenant-id",
            "local-tenant",
            "--apply",
            "--confirm-isolated-stores",
            "--settings-file",
            str(tmp_path / "missing.env"),
        ],
    )
    runtime = Mock()
    monkeypatch.setattr(seed, "Runtime", runtime)

    with pytest.raises(ValueError, match="explicit demo settings file"):
        seed.main()

    runtime.assert_not_called()


def test_demo_settings_do_not_load_the_application_env(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AZURE_CLOUD", raising=False)
    (tmp_path / ".env").write_text("AZURE_CLOUD=unsupported\n")
    deployment = tmp_path / "demo.env"
    deployment.write_text("TABLE_NAME=OfficeTest\n")
    values = seed.DotEnvSettingsSource(seed.DemoSettings, env_file=deployment)()

    settings = seed.DemoSettings(**values)

    assert settings.azure_cloud == "commercial"
    assert settings.table_name == "OfficeTest"


async def test_apply_uses_separate_settings_and_disables_synthetic_exports(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed",
            "--tenant-id",
            "local-tenant",
            "--apply",
            "--confirm-isolated-stores",
            "--settings-file",
            "demo/.env.example",
        ],
    )
    apply = AsyncMock()
    pending = []
    monkeypatch.setattr(seed, "asyncio", SimpleNamespace(run=pending.append))
    monkeypatch.setattr(seed, "apply_data", apply)
    monkeypatch.setenv("EVENT_HUB_FQDN", "unused.example")
    monkeypatch.setenv("EVENT_HUB_NAME", "unused")

    seed.main()
    await pending[0]

    apply.assert_awaited_once()
    settings = apply.await_args.args[2]
    assert settings.event_hub_fqdn == settings.event_hub_name == ""
    assert settings.telemetry_enabled is False
    assert json.loads(capsys.readouterr().out)["status"] == "verified"


async def test_seed_uses_real_pricing_history_and_counter_paths(settings: Settings) -> None:
    repository, counters = MemoryRepository(), MemoryCounters(settings)
    gateway = GatewayServices.create(repository, counters, settings)
    tenant = "tenant-1"
    mapped_principal = "11111111-1111-1111-1111-111111111111"
    data = seed.load_data(seed.DATA_FILE, tenant, {"jim-halpert": mapped_principal})
    try:
        await seed.seed_data(gateway, data, tenant)

        history = await gateway.reports.usage(tenant, "", admin=True)
        assert len(history) == 2
        actual = next(row for row in history if row["status"] == "actual")
        unknown = next(row for row in history if row["status"] == "usage_unknown")
        assert actual["cost_micro_usd"] == 5424
        assert actual["user_ref"] == opaque(tenant, mapped_principal)
        assert unknown["cost_micro_usd"] == 66432
        assert unknown["cost_basis"] == "estimated_upper_bound"
        assert unknown["input_tokens"] is None
        for event, principal in ((actual, mapped_principal), (unknown, "angela-martin")):
            keys = [
                digest(tenant, kind, subject, event["month"], model)
                for kind, subject in (
                    ("user", principal),
                    ("team", event["team_id"]),
                    ("department", event["department_id"]),
                )
                for model in ("*", event["model"])
            ]
            assert await counters.totals(event["month"], keys) == {
                key: event["cost_micro_usd"] for key in keys
            }
        budgets = await gateway.reports.budget_status(tenant, "", admin=True)
        assert {row["spent_micro_usd"] for row in budgets} == {5424}
        assert (
            next(row for row in budgets if row["subject_type"] == "user")["subject_id"]
            == mapped_principal
        )
        chargeback = await gateway.reports.chargeback(tenant, utc_month()[0], None)
        assert sum(row["cost_micro_usd"] for row in chargeback) == 71856
        assert sum(row["unknown_requests"] for row in chargeback) == 1
        assert (
            len(await repository.list(USAGE_COLLECTION, usage_partition(tenant, utc_month()[0])))
            == 2
        )
        assert all(row["tenant_id"] == tenant for row in await repository.list("assignments"))
        user_history = await gateway.reports.usage(tenant, mapped_principal, admin=False)
        assert user_history == [actual]
    finally:
        await gateway.close()


@pytest.mark.parametrize(
    "mapping", [{"unknown-user": "object-id"}, {"jim-halpert": "dwight-schrute"}]
)
def test_invalid_principal_mapping_is_rejected(mapping: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="Principal mapping"):
        seed.load_data(seed.DATA_FILE, "tenant-1", mapping)


@pytest.mark.parametrize("redis_size,table_has_rows", [(1, False), (0, True), (0, False)])
async def test_empty_store_guard_prevents_repeat_or_shared_store_writes(
    settings: Settings, redis_size: int, table_has_rows: bool
) -> None:
    table = MagicMock(spec=TableClient)
    table.create_table = AsyncMock()

    async def entities():
        if table_has_rows:
            yield {"PartitionKey": "existing"}

    table.list_entities.return_value = entities()
    client = MagicMock(spec=Redis)
    client.dbsize = AsyncMock(return_value=redis_size)
    repository = TableRepository(table)
    counters = RedisCounters(settings, None, client)
    if redis_size or table_has_rows:
        with pytest.raises(ValueError, match="non-empty"):
            await seed.require_empty_stores(repository, counters)
    else:
        await seed.require_empty_stores(repository, counters)
    table.create_table.assert_not_awaited()
    table.submit_transaction.assert_not_called()
    if redis_size:
        table.list_entities.assert_not_called()


async def test_guard_creates_missing_table_only_after_empty_redis_check(settings: Settings) -> None:
    table = MagicMock(spec=TableClient)
    table.create_table = AsyncMock()

    async def missing_table():
        raise ResourceNotFoundError("missing")
        yield  # pragma: no cover

    table.list_entities.return_value = missing_table()
    client = MagicMock(spec=Redis)
    client.dbsize = AsyncMock(return_value=0)

    await seed.require_empty_stores(TableRepository(table), RedisCounters(settings, None, client))

    table.create_table.assert_awaited_once()


async def test_memory_only_settings_cannot_be_applied(settings: Settings, monkeypatch) -> None:
    runtime = Mock(side_effect=AssertionError("Must not open stores"))
    monkeypatch.setattr(seed, "Runtime", runtime)
    data = seed.load_data(seed.DATA_FILE, "tenant-1", {})

    with pytest.raises(ValueError, match="requires persistent"):
        await seed.apply_data(data, "tenant-1", settings)

    runtime.assert_not_called()


async def test_invalid_seed_is_rehearsed_before_any_persistent_connection(
    settings: Settings, monkeypatch
) -> None:
    runtime = Mock(side_effect=AssertionError("Must not open stores"))
    monkeypatch.setattr(seed, "Runtime", runtime)
    data = seed.load_data(seed.DATA_FILE, "tenant-1", {})
    data["collections"]["usage"][0]["model"] = "unregistered-model"
    settings = settings.model_copy(
        update={
            "local_redis_url": "redis://127.0.0.1:6379/0",
            "local_table_connection_string": "unused-by-rehearsal",
        }
    )

    with pytest.raises(ValueError, match="Unknown model"):
        await seed.apply_data(data, "tenant-1", settings)

    runtime.assert_not_called()
