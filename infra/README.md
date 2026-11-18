---
title: Infrastructure reference
description: Terraform inputs, resource choices, model backends and infrastructure validation.
---

## Overview

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

| Configuration                                                            | Purpose                                                                                                           |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `AZURE_*`, `ARM_ENVIRONMENT`                                             | Existing subscription/tenant/region/RG/deployer; explicit `AzureCloud/public` or `AzureUSGovernment/usgovernment` |
| `*_SUBNET_ID`                                                            | Existing delegated service subnets, APIM subnet and private endpoint subnet                                       |
| `APIM_PUBLISHER_*`, `GATEWAY_CLIENT_AUDIENCE`                            | Publisher metadata and inference JWT audience; distinct from generated limiter API audience                       |
| `ENABLE_FOUNDRY`, `CREATE_FOUNDRY`, `FOUNDRY_*`                          | Preserve direct OpenAI account/create-or-reference choice and legacy deployment                                   |
| `ENABLE_RESPONSES`, `RESPONSES_*`                                        | Explicit optional referenced Responses endpoint/version, role and sovereign/private capability attestations       |
| `LLM_MODELS`, `MANAGED_MODELS`                                           | Explicit additional references or real managed OpenAI deployments; use `{}` when empty                            |
| `APPLICATION_SUBSCRIPTIONS_CONFIG`                                       | Stable native inference subscription IDs and separate server-only portal subscription                             |
| `REDIS_TOKEN_SCOPE`, `REDIS_INSPECTION_ENABLED`                          | Verified Redis scope and normally disabled read-only operator inspection                                          |
| `EVENT_HUB_CAPACITY`, `EVENT_HUB_PARTITIONS`, `EVENT_HUB_RETENTION_DAYS` | Required explicit Standard namespace sizing, partitioning and retention; example `1`, `2`, `7`                    |

Deployment SKUs, worker counts, TLS, sampling, retention, timeouts and limits are
visible explicitly in tfvars, not hidden defaults. Configure every placeholder.
Terraform sets application settings directly. Root outputs use
SCREAMING_SNAKE_CASE and flow back into azd for deployment targeting and operator use.
Naming uses azurecaf 2.x with explicit legacy resource slugs where needed to
preserve existing names; a provider update must not silently rename resources.

## OpenAI and hosting configuration

`CREATE_FOUNDRY=true` manages a direct `OpenAI` / S0 account with a dedicated
user-assigned identity, no Foundry project child resource, and disabled local
authentication. Created inference origins are the official custom-subdomain
`.openai.azure.com` / `.openai.azure.us` URLs. Existing compatible referenced
accounts remain supported. APIM and the retained stream relay use explicit
least-privilege OpenAI User grants; the account's own identity is not the caller.

The built-in `sample-model` deployment has its own APIM backend entities.
`MANAGED_MODELS` adds model deployments without overwriting that deployment.
Nonempty managed models hide built-in sample aliases/defaults from the
active registry; additional references remain available.
`managed-models.example.json` has three explicitly versioned deployment aliases
and their Chat/Responses price/capability/cap metadata. Recheck regional catalog,
pricing, quota and private/Government attestations before using it.

### Native backend pools

