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
| `GET /usage/summary?period=hour\|day` | Scoped UTC admission-time usage/cost summaries; default day |

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

### LLM protocol and caching contract

`Reserve.api_protocol` accepts `openai-chat`, `openai-responses`, or `anthropic-messages`.
An omitted protocol on an existing Foundry reservation retains Chat Completions behavior.
All three use `service: "foundry"`; policies remain model/service/principal scoped. The gateway
selects the protocol from its operation, not a client-supplied accounting header.

`Settle` accepts the existing normalized `usage`, or `provider_usage` containing only the backend
usage object. Do not send both. The Function derives the provider schema from the reservation,
not the settlement caller. Document Intelligence and Language keep their normalized unit contract.

Normalized `input_tokens` includes uncached input, cached reads and cache writes.
`cached_input_tokens` is reads; `cache_write_input_tokens_5m` / `cache_write_input_tokens_1h`
are write subsets. All three subsets together must fit within total input.
Anthropic's raw `input_tokens` excludes these cache categories, unlike OpenAI's input totals.

Price cards add `cache_write_5m_per_million` and `cache_write_1h_per_million` (decimal USD strings).
They may be absent/null for legacy OpenAI cards; null means **unknown**, never free. Anthropic
admission requires prices sufficient to reserve the worst possible relevant input category.
The Fluent editor exposes reads and both write TTLs separately. `examples/prices.json` contains
invented examples for both OpenAI and Anthropic, not contractual provider rates.

Decision responses include matched and blocking policy IDs. Denials calculate `Retry-After`
from the blocking windows, not an unrelated shorter rule. Counter keys include metric and period,
so changing either starts a distinct allowance namespace; size-only edits preserve consumption.
Configuration audit events retain validated record snapshots and the actor.

Summaries count each admitted request once even when several cost policies apply. Later actual
settlement replaces the conservative contribution. They are derived from durable events on read,
not separately materialized or invoiced charges; summary scans share the sample's retention and
partition-scaling limitations. The portal's existing tables continue to show per-event records.

## Cloud selection

azd/CLI use `AzureCloud` or `AzureUSGovernment`. The backend uses `commercial` or `government`;
Terraform maps deployment cloud choice to runtime settings and provider environments.
Cloud-specific endpoints come from resource outputs/configuration, not hostname string replacement.
The [Tables SDK audience](https://learn.microsoft.com/python/api/azure-data-tables/azure.data.tables.tableclient)
is `https://storage.azure.com` for Commercial and `https://storage.azure.us` for Government.
Redis audiences remain a separately verified deployment input; do not infer one from a DNS suffix.

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
