# Infrastructure reference

Terraform defines the OpenAI-only gateway; azd orchestrates deployment.
Validation and mocked tests do **not** provision Azure resources.
See [deployment](../docs/deployment.md) for the execution runbook,
[gateway contracts](../apim/README.md) for policies, and
[observability](../docs/observability.md) for operational guidance.

## Configuration and state

`environment.example.json` is the complete non-secret azd environment shape.
`main.tfvars.json` substitutes those strings into required typed inputs in
`variables.tf`. `provider.conf.json` supplies the Entra-authenticated Azure Blob
state coordinates (`RS_RESOURCE_GROUP`, `RS_STORAGE_ACCOUNT`, `RS_CONTAINER_NAME`).
Never commit generated environments, state, plans, credentials or subscription keys.

The resource group, VNets, integration/endpoint/APIM subnets and private DNS zones
are pre-created. Terraform never creates a resource group or private DNS zone
group/link. All private endpoints ignore DINE-managed `private_dns_zone_group`.
`PUBLIC_NETWORK_ACCESS_ENABLED=false` is the private reference; public mode is
an explicit development exception. A private runner must reach SCM, Storage/Table,
Redis, Azure OpenAI and Event Hubs through operator-managed routing/DNS.

| Configuration | Purpose |
|---|---|
| `AZURE_*`, `ARM_ENVIRONMENT` | Existing subscription/tenant/region/RG/deployer; explicit `AzureCloud/public` or `AzureUSGovernment/usgovernment` |
| `*_SUBNET_ID` | Existing delegated service subnets, APIM subnet and private endpoint subnet |
| `APIM_PUBLISHER_*`, `GATEWAY_CLIENT_AUDIENCE` | Publisher metadata and inference JWT audience; distinct from generated limiter API audience |
| `ENABLE_FOUNDRY`, `CREATE_FOUNDRY`, `FOUNDRY_*` | Preserve direct OpenAI account/create-or-reference choice and legacy deployment |
| `ENABLE_RESPONSES`, `RESPONSES_*` | Explicit optional referenced Responses endpoint/version, role and sovereign/private capability attestations |
| `LLM_MODELS`, `MANAGED_MODELS` | Explicit additional references or real managed OpenAI deployments; use `{}` when empty |
| `APPLICATION_SUBSCRIPTIONS_CONFIG` | Stable native inference subscription IDs and separate server-only portal subscription |
| `REDIS_TOKEN_SCOPE`, `REDIS_INSPECTION_ENABLED` | Verified Redis scope and normally disabled read-only operator inspection |
| `EVENT_HUB_CAPACITY`, `EVENT_HUB_PARTITIONS`, `EVENT_HUB_RETENTION_DAYS` | Required explicit Standard namespace sizing, partitioning and retention; example `1`, `2`, `7` |

Deployment SKUs, worker counts, TLS, sampling, retention, timeouts and limits are
visible explicitly in tfvars, not hidden defaults. Configure every placeholder.
Outputs use SCREAMING_SNAKE_CASE and flow back into azd/service settings.

## Preserved OpenAI and hosting baseline

`CREATE_FOUNDRY=true` manages a direct `OpenAI` / S0 account with a dedicated
user-assigned identity, no Foundry project child resource, and disabled local
authentication. Created inference origins are the official custom-subdomain
`.openai.azure.com` / `.openai.azure.us` URLs. Existing compatible referenced
accounts remain supported. APIM and the retained stream relay use explicit
least-privilege OpenAI User grants; the account's own identity is not the caller.

The existing legacy `sample-model` deployment and APIM backend entities remain.
`MANAGED_MODELS` adds real model deployments without overwriting the legacy
deployment. Nonempty managed models hide legacy sample aliases/defaults from the
active registry; additional references remain available.
`managed-models.example.json` has three explicitly versioned deployment aliases
and their Chat/Responses price/capability/cap metadata. Recheck regional catalog,
pricing, quota and private/Government attestations before using it.

The shared function/web plans keep the existing P1v2 specifications and disabled
Always On settings; the stream host remains Always On. The web uses Node 24 LTS,
the Functions use Python 3.12. This change does not resize plans silently.

The inference product and portal product still require native subscription keys
plus Entra JWT authentication. Product subscriptions have stable IDs; keys rotate
without changing attribution. Subscription ID is an application dimension, not
the person budget key. Inference requires delegated person `tid`/`oid`, then an
enabled user assignment. Monthly USD budgets apply to every configured user,
team and department; they are **soft caps** and concurrent requests can overshoot.

The portal key remains a credential exception stored in Key Vault/protected
Terraform state. Only the web workload has Secrets User; the deployer has Secrets
Officer for setup. The browser never receives the key. Existing EasyAuth, SPA
PKCE, API roles, managed-identity federation and delegated Graph `User.Read` consent
remain; no directory-wide application permissions are added.

## Model references

