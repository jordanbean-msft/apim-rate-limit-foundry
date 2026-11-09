# Configuration and API reference

The backend loads centralized `pydantic-settings` configuration; Terraform supplies
deployed values. `.env.example` contains local-only settings. Never enable local
identity/storage bypasses in Azure.

## Organization and budgets

Collections are JSON arrays on GET. PUT requires a full record whose ID matches
the route. Config edits and their audit records are committed together.

| Collection | Fields |
| --- | --- |
| `organizations` | `id`, `tenant_id`, `kind` (`team`/`department`), `name`, team `department_id`, `business_unit`, `cost_center`, `enabled` |
| `assignments` | `id`, `tenant_id`, `principal_id`, `team_id`, `department_id`, optional `display_label`, `enabled` |
| `budgets` | `id`, `tenant_id`, `name`, `subject_type` (`user`/`team`/`department`), `subject_id`, `model` (alias or `*`), `limit_micro_usd`, `enabled` |
| `prices` | `id`, `model`, `version`, decimal-string `input_per_million`, `cached_input_per_million`, `output_per_million` |

Users have one enabled assignment; team and department must be enabled in the
same tenant and match the team's parent. Unknown or ambiguous assignments fail
closed. Teams are explicit organizational configuration, not Entra group claims.

Monthly budgets reset at **00:00 UTC on the first of each calendar month**, with
no rollover. `$80 = 80000000 micro-USD`. Zero is a valid blocking limit. Every
matching enabled budget applies. A wildcard model budget pools spend across
models; a model-specific budget is an additional constraint. Budget edits do not
erase previously recorded spend.

## Routes

All routes below are relative to `/api` on the Function. The portal exposes
approved administration/report operations through APIM `/portal`.

| Route | Authorization and purpose |
| --- | --- |
| `GET /health` | Process/cloud status, not financial readiness |
| `POST /budgets/check` | Gateway only; check current spend without debiting |
| `POST /usage/record` | Gateway only; record actual provider usage or explicit unknown |
| `GET /budgets/status` | Admin or scoped Reader; monthly spent/remaining |
| `GET /usage` | Admin or scoped Reader; durable request outcomes |
| `GET /chargeback?month=YYYY-MM&format=json\|csv` | Admin or scoped Reader; monthly ledger-based export |
| `GET /models` | Approved, redacted OpenAI model inventory |
| `GET /dashboard?period=1h\|24h\|7d` | Admin only; persisted Azure dashboard layout/KQL |
| `GET /{collection}` | Admin-only configuration; Readers use scoped status and usage |
| `PUT /{collection}/{id}`, `DELETE /{collection}/{id}` | Admin only |
| `POST /counters/rebuild` | Admin only; rebuild from finalized usage |

Budget checks accept `request_id`, `tenant_id`, `principal_id`, `subscription_id`,
`model`, `api_protocol` (`openai-chat`/`openai-responses`) and `streaming`. APIM
derives identity and request IDs from trusted context, never caller headers.
The response contains `allowed`, `request_id`, `reason`, `denied_budget_ids`,
`reset_at`, `retry_after`. No predicted token count or cost is sent.

Usage recording accepts `request_id`, `status` (`actual`/`usage_unknown`) and
provider `provider_usage` for actuals. It returns `{event, replayed}`. The event
is a safe projection for APIM publication, not authority to execute inference
again. Idempotent duplicate recording must not debit or export twice.

The streaming host exposes `POST /api/stream` only to the Gateway workload role;
APIM supplies `X-Usage-Request-ID` and the approved OpenAI payload. An internal
APIM event-logging operation accepts only the configured Function identity.

## Runtime groups

| Settings | Purpose |
| --- | --- |
| `AZURE_CLOUD`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` | Cloud/tenant and workload identity |
| `TABLE_ENDPOINT`, `TABLE_NAME` | Durable configuration/usage destination |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME`, `REDIS_TOKEN_SCOPE` | Counter projection/coordination |
| `MODEL_REGISTRY` | Protocol/alias allowlist with provider path, model and price version |
| `APIM_USAGE_EVENT_URL`, `API_AUDIENCE` | Streaming callback to native APIM Event Hub logger |
| `STREAM_MAX_EVENT_BYTES`, `STREAM_MAX_BODY_BYTES`, `STREAM_TIMEOUT_SECONDS` | Bounded streaming transport |
| `AZURE_DASHBOARD_ID`, `LOG_ANALYTICS_WORKSPACE_ID`, `LOG_ANALYTICS_WORKSPACE_RESOURCE_ID` | Fixed Admin dashboard query destinations |
| `APPLICATIONINSIGHTS_CONNECTION_STRING`, `TELEMETRY_ENABLED`, `OTEL_SERVICE_NAME` | Operational telemetry |
| `LOCAL_AUTH_ENABLED`, `LOCAL_STORE_ENABLED` | Explicit local-only test mode |
| `LOCAL_REDIS_URL`, `LOCAL_TABLE_CONNECTION_STRING` | Optional real local stores, supplied together |

Use the local `/openapi.json` for executable field constraints. Do not expose a
catch-all proxy that turns the portal into a Gateway-role usage-ingestion client.
