---
title: Local development
description: Run and validate the gateway locally using explicit authentication and storage settings.
---

## Setup

Use Python 3.12+, `uv`, Node.js 24 LTS, Terraform 1.9+ and
Azure Functions Core Tools v4 (`func`, used by the Function host tasks). Do not use global pip
or install package versions outside the repository manifests.

```bash
uv sync --extra dev
npm --prefix web ci
cp .env.example .env
uv run apim-rate-limit-foundry
```

Local mode must explicitly enable authentication/storage bypasses. On loopback,
send `X-Local-Tenant-Id`, `X-Local-Principal-Id` and `X-Local-Roles` for test actors.
These are not supported deployment credentials and are prohibited in Azure.
The loopback API does not validate delegated bearer JWTs itself; local API tests
must use those explicit test headers.

Optional fictional data and its deployment command live entirely under
[`demo/`](../demo/README.md). Preview with
`uv run python -m demo.seed --tenant-id local-tenant`; follow that guide for
explicit deployment into empty, isolated Table Storage and Redis stores.
Application startup and deployment never seed data. The portal has no demo mode,
bundled fixture data or alternate authentication path.

Configure a model registry before inference. The
[example registry](../examples/model-registry.json) and
[`infra/managed-models.example.json`](../infra/managed-models.example.json)
describe matching model aliases and pinned price versions. Example endpoints
are placeholders, not callable models. Try configured aliases with
[`examples/gateway.http`](../examples/gateway.http).

For persistent local stores, `docker compose up -d` starts Redis/Azurite on
loopback. Set both local endpoint settings in `.env` and create the configured Table.
Configure real organizations and budgets through the administration API or use
the separate optional demo loader before starting application writers.
The first cold check loads the shared configuration
snapshot; warm checks use Redis only. Do not use shared production Redis databases.
Clearing local Redis resets approximate spend and can lose admitted context;
there is no automatic rebuild from Table history.

The API and streaming Functions have separate entry points/hosting modes:
[`function_app.py`](../function_app.py) and
[`stream/function_app.py`](../stream/function_app.py). VS Code's `run-api`,
`run-functions`, `run-stream`, and corresponding debug configurations preserve
that separation. Functions debugger configurations attach to an already
debug-enabled Python worker; running a host task alone does not open the debug
port. Start the appropriate worker with debugging enabled before attaching.

For browser work, follow the [portal setup](../web/README.md) and its
[runtime settings](../web/README.md#required-production-runtime-settings).
The browser sends delegated tokens, not `X-Local-*` headers: setting
`API_BASE_URL` to the loopback API is not enough for authenticated end-to-end
development. Use a reachable backend with the supported authentication boundary
and registered local SPA redirect origin; do not add a browser auth bypass.

## Validation

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -W error
uv run python -W error -m unittest discover -s apim/tests -v
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
terraform -chdir=infra test
```

Terraform validation must have zero warnings as well as zero errors. No unit
test should need paid inference or cloud credentials.

To exercise actual Redis Lua concurrency/idempotency behavior, start an isolated,
disposable Redis instance bound to loopback only, then run:

```bash
TEST_REDIS_URL=redis://127.0.0.1:<port>/0 uv run pytest -W error tests/test_redis.py
```

Replace `<port>` with that instance's local port. Never point these tests at
shared, persistent or deployed Redis: they may change/delete test state.
Stop and discard the isolated instance after testing. Table repository tests
currently use mocked SDK clients; there is no checked-in Azurite integration-test
switch.

See [tasks.json](../.vscode/tasks.json) for grouped validation and
[launch.json](../.vscode/launch.json) for
debuggers. Deployment and live acceptance are separate from local fixture tests.

## Calling the deployed gateway

Inference calls (`/foundry/...`) need an inference-product subscription key plus an
Entra token for the gateway audience. Portal API calls (`/portal/...`) need the
separate portal-product subscription key plus a token for the portal API scope;
an inference key is rejected there with `401`.

Return to the [code guide](code-guide.md) for implementation walkthroughs,
[deployment](deployment.md) for provisioning and
[operations](operations.md#acceptance-checklist) for live acceptance.
