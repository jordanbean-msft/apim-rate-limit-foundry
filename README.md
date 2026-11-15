# APIM monthly AI dollar budgets

An **Azure API Management + Azure OpenAI + Python Azure Functions** sample with
a Microsoft Fluent UI React administration portal. It accounts for actual tokens
after each request and enforces monthly USD budgets for **users, teams and
departments**. Cached input is priced separately from uncached input and output.

**These are approximate operational spending limits.** The gateway checks Redis-recorded spend before
execution, without holding funds. Already-running requests can exceed a budget;
the next request is denied while that spend remains in Redis. Redis data loss can
reset spend. Inference latency takes priority over accounting durability.
Native APIM RPM/TPM protection and provider capacity quotas remain independent of dollars.

Only OpenAI **Chat Completions** and **Responses** are in scope. APIM validates
both Entra authorization and a product subscription key, then routes approved
model aliases through native APIM backend entities. Budgets follow the validated
Entra user, not the subscription key. The subscription identifies the calling
application for attribution. Organizational membership is explicitly configured.

Completed provider usage updates Redis at a pinned price version. Request/usage
Table writes run in a bounded in-process background queue and can be lost.
Live spend and persisted history/chargeback can therefore differ permanently.
APIM publishes the Redis-accepted event with native **`log-to-eventhub`** and
managed identity; neither acceptance nor export proves Table persistence.
The Azure dashboard and the portal share the deployed dashboard's KQL definitions.

## Architecture

```mermaid
flowchart LR
    U[Entra user + application key] --> A[APIM authentication and burst controls]
    A -->|Check all monthly budgets| F[Budget API]
    F -->|Warm admission and actual usage| R[(Redis operational state)]
    F -->|Cold configuration miss only| T[(Table configuration and eventual history)]
    F -.->|Best-effort process-local writer| T
    A --> O[Approved Azure OpenAI backend]
    A --> S[Incremental streaming relay]
    S --> O
    O -->|Provider token totals| F
    F -->|Redis-accepted usage event| A
    A -->|Native log-to-eventhub| E[Event Hub]
    P[Authenticated Fluent portal] --> A
    D[Azure dashboard + shared KQL] --> L[Log Analytics]
```

Redis caches shared configuration for 60 seconds by default, request context and
usage replay markers for 24 hours, and monthly user/team/department wildcard/model
counters for about 62 days. Warm admission never reads Table. Redis unavailability
fails closed with `503`, without Table fallback; exhausted budgets, including zero
limits, return `429`. No automatic ledger rebuild restores lost Redis state.
Admin configuration writes remain synchronous, durable-first and invalidate the
shared cache. See [operations](docs/operations.md) for accepted data-loss limits.

## Documentation

| Concern | Guide |
| --- | --- |
| Responsibilities, accounting and failure behavior | [Architecture](ARCHITECTURE.md) |
| Monthly budgets, organization hierarchy and APIs | [Configuration](docs/configuration-reference.md) |
| Streaming totals and unknown usage | [Token accounting](docs/token-accounting.md) |
| Cost centers and monthly exports | [Chargeback](docs/chargeback.md) |
| Dashboard, telemetry and Event Hub delivery limits | [Observability](docs/observability.md) |
| Runtime identities and networking | [Azure topology](docs/azure-topology.md) |
| Safe cutover from the previous ledger | [Migration](docs/migration.md) |
| Local development, tests and debugging | [Development](docs/local-development.md) |
| Cloud configuration and deployment | [Deployment](docs/deployment.md), [infrastructure](infra/README.md) |
| Entry points and module boundaries | [Code guide](docs/code-guide.md) |
| Approved model aliases | [Model registry](docs/model-registry.md) |
| Gateway and portal details | [APIM](apim/README.md), [portal](web/README.md) |

## Develop

Use Python 3.12+, `uv`, Node.js 24 LTS and Terraform 1.9+.

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src/
uv run pytest -W error
```

The repository includes VS Code tasks and launch configurations. Do not deploy
local authentication bypasses. Deployment uses **azd + Terraform**, an existing
resource group and explicitly selected Azure Commercial or Government endpoints.
Government service availability, private connectivity and GCCH authorization
require independent approval; this sample is not a compliance certification or
an Azure invoice.

Historical plans under `.github/plans/` are execution records, not current
operating instructions. The dollar-budget cutover removes the former monetary
hold/settlement system rather than maintaining two enforcement mechanisms.
