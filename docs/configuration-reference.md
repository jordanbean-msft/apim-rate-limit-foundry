# Configuration and API reference

The backend loads centralized `pydantic-settings` configuration; Terraform supplies
deployed values. `.env.example` contains local-only settings. Never enable local
identity/storage bypasses in Azure.

## Organization and budgets

Collections are JSON arrays on GET. PUT requires a full record whose ID matches
the route. Config edits and their audit records are committed together.
Admin configuration CRUD stays synchronous and durable-first, then invalidates
the shared Redis configuration snapshot. Admission uses that snapshot
(assignments, organizations, prices and budgets), default TTL 60 seconds; a cold
miss may read Table, but warm admission never does.

| Collection | Fields |
| --- | --- |
| `organizations` | `id`, `tenant_id`, `kind` (`team`/`department`), `name`, team `department_id`, `business_unit`, `cost_center`, `enabled` |
| `assignments` | `id`, `tenant_id`, `principal_id`, `team_id`, `department_id`, optional `display_label`, `enabled` |
| `budgets` | `id`, `tenant_id`, `name`, `subject_type` (`user`/`team`/`department`), `subject_id`, `model` (alias or `*`), `limit_micro_usd`, `enabled` |
| `prices` | `id`, `model`, `version`, decimal-string `input_per_million`, `cached_input_per_million`, `output_per_million`, optional decimal-string `cache_write_per_million` (charged at the uncached input rate when absent) |

Users have one enabled assignment; team and department must be enabled in the
same tenant and match the team's parent. Unknown or ambiguous assignments fail
closed. Teams are explicit organizational configuration, not Entra group claims.

Monthly budgets reset at **00:00 UTC on the first of each calendar month**, with
no rollover. `$80 = 80000000 micro-USD`. Zero is a valid blocking limit. Every
matching enabled budget applies. A wildcard model budget pools spend across
models; a model-specific budget is an additional constraint. Budget edits do not
erase previously recorded Redis spend. These are approximate operational budgets:
concurrent requests can overshoot and Redis loss can reset spend. No ledger
rebuild restores lost counters.

## Routes

All routes below are relative to `/api` on the Function. The portal exposes
approved administration/report operations through APIM `/portal`.

| Route | Authorization and purpose |
| --- | --- |
| `GET /health` | Process/cloud status, not financial readiness |
| `POST /budgets/check` | Gateway only; check current spend without debiting |
| `POST /usage/record` | Gateway only; record actual provider usage or explicit unknown |
| `GET /budgets/status` | Admin or scoped Reader; live approximate Redis monthly spent/remaining |
| `GET /usage?month=YYYY-MM` | Admin or scoped Reader; eventually persisted request outcomes for one UTC month (default: current) |
| `GET /chargeback?month=YYYY-MM&format=json\|csv` | Admin or scoped Reader; monthly persisted-history export, potentially incomplete |
| `GET /models` | Approved, redacted OpenAI model inventory |
| `GET /dashboard?period=1h\|24h\|7d` | Admin only; persisted Azure dashboard layout/KQL; `504` when the query deadline passes |
| `GET /{collection}` | Admin-only configuration; Readers use scoped status and usage |
| `PUT /{collection}/{id}`, `DELETE /{collection}/{id}` | Admin only |

Budget checks accept `request_id`, `tenant_id`, `principal_id`, `subscription_id`,
`model`, `api_protocol` (`openai-chat`/`openai-responses`) and `streaming`. APIM
derives identity and request IDs from trusted context, never caller headers.
The response contains `allowed`, `request_id`, `reason`, `denied_budget_ids`,
`reset_at`, `retry_after`. No predicted token count or cost is sent. Any exhausted
budget, including a zero limit, returns `429`. Redis unavailability returns
fail-closed `503`, without a Table fallback.

Usage recording accepts `request_id`, `status` (`actual`/`usage_unknown`) and
provider `provider_usage` for actuals. It returns `{event, replayed}`. The event
is a safe projection for APIM publication, not authority to execute inference
again. Events add `cache_write_tokens`, `cost_basis` (`provider_usage` or
`estimated_upper_bound`) and `out_of_bounds`. Unknown usage (including invalid
counters) keeps null token fields but is charged a conservative upper bound; see
[token accounting](token-accounting.md). On `200`, Redis has accepted the accounting; Table persistence is not
confirmed. Duplicate recording within the 24-hour replay window must not debit or
export twice. Actuals atomically increment all six user/team/department
wildcard/model counters together with the replay marker. Counters are retained
about 62 days; admitted request context and replay markers last 24 hours.

Request/usage history uses a process-local background writer: 256 pending writes,
logged drops/failures and a best-effort two-second graceful-close drain. APIM never
awaits those Table writes. They can be lost on restart, failure or saturation;
there is no durable queue/outbox, retry, or exactly-once guarantee. Live spend and
persisted reports can differ permanently after loss.

The streaming host exposes `POST /api/stream` only to the Gateway workload role;
APIM supplies `X-Usage-Request-ID` and the approved OpenAI payload. An internal
APIM event-logging operation accepts only the configured Function identity.

## Runtime groups

| Settings | Purpose |
| --- | --- |
| `AZURE_CLOUD`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` | Cloud/tenant and workload identity |
| `TABLE_ENDPOINT`, `TABLE_NAME` | Durable configuration/usage destination |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME`, `REDIS_TOKEN_SCOPE` | Live operational configuration, request context, replay markers and spend |
| `CONFIGURATION_CACHE_SECONDS` | Shared configuration snapshot TTL; `configuration_cache_seconds=60` by default |
| `REQUEST_CACHE_SECONDS` | Admitted context and usage replay window; `request_cache_seconds=86400` (24h) by default |
| `MODEL_REGISTRY` | Protocol/alias allowlist with provider path, model and price version |
| `APIM_USAGE_EVENT_URL`, `API_AUDIENCE` | Streaming callback to native APIM Event Hub logger |
| `STREAM_MAX_EVENT_BYTES`, `STREAM_MAX_BODY_BYTES`, `STREAM_TIMEOUT_SECONDS` | Bounded streaming transport; the event bound limits *retained* bytes, larger Responses terminal events are scanned for usage only |
| `DASHBOARD_QUERY_TIMEOUT_SECONDS` | Log Analytics server timeout per dashboard query batch (default 20, 5-120); the client read timeout is this plus 5 s and the overall fetch deadline plus 15 s |
| `AZURE_DASHBOARD_ID`, `LOG_ANALYTICS_WORKSPACE_ID`, `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` | Fixed Admin dashboard query destinations |
| `APPLICATIONINSIGHTS_CONNECTION_STRING`, `TELEMETRY_ENABLED`, `OTEL_SERVICE_NAME` | Operational telemetry |
| `LOCAL_AUTH_ENABLED`, `LOCAL_STORE_ENABLED` | Explicit local-only test mode |
| `LOCAL_REDIS_URL`, `LOCAL_TABLE_CONNECTION_STRING` | Optional real local stores, supplied together |

Use the local `/openapi.json` for executable field constraints. Do not expose a
catch-all proxy that turns the portal into a Gateway-role usage-ingestion client.

Deployment explicitly sets `hosting.configuration_cache_seconds=60` and
`hosting.request_cache_seconds=86400` in `infra/main.tfvars.json`; root Terraform
passes their uppercase environment names to both Function hosts. The Dedicated
budget host now uses `hosting.function_always_on=true` for low-latency hosting;
the streaming host was already Always On. This does not protect pending
process-local background writes from host loss.
