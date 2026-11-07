# Local development

## Setup

Use Node.js 24 LTS for the portal, matching the App Service runtime.

```bash
uv sync --extra dev
npm --prefix web ci
cp .env.example .env
code apim-rate-limit-foundry.code-workspace
```

The example `.env` deliberately enables **loopback-only local authentication and in-memory
storage**. It is not a production configuration. Azure runtime detection rejects either bypass
flag in an Azure-hosted process.

```bash
uv run apim-rate-limit-foundry
```

The API listens on `http://127.0.0.1:8000`; set `PORT` to change it.
Health is `/api/health`, API docs `/docs`.
To initialize illustrative price cards/rules:

```bash
uv run python scripts/seed.py          # dry run, no writes
uv run python scripts/seed.py --apply  # explicit local configuration writes
```

The seed tool uses `SEED_LOCAL_AUTH=true` only against loopback HTTP. Deployed APIs require
`SEED_ACCESS_TOKEN` containing an administrator **access token**, not an ID token. The supplied
prices are invented examples, never current Azure pricing.
For `SEED_API_URL=https://<gateway>/portal`, also supply the portal product's
`SEED_APIM_SUBSCRIPTION_KEY` through the process environment. Never save a real
key in the browser's public configuration, `.env.example` or a transcript.

Local identity headers are required even with the bypass enabled:

```text
X-Local-Tenant-Id: local-tenant
X-Local-Principal-Id: local-admin
X-Local-Roles: RateLimit.Admin
```

Use `RateLimit.Gateway` for reserve/settle calls and `RateLimit.Reader` for scoped consumer views.
Never configure a reverse proxy to expose this local server or turn on local identity handling
in a cloud deployment.

## Frontend

```bash
WEB_DEMO_MODE=true npm --prefix web run dev
```

Use the portal's documented runtime configuration in `web/` for Entra authentication and the API
base URL. Any explicit demo mode is separate from the live Function API, with a visible demo
banner; authentication/network failures must not silently switch to demo data.
The credential-free GUI demo does not edit the local CLI's stores. Live GUI/API integration uses
the configured Entra-protected gateway and its exact-origin CORS policy; local identity headers
are for direct API smoke tests, not a browser authentication scheme.
See [portal screens and contracts](../web/README.md#screens-and-server-contracts)
and the [code guide](code-guide.md) for the UI/backend boundary.

## Functions host

The root `function_app.py` exposes the ASGI API and a five-minute reconciliation timer.
`host.json` sets an empty route prefix because API paths already contain `/api`.
Install Azure Functions Core Tools v4 separately when testing host behavior.

Export the environment values in your terminal or create an untracked `local.settings.json`
with the Functions-required `Values` dictionary. The local FastAPI CLI reads `.env`; Core Tools
does not automatically translate `.env` into host settings.

```bash
FUNCTIONS_WORKER_RUNTIME=python AzureWebJobsStorage=UseDevelopmentStorage=true uv run func start
```

The timer needs host storage (Azurite or an explicitly configured storage account).
Core Tools' loopback `WEBSITE_HOSTNAME` is supported; actual Azure site/instance markers still
prohibit local authentication or storage bypasses.
For debugging the Python worker, start Core Tools with the worker's debugpy listen argument and
use the VS Code **Functions: attach Python worker** configuration on port 9091.

## Dedicated streaming host

The streaming app is a separate host, not another route to add to the root ASGI
Function. Configure its untracked `stream/local.settings.json` or exported
environment independently, using [runtime settings](configuration-reference.md#backend-runtime).
Do not assume the root `.env` is translated or inherited by Core Tools.

```bash
PYTHON_ENABLE_INIT_INDEXING=1 \
uv run func start --script-root stream --port 7072
```

VS Code's `run-stream` task starts the same separate host. The stream attach
configuration uses debug port 9092 when Core Tools is launched with matching
Python worker debug arguments; the HTTP port is 7072.

Successful inference needs an admitted, body-bound reservation, fixed
`MODEL_REGISTRY` (or legacy `STREAM_BACKENDS`), real Table/Redis and an Azure credential authorized to call
the provider. In-memory local mode deliberately has no such credential and the
stream entry point returns 503 rather than fake model output. Use deterministic
[`test_streaming.py`](../tests/test_streaming.py) fixtures to validate transport
and usage parsing without Azure inference charges. Actual local auth headers are
still loopback-only; do not expose this development host.
See the [local model registry example](model-registry.md#local-configuration-example)
for multi-model discovery without live inference.

## Tests and checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest -W error
uv run pytest --cov --cov-report=xml --cov-report=term-missing
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
terraform -chdir=infra test
tflint --chdir=infra --recursive
uv run python -W error -m unittest discover -s apim/tests -v
```

Real Redis/Table tests are optional locally and mandatory in CI:

```bash
docker compose up -d redis azurite
TEST_REDIS_URL=redis://127.0.0.1:6379/5 \
TEST_TABLE_CONNECTION_STRING=UseDevelopmentStorage=true TEST_AZURITE=true \
uv run pytest -W error
```

The compose ports bind only to loopback. `redis` is a third-party image because Microsoft does
not distribute a suitable local Redis engine; Microsoft's Azurite emulates Storage.
The tests use isolated key namespaces and deterministic fake Azure dependencies, not cloud
credentials. Never point them at production Redis.

## Persistent local application

The same running services can back the application rather than its in-memory test doubles.
Set both optional settings in `.env`:

```text
LOCAL_REDIS_URL=redis://127.0.0.1:6379/0
LOCAL_TABLE_CONNECTION_STRING=UseDevelopmentStorage=true
```

Create the local table once, then start the API and apply the seed configuration:

```bash
uv run python - <<'PY'
from azure.data.tables import TableServiceClient

with TableServiceClient.from_connection_string("UseDevelopmentStorage=true") as service:
    service.create_table_if_not_exists("RateLimiter")
PY
uv run apim-rate-limit-foundry
# In a second terminal:
uv run python scripts/seed.py --apply
curl --fail-with-body -X POST http://127.0.0.1:8000/api/reconciliation/recover \
  -H 'X-Local-Tenant-Id: local-tenant' \
  -H 'X-Local-Principal-Id: local-admin' \
  -H 'X-Local-Roles: RateLimit.Admin'
```

Recovery initializes the guarded Redis ledger and rebuilds it after cache loss; it does not
erase durable consumption. Redis and Azurite must remain running. Local connection strings and
identity headers are deliberately prohibited in Azure.

## Automation

VS Code provides `setup`, `build`, `run-api`, `run-functions`, `web:dev`, `test`, `test-strict`,
`coverage`, `lint`, `format`, `type-check`, frontend checks, and infrastructure checks.
The workspace delegates to `.vscode/tasks.json` rather than duplicating task logic.
`build` includes Python packaging, the separate stream wheel/export and portal
build. Source requirements and architecture entry points are mapped in the
[code guide](code-guide.md#three-runnable-services).

Install optional pre-commit hooks with:

```bash
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type pre-push
uv run pre-commit run --all-files
```

Terraform hooks require initialized providers and tflint. All tests must remain warning-free.
