---
title: Isolated demo data
description: Deploy fictional Office-themed records to a dedicated Table Storage and Redis pair.
---

## Separation

This directory owns the fictional data and its optional deployment command.
Nothing imports it from application source, runs it during application startup,
or invokes it from `azd up`. Python packages include only application source;
the root Function package excludes this directory. The web build contains no
demo data, demo adapter, or authentication bypass.

The [dataset](data/office.json) describes Dunder Mifflin's Scranton Sales and
Accounting departments and seven fictional people. Only its organizations,
assignments, prices, budgets and usage inputs are deployed. Model inventory
remains deployment-managed. The identity, spend, chargeback and dashboard
snapshots in the file are used only by frontend unit tests, not written to stores.

The loader uses the normal configuration, admission and usage services.
It recomputes prices, opaque user references, chargeback dimensions and Redis
counter projections instead of trusting precomputed fixture values. Unknown
usage is charged the registered model's pinned upper bound, not zero.
No inference requests are made. Request and usage history are synchronously
verified in Table Storage rather than relying only on background mirrors.

The portal always authenticates normally and reads its usual API. Its displayed
user is the real signed-in account, not a fictional administrator. Azure
dashboard queries remain real telemetry queries; the seed command does not
fabricate Application Insights or Log Analytics data or export synthetic events.

## Local deployment

Use a dedicated Redis instance/database and a new Table name. Stop all application
writers before applying. The command refuses any existing Redis keys or Table
entities, including data from a previous or partially failed seed. It never
flushes Redis, overwrites existing stores, or automatically retries partial work.
After a failure, inspect the error and select fresh isolated stores before
trying again. The two stores are not one atomic transaction.

```bash
uv sync --extra dev
cp demo/.env.example demo/.env
uv run python -m demo.seed --tenant-id local-tenant
```

Preview opens no connections and does not read deployment settings. Review and
edit `demo/.env` separately from the application's `.env`. The example points
at loopback Redis and Azurite with the `OfficeDemo` Table name. Start your isolated
emulators separately, for example with `docker compose up -d` on a fresh local
development environment. The loader creates the table if it does not exist.

```bash
uv run python -m demo.seed --tenant-id local-tenant \
  --settings-file demo/.env --apply --confirm-isolated-stores
```

The command first rehearses the complete dataset in memory using the configured
model registry, before opening persistent connections. After success, configure
the application to use that same Redis instance/database, Table name and model
registry, then start the application. Redis must be dedicated because the app's
operational keys are shared across tenants.

The example model endpoints are placeholders used only for offline accounting;
configure real deployment endpoints before making inference calls. In local API
mode, a sample Reader uses `X-Local-Tenant-Id: local-tenant`,
`X-Local-Principal-Id: jim-halpert` and `X-Local-Roles: RateLimit.Reader`.
Browser sign-in still requires valid Entra and API settings.

## Azure deployment

Provision an isolated non-production storage pair through the normal infrastructure
workflow; this command does not provision infrastructure or modify deployment
hooks. In a separate settings file configure `LOCAL_STORE_ENABLED=false`,
`AZURE_CLOUD`, `AZURE_TENANT_ID`, `TABLE_ENDPOINT`, `TABLE_NAME`, `REDIS_HOST`,
`REDIS_PORT`, `REDIS_USERNAME` and the application's actual `MODEL_REGISTRY`.
Government Redis also requires its explicitly verified `REDIS_TOKEN_SCOPE`.
Do not include local emulator settings.

The command uses the existing Entra credential chain and needs Table data-write
and Redis data-write permissions plus private-network access where configured.
Pass the same tenant as `AZURE_TENANT_ID`. Optionally use `--principal-map` with
a JSON object mapping fictional principal slugs to actual Entra object IDs;
assignment and user-budget references are changed together. Unmapped people
remain fictional; Readers only see data for their actual assigned principal.

```bash
uv run python -m demo.seed --tenant-id <tenant-guid> \
  --settings-file demo/.env --principal-map <mapping-file.json> \
  --apply --confirm-isolated-stores
```

Prices are illustrative, not an authoritative Azure price feed. Request IDs and
usage dates are anchored to the current UTC month. The script does not reset
stores, restore expired counters, or migrate historical financial data.

## Validation

```bash
uv run pytest -W error demo/tests
uv run ruff check demo
uv run mypy demo/seed.py
```

See [local development](../docs/local-development.md) for application setup,
[configuration](../docs/configuration-reference.md) for the deployed record
schemas and [operations](../docs/operations.md) for the accounting-loss contract.
