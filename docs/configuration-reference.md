# Configuration reference

For an example of configuring multiple rules and following the resulting debits,
see the [rate-limiting walkthrough](rate-limiting-walkthrough.md). The
[architecture diagrams](../ARCHITECTURE.md) show how these contracts fit together.

## Backend runtime

Python configuration is centralized in [`config.py`](../src/apim_rate_limit_foundry/config.py).
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
| `MODEL_REGISTRY` | Both Function hosts: JSON allowlist keyed by protocol and alias; see [model registry](model-registry.md) |
| `APPLICATION_REGISTRY` | Both Function hosts: JSON map of stable APIM subscription IDs to `{tenant_id, display_name}`; Terraform generates it from inference applications, never secret keys |
| `STREAM_BACKENDS` | Legacy streaming fallback only when the registry is empty: JSON map keyed by protocol, with fixed HTTPS endpoint/audience, path, model and provider versions |
| `STREAM_MAX_EVENT_BYTES` | Maximum retained SSE event bytes; default 65536, runtime range 8192–1048576 |
| `STREAM_MAX_BODY_BYTES` | Streaming body cap, aligned with the gateway request cap |
| `STREAM_TIMEOUT_SECONDS` | Upstream timeout; default 180, runtime range 10–210 seconds |
| `TELEMETRY_ENABLED`, `OTEL_SERVICE_NAME` | SDK export switch and role name (`rate-limiter` or `rate-limiter-stream`) |
| `OTEL_TRACES_SAMPLER_ARG` | Backend trace sampling ratio; default 1 |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional configured telemetry destination; see the observability/privacy guides |
| `AZURE_DASHBOARD_ID` | Fixed deployed dashboard ARM ID for the Admin-only in-app charts |
| `LOG_ANALYTICS_WORKSPACE_ID` | Workspace customer UUID used by the server's Azure Monitor Logs SDK |
| `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` | Workspace ARM scope; every native dashboard tile must match it |

