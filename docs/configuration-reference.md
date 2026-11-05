# Configuration reference

## Backend runtime

Python configuration is centralized in `src/apim_rate_limit_foundry/config.py`.
Settings load environment variables and a local `.env`; Terraform supplies deployed settings.

| Variable | Meaning |
| --- | --- |
| `AZURE_CLOUD` | Backend value `commercial` or `government` (not the azd cloud display name) |
| `AZURE_TENANT_ID` | Accepted Entra tenant |
| `AZURE_CLIENT_ID` | User-assigned managed identity client ID |
| `TABLE_ENDPOINT` | Cloud-specific Storage Table account URL |
| `TABLE_NAME` | Durable ledger/config table; default `RateLimiter` |
| `REDIS_HOST`, `REDIS_PORT` | Redis endpoint/TLS port |
| `REDIS_USERNAME` | Managed identity object/principal ID for Redis Entra auth |
| `REDIS_TOKEN_SCOPE` | Verified Redis scope; explicitly required for Government |
| `WEBSITE_AUTH_ENABLED` | Must be `true` in Azure, with platform auth requiring authentication |
| `LOCAL_AUTH_ENABLED` | Explicit local identity headers, forbidden in Azure |
| `LOCAL_STORE_ENABLED` | Explicit local test stores, forbidden in Azure |
| `LOCAL_REDIS_URL`, `LOCAL_TABLE_CONNECTION_STRING` | Optional real local stores; set both together with local stores enabled, forbidden in Azure |
| `PORT` | Loopback development API port; default 8000, not the Functions host port |
| `MAX_INPUT_TOKENS`, `MAX_OUTPUT_TOKENS` | Admission bounds, default 131072 / 32768 |
| `MAX_PAGES`, `MAX_TEXT_RECORDS` | Service-unit bounds, default 2000 / 1000 |

APIM must impose compatible or tighter actual request bounds. Setting a maximum in the Function
does not magically count an arbitrary binary document or constrain an unbounded model request.
Use supported gateway operations and do not trust caller-supplied usage or identity headers.

## API contracts

All routes have the `/api` prefix. Reserve/settle/release and operation binding/checking require
`RateLimit.Gateway`. Configuration writes and recovery require `RateLimit.Admin`. Read routes
allow `RateLimit.Admin` or `RateLimit.Reader`, with server-side consumer scoping.

| Route | Purpose |
| --- | --- |
| `GET /health` | Basic process/cloud health, not proof of initialized counter readiness |
| `POST /decisions/reserve` | Admit and reserve all matching limits atomically |
| `POST /decisions/settle` | Finalize actual or conservative service usage |
| `POST /decisions/release` | Conservatively finalize; not an unconditional refund API |
| `POST /operations/bind`, `/operations/check` | Bind/check asynchronous document operation ownership |
| `POST /reconciliation/recover` | Protected cold initialization/cache recovery |
| `GET /policies`, `/prices`, `/assignments` | Configuration collections |
| `PUT /policies/{id}`, `/prices/{id}`, `/assignments/{id}` | Save validated config with audit |
| `DELETE /{collection}/{id}` | Delete configuration with audit |
| `GET /usage`, `/audit`, `/reconciliation` | Scoped durable event records |

See `/docs` in the local API for executable schema. Policies support optional `tenant_id` scoping;
assignments require both tenant and principal IDs. Returned event records contain `id`, `kind`,
`tenant_id`, `principal_id`, `timestamp`, and nested `data`. They are not Azure invoice records.

`limit` for cost policies is integer **micro-USD** (`1000000` = `$1`). Token/requests/page/record
policies use integer units. Prices are decimal USD **strings**, with token prices per million and
other prices per unit. Specify explicit zero for uncharged dimensions rather than leaving a
billable dimension unknown.

Reservations snapshot price data so in-flight settlement does not change after a catalog edit.
If multiple price versions exist for the same service/model, pass an explicit `price_version`
in the trusted reserve request; ambiguous pricing fails closed.

Decision responses include matched and blocking policy IDs. Denials calculate `Retry-After`
from the blocking windows, not an unrelated shorter rule. Counter keys include metric and period,
so changing either starts a distinct allowance namespace; size-only edits preserve consumption.
Configuration audit events retain validated record snapshots and the actor.

## Cloud selection

azd/CLI use `AzureCloud` or `AzureUSGovernment`. The backend uses `commercial` or `government`;
Terraform maps deployment cloud choice to runtime settings and provider environments.
Cloud-specific endpoints come from resource outputs/configuration, not hostname string replacement.

Private deployments require operator-supplied existing subnet IDs and policy-managed DNS.
Only explicitly selected public development mode should enable public service access.
Review `infra/main.tfvars.json` for all required sizing/network/service inputs and
`infra/provider.conf.json` for remote-state placeholders.

## Seed helper

| Variable | Meaning |
| --- | --- |
| `SEED_API_URL` | API base including `/api`; default loopback port 8000 |
| `SEED_ACCESS_TOKEN` | Administrator access token for a deployed HTTPS API |
| `SEED_LOCAL_AUTH` | Loopback-only test admin headers, never allowed for deployed endpoints |

Seed writes require the explicit `--apply` flag. Do not copy example prices to production.