`MANAGED_MODELS` aliases and `LLM_MODELS` entries accept optional
`additional_endpoints` (`endpoint`, `priority` 1-5, `weight` 1-100,
`private_endpoint_verified`) plus `primary_priority`/`primary_weight`. Without
them an alias keeps one APIM backend (`ai-model-<hash>`). With them Terraform adds a
circuit-breaker backend per member (`ai-model-<hash>-m<n>`, first is the primary
endpoint) and an `azapi_resource` pool (`ai-pool-<hash>`, API `2024-05-01`) that
the policy routes to. Native APIM load balancing and circuit breaking replace any
custom failover code; the Function registry and per-model cost accounting are
unchanged. Breaker thresholds are `gateway.backend_circuit_breaker` in tfvars.
Streaming uses the Function relay and the primary endpoint, so it is not pooled.
Grant the gateway identity RBAC on each additional account yourself.
See [model registry](../docs/model-registry.md#optional-backend-pools-same-model-more-endpoints).

The function/web plans keep the existing P1v2 specifications. The Dedicated
budget Function enables Always On (`hosting.function_always_on=true`) for
low-latency hosting; the stream host also enables Always On. The web's Always On
setting remains disabled. The web uses Node 24 LTS, the Functions use Python 3.12.
These settings are explicit in `main.tfvars.json`.

The inference product and portal product still require native subscription keys
plus Entra JWT authentication. Product subscriptions have stable IDs; keys rotate
without changing attribution. Subscription ID is an application dimension, not
the person budget key. Inference requires delegated person `tid`/`oid`, then an
enabled user assignment. Monthly USD budgets apply to every configured user,
team and department; they are **approximate operational caps** and concurrent
requests can overshoot. Redis loss can reset spend.

`main.tfvars.json` explicitly sets `hosting.configuration_cache_seconds=60` and
`hosting.request_cache_seconds=86400`; root Terraform passes these as
`CONFIGURATION_CACHE_SECONDS` and `REQUEST_CACHE_SECONDS` to **both** Function
hosts so budget checks and streaming accounting use the same retention contract.

Storage queue resources/endpoints support Function hosting, not a durable
accounting queue/outbox. See [operations](../docs/operations.md) for the canonical
Redis retention, fail-closed behavior and process-local history/export loss
contract; [configuration](../docs/configuration-reference.md#runtime-groups)
lists the corresponding runtime settings.

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

The alias may differ from the actual deployment. All fields shown above are
required; the additional pooling fields described earlier are optional.
endpoints must be same-cloud HTTPS origins without path/query/credentials.
Responses uses `api_version:"v1"` or `"preview"` and separate Government
availability verification. Capability/private/native-token-policy attestations
are operator assertions, not claims of regional availability.
`price_version` pins a published Python price card; APIM does no cost calculation.

## Event Hubs export

`modules/event_hubs` creates a Standard namespace and usage hub with explicitly
configured throughput/partitions/retention, TLS 1.2 and disabled local auth.
Only the Function managed identity (`sender_principal_id`) receives **Azure Event
Hubs Data Sender**, scoped to the hub. An explicit RBAC propagation wait precedes
use. Neither APIM nor web receives Event Hubs permissions, and APIM has no Event
Hub logger. The namespace hostname uses the correct Commercial/Government suffix.

The namespace exports all supported diagnostic logs and metrics to the shared
workspace; Event Hubs has no native Application Insights agent. Private mode
adds its namespace endpoint with policy-owned DNS. The Function hosts' network
path must resolve/reach the hub's private namespace.

The Function publishes only compact normalized v2 events with the `azure-eventhub`
SDK after Redis accepts actual/unknown usage, and only for new usage within the
replay window. Events do not establish Table persistence. Delivery is a
best-effort background send through the same serial `BackgroundWriter` as Table
jobs (256 pending jobs, drop-on-full, best-effort two-second shutdown drain).
There is no application-level retry/outbox or replay repair; the Azure Event Hubs
SDK retains its default transport retries. Event Hub availability does not turn
an inference response into a failure.
Redis is the live budget authority; Table is eventual long-term history.
Absence from Event Hubs or Table is not evidence that the request was uncharged.

Streaming remains unbuffered through the narrow relay. Function runtime settings
include `EVENT_HUB_FQDN` and `EVENT_HUB_NAME`, set from the `event_hubs` module
outputs.

Outputs include `EVENT_HUB_NAMESPACE_NAME`, `EVENT_HUB_NAME` and
`EVENT_HUB_RESOURCE_ID`; none are secrets.

## Single dashboard query catalog

`modules/monitoring/queries/` contains only the replacement v2 KQL:
month-to-date actual model spend, hierarchy utilization/denials, cached/uncached/
output tokens, business-unit/cost-center chargeback, application attribution,
request health, unknown usage and Event Hub health. Terraform persists the exact
queries in the Azure portal dashboard. The Admin dashboard service reads that
persisted layout/KQL, not a second application catalog. Monthly spend owns its
month-start query window; other activity tables use the selected period.

Traces can be sampled/delayed and budget balances are last-observed snapshots,
not live reads. Use authorized JSON/CSV chargeback exports and persisted Table
history to investigate retained records, not dashboard totals or Event Hub
delivery counts. Neither reports nor live budgets guarantee financial completeness.

## Validation and deployment safety

```sh
terraform -chdir=infra init -backend=false
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra test
uv run python -m pytest apim/tests -W error
```

Azure operations are mocked; selected naming tests execute the real local
azurecaf provider. These tests do not provision Azure resources, including tests
with `command=apply`. Require zero validation errors **and warnings**.

Removing APIs, services or role bindings can affect live resources. Back up
configuration, usage and Terraform state, review destructive plan actions, and
verify schema compatibility before applying changes. APIM rejects deleting
fragments or backends still referenced by policies: update/remove referencing
policies first, then retire unused objects. Do not bypass these checks by
removing resources from state.

Run the [operational acceptance checklist](../docs/operations.md#acceptance-checklist)
after deployment. Return to the [README](../README.md) for the documentation map.