APIM must impose compatible or tighter actual request bounds. Setting a maximum in the Function
does not magically count an arbitrary binary document or constrain an unbounded model request.
Use supported gateway operations and do not trust caller-supplied usage or identity headers.
The [infrastructure reference](../infra/README.md#dedicated-streaming-host) explains
why custom stream limits must satisfy Python's narrower bounds as well as Terraform.

## API contracts

All control-plane routes below have the `/api` prefix. Reserve/settle/release and operation binding/checking require
`RateLimit.Gateway`. Configuration writes and recovery require `RateLimit.Admin`. Read routes
allow `RateLimit.Admin` or `RateLimit.Reader`, with server-side consumer scoping.
The workspace-wide dashboard endpoint is an exception: it requires Admin.

| Route | Purpose |
| --- | --- |
| `GET /models` | Admin/Reader read-only model inventory; excludes endpoints and audiences |
| `GET /subscriptions` | Admin/explicitly assigned Reader application metadata: `id`, `tenant_id`, `display_name`; never keys |
| `GET /health` | Basic process/cloud health; platform authentication in Azure, no application-role check or readiness proof |
| `GET /dashboard?period=1h\|24h\|7d` | Admin-only native dashboard charts/grids; default 24h, no client KQL, workspace or URL parameters |
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
| `GET /usage/callers?period=hour\|day` | Authorized caller/service/model/protocol/streaming attribution; default day |

The separate streaming host exposes `POST /api/stream` to Gateway-role callers only.
It is not a consumer-facing ingestion API. APIM supplies the admitted reservation ID and
the exact pinned body whose `Reserve.payload_sha256` was recorded before dispatch.
Client-supplied identity, reservation or usage headers do not establish trust.

See `/docs` and `/openapi.json` in the local FastAPI server for executable schema.
They are not published as catch-all APIM portal operations.
The [API implementation](../src/apim_rate_limit_foundry/api.py) independently enforces roles.
See [identity boundaries](azure-topology.md#identity-and-token-boundaries) for audiences,
allowed clients and the difference between app roles and Azure RBAC.

### Configuration and response shapes

Collection GETs return JSON arrays, not `{items: [...]}`. PUT sends the complete
record with an ID matching the path. The current backend DELETE returns
`{deleted: id}`; the portal also tolerates a 204 response from compatible backends.

| Record | Fields and authoritative validation |
| --- | --- |
| Policy | `id`, `name`, `service`, `model`, `tenant_id`, required `subscription_id`, `limit`, `period`, `metric`, `enabled`, `priority`; [model](../src/apim_rate_limit_foundry/models/policy.py) |
| Price | `id`, `service`, `model`, `version`, `input_per_million`, `output_per_million`, `cached_input_per_million`, `cache_write_5m_per_million`, `cache_write_1h_per_million`, `per_page`, `per_text_record`, `per_request`; [model](../src/apim_rate_limit_foundry/models/price.py) |
| Assignment | `id`, `tenant_id`, `subscription_id`, `policy_ids`, `reader_principal_ids`, optional `display_label` (max 128 characters); [model](../src/apim_rate_limit_foundry/models/assignment.py) |
| Event envelope | `id`, `kind`, `tenant_id`, `principal_id`, `timestamp`, nested `data`; usage/audit/reconciliation history, not invoice records |

Services are `foundry`, `document-intelligence`, `language`. Metrics are `cost`,
`tokens`, `requests`, `pages`, `text_records`; the portal offers service-appropriate
choices. Policy amounts are strict nonnegative integers up to 9,000,000,000,000
in the backend; the portal editor asks for positive limits. Identifiers, decimal
types and additional restrictions are defined in
[`types.py`](../src/apim_rate_limit_foundry/models/types.py).

`limit` for cost policies is integer **micro-USD** (`1000000` = `$1`). Token/requests/page/record
policies use integer units. Prices are decimal USD **strings**, with token prices per million and
other prices per unit. Specify explicit zero for uncharged dimensions rather than leaving a
billable dimension unknown.

Reservations snapshot price data so in-flight settlement does not change after a catalog edit.
If multiple price versions exist for the same service/model, pass an explicit `price_version`
in the trusted reserve request; ambiguous pricing fails closed.
Backend rate fields may be omitted/null to mean unknown; this does not establish
permission to admit a request needing that rate. Portal form requirements may be
stricter. Explicit `"0"` is distinct from unknown.

### Example: save and read a budget policy

Run only in an approved test environment. Set `APIM_GATEWAY_URL` to the gateway
origin, `API_SCOPE` to the limiter's delegated API scope, and `TENANT_ID` /
`APPLICATION_SUBSCRIPTION_ID` to the intended application. Supply the separate
portal product key as `PORTAL_SUBSCRIPTION_KEY`, never an inference key. Use a new policy ID and a
real configured model alias; this write affects subsequent matching requests.
The price catalog and gateway price-version pin must already agree.

```bash
# Requires an approved Azure CLI session with RateLimit.Admin; keep shell tracing off.
ADMIN_ACCESS_TOKEN="$(az account get-access-token \
  --scope "$API_SCOPE" --query accessToken --output tsv)"

curl --fail-with-body --silent --show-error --request PUT \
  "$APIM_GATEWAY_URL/portal/policies/example-model-budget" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Ocp-Apim-Subscription-Key: $PORTAL_SUBSCRIPTION_KEY" \
  -H "Content-Type: application/json" \
  --data @- <<JSON
{
  "id": "example-model-budget",
  "name": "Illustrative model monthly budget",
  "service": "foundry",
  "model": "gpt-5.4-mini",
  "tenant_id": "$TENANT_ID",
  "subscription_id": "$APPLICATION_SUBSCRIPTION_ID",
  "metric": "cost",
  "limit": 1000000,
  "period": "month",
  "enabled": true,
  "priority": 10
}
JSON

curl --fail-with-body --silent --show-error \
  "$APIM_GATEWAY_URL/portal/policies" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Ocp-Apim-Subscription-Key: $PORTAL_SUBSCRIPTION_KEY"
unset ADMIN_ACCESS_TOKEN
```

Verify the saved record, not just HTTP success. Do not reuse this admin token
for inference or reserve/settle. To undo a disposable test, delete only its new
policy through the portal; deleting it does not erase historical consumption.

### Policy selection and counter scope

All matching enabled policies apply. Priority determines evaluation order, not
override behavior. Selectors are service, model, tenant and subscription; model,
tenant and subscription may be `*`. An explicit wildcard is a reusable template,
not a shared allowance across applications. Protocol, APIM operation and product
are not independent policy selectors. All LLM protocols use `service=foundry`.

Once any assignment references a policy, that policy applies only to assigned
tenant/subscription pairs that also satisfy its own selectors. Unassigned policies
apply to all matching callers. An assignment never broadens the policy selectors.

Counter identity includes policy ID + metric + period + tenant + subscription +
UTC window start. Thus a wildcard subscription gives each application a separate
allowance; a wildcard model can pool that application's models. A signed-in
principal is actor metadata only. Periods are fixed UTC calendar
minute/hour/day/month, not sliding windows.

Limit-only edits preserve consumption. Changing policy ID, metric or period starts
a different counter namespace; disabling/deleting does not refund history or
rewrite in-flight snapshots. See [`matching()` and `debits()`](../src/apim_rate_limit_foundry/accounting.py).

Application labels come from registered subscription metadata or explicitly
configured assignment labels. They never change identity and have no Graph/user
fallback. Reader access requires the signed-in principal in
`reader_principal_ids` for that tenant/application; a shared Entra identity or
an empty reader list does not grant app visibility. The caller reference is defined in
[observability](observability.md#resolve-a-caller-without-logging-names).

### LLM protocol and caching contract

`Reserve.api_protocol` accepts `openai-chat`, `openai-responses`, or `anthropic-messages`.
Registered requests select the protocol/alias entry and its pinned price version;
the alias is the accounting model, not necessarily the provider deployment.
An omitted protocol on an existing Foundry reservation retains Chat Completions behavior.
All three use `service: "foundry"`; policies remain model/service/subscription scoped. The gateway
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

Incomplete provider metadata returns an estimated `settlement_pending` reconciliation record
without finalizing or refunding the reservation. A corrected trusted usage report can settle
later, including after Redis recovery. Malformed counts/TTL totals reject with `400`/`422`.
Standard text inference is the priced baseline; unknown billing dimensions, provider-executed
tools, nonstandard tiers and unconfigured geography pricing do not become zero-cost usage.

Decision responses include matched and blocking policy IDs. Denials calculate `Retry-After`
from the blocking windows, not an unrelated shorter rule.
Configuration audit events retain validated record snapshots and the actor.

Summaries count each admitted request once even when several cost policies apply. Later actual
settlement replaces the conservative contribution. They are derived from durable events on read,
not separately materialized or invoiced charges; summary scans share the sample's retention and
partition-scaling limitations. The `/usage` API overlays available settlements; original durable reservation
records are not mutated by that response projection. See the
[record collection map](code-guide.md#durable-record-collections).

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