`LLM_MODELS` references existing deployments; Terraform does not create them.
It is a typed map keyed by `<api_protocol>:<client-alias>`, with protocols restricted
to `openai-chat` and `openai-responses`. Example:

```json
{
  "openai-chat:fast": {
    "api_protocol": "openai-chat",
    "resource_id": "/subscriptions/<subscription>/resourceGroups/<group>/providers/Microsoft.CognitiveServices/accounts/<account>",
    "endpoint": "https://<account>.openai.azure.com",
    "audience": "https://cognitiveservices.azure.com",
    "location": "eastus2",
    "deployment_name": "provider-deployment",
    "price_version": "approved-v1",
    "max_input_tokens": 64000,
    "max_output_tokens": 2048,
    "role_definition_name": "Cognitive Services OpenAI User",
    "capability_verified": true,
    "government_verified": false,
    "byte_tokenizer_verified": true,
    "private_endpoint_verified": true,
    "api_version": "2024-10-21"
  }
}
```

The alias may differ from the actual deployment. All fields are required;
endpoints must be same-cloud HTTPS origins without path/query/credentials.
Responses uses `api_version:"v1"` or `"preview"` and separate Government
availability verification. Capability/private/native-token-policy attestations
are operator assertions, not claims of regional availability.
`price_version` pins a published Python price card; APIM does no cost calculation.

## Native Event Hubs export

`modules/event_hubs` creates a Standard namespace and usage hub with explicitly
configured throughput/partitions/retention, TLS 1.2 and disabled local auth.
Only the APIM managed identity receives **Azure Event Hubs Data Sender**, scoped
to the hub. An explicit RBAC propagation wait precedes logger use.
Neither Function nor web receives Event Hubs producer permissions.

AzureRM **5.13** supports `eventhub.endpoint_uri` and
`eventhub.user_assigned_identity_client_id` on `azurerm_api_management_logger`,
so no AzAPI logger or connection string is needed. The namespace hostname uses
the correct Commercial/Government suffix. The existing Application Insights
logger remains separate. Latest stable provider versions were checked against
the Terraform registry: AzureRM 5.13.0 and AzAPI 2.13.0; existing `~>` pins match.
See the [provider logger reference](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/api_management_logger)
and [Microsoft managed-identity logger documentation](https://learn.microsoft.com/azure/api-management/api-management-howto-log-event-hubs).

The namespace exports all supported diagnostic logs and metrics to the shared
workspace; Event Hubs has no native Application Insights agent. Private mode
adds its namespace endpoint with policy-owned DNS. APIM's integration subnet
must resolve/reach the hub's private namespace.

The native `log-to-eventhub` policy publishes only compact normalized v2 events
returned after durable actual/unknown usage recording, and only for new records.
It is **unsampled by Application Insights** and truncates events exceeding
**200 KB**. Keep the compact schema below 16 KiB. Delivery is best effort:
no SDK publisher, no retries and no failed inference due to logger availability.
The ledger remains authoritative; absence from Event Hubs is not evidence that
the request was uncharged.

Streaming remains unbuffered through the narrow relay. Function runtime settings
include `APIM_USAGE_EVENT_URL` and `API_AUDIENCE`; its managed identity receives
the existing `RateLimit.Gateway` role for the callback. The internal APIM operation
requires that exact identity's client/object IDs and no delegated scope. It is
not part of either client product and cannot be invoked by portal users.

Outputs include `EVENT_HUB_NAMESPACE_NAME`, `EVENT_HUB_NAME`,
`EVENT_HUB_RESOURCE_ID`, and `APIM_USAGE_EVENT_URL`; none are secrets.

## Single dashboard query catalog

`modules/monitoring/queries/` contains only the replacement v2 KQL:
month-to-date actual model spend, hierarchy utilization/denials, cached/uncached/
output tokens, business-unit/cost-center chargeback, application attribution,
request health, unknown usage and Event Hub health. Terraform persists the exact
queries in the Azure portal dashboard. The Admin dashboard service reads that
persisted layout/KQL, not a second application catalog. Monthly spend owns its
month-start query window; other activity tables use the selected period.

Traces can be sampled/delayed and budget balances are last-observed snapshots,
not live reads. Use authorized JSON/CSV chargeback exports and the durable
ledger for reconciliation, not dashboard totals or Event Hub delivery counts.

## Validation and destructive migration boundary

```sh
terraform -chdir=infra init -backend=false
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra test
uv run python -m pytest apim/tests -W error
```

All Terraform tests use mocked providers; even test `command=apply` never contacts
Azure. Require zero validation errors **and warnings**.

**Do not run live provision/deploy as part of this refactor.** Removing old APIs,
services and role bindings can destroy live resources. Before an approved cutover,
export/archive previous configuration and historical usage, review a real plan
for destructive changes, approve user/team/department mappings and price cards,
then run explicit Chat/Responses nonstream/stream, budget exhaustion/overshoot,
callback-auth rejection, cache rebuild, Event Hub failure-isolation and chargeback
acceptance. Never silently reinterpret old application budgets as person budgets.
