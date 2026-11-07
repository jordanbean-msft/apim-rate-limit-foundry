# Infrastructure reference

This guide owns Terraform/azd inputs, packaging and provider-specific maintenance.
Use [deployment](../docs/deployment.md) for the execution runbook,
[Azure topology](../docs/azure-topology.md) for resources/networking/identity, and
[observability](../docs/observability.md) for dashboard and logging details.
Validation does not provision Azure resources.
The [editable physical architecture](../docs/diagrams/physical-architecture.drawio)
has separate public-demo and private-reference pages; see
[previews and editing instructions](../docs/diagrams/README.md).

## Input sources and value flow

[`environment.example.json`](environment.example.json) is the complete non-secret
azd environment shape. [`main.tfvars.json`](main.tfvars.json) maps those strings
into typed Terraform objects; [`variables.tf`](variables.tf) defines validations.
[`provider.conf.json`](provider.conf.json) supplies remote-state placeholders.
Read all placeholders before provisioning; the short deployment example is not
a complete environment.

`CREATE_FOUNDRY=true` manages a Microsoft Foundry **`AIServices` / S0** account,
with project management enabled and a dedicated user-assigned managed identity.
No hub, project or Agent Service is required for these account-level inference
APIs. The account retains its existing diagnostic export; managed identities
have no resource diagnostic categories or native Application Insights integration.
APIM and the streaming Function retain their least-privilege OpenAI User roles
for OpenAI models; the account's own identity is not the inference caller.
Created Chat backends use the account's custom-subdomain **OpenAI-compatible
inference origin**, not its general AIServices endpoint or a Foundry project URL.
Existing compatible referenced accounts remain supported. See the
[in-place upgrade runbook](../docs/deployment.md#upgrade-an-existing-openai-account).

```text
azd environment strings
    -> main.tfvars.json / provider.conf.json substitution
    -> typed Terraform variables and modules
    -> SCREAMING_SNAKE_CASE outputs captured by azd
    -> service names, application settings and public portal configuration
```

| Input group | Important distinctions |
| --- | --- |
| `AZURE_*`, `ARM_ENVIRONMENT` | Existing subscription/tenant/region/RG/deployer; cloud name is `AzureCloud` or `AzureUSGovernment`, provider/state environment `public` or `usgovernment` |
| `RS_RESOURCE_GROUP`, `RS_STORAGE_ACCOUNT`, `RS_CONTAINER_NAME` | Existing Entra-authenticated state backend in the selected cloud |
| `*_SUBNET_ID`, `PUBLIC_NETWORK_ACCESS_ENABLED` | Explicit public exception or existing private subnets; see topology requirements |
| `APIM_PUBLISHER_*`, `GATEWAY_CLIENT_AUDIENCE` | Publisher metadata and inference-token audience, distinct from generated limiter API audience |
| `ENABLE_*`, `CREATE_*`, backend IDs/endpoints/locations | Explicit create/reference ownership; disabled values must still satisfy placeholder substitution |
| `*_DEPLOYMENT_*`, `*_API_VERSION`, `*_TOKEN_AUDIENCE` | Model alias, provider version and verified resource audience, not inferred from hostname |
| `*_PRICE_VERSION` | Route's pinned catalog version; catalog edits do not change this pin |
| `MAX_INPUT_TOKENS`, tokenizer/context attestations | Shared Function bound and protocol-specific hard-input evidence |
| `REDIS_TOKEN_SCOPE`, `REDIS_INSPECTION_ENABLED` | Verified data-plane scope and normally disabled operator-only read inspection |

Use explicit empty strings/false for disabled fields, not missing placeholders.
Never put credentials into `AZD_ENV_JSON` or commit generated state/environment files.

### Managed models and application subscriptions

Set `MANAGED_MODELS` explicitly to `{}` to retain legacy/reference-only behavior,
or load [`managed-models.example.json`](managed-models.example.json) after checking
the target account's current catalog and quota:

```sh
azd env set MANAGED_MODELS "$(cat infra/managed-models.example.json)"
azd env set APPLICATION_SUBSCRIPTIONS_CONFIG '{"inference":{"demo-app-a":{"tenant_id":"<AZURE_TENANT_ID>","display_name":"Demo application A"},"demo-app-b":{"tenant_id":"<AZURE_TENANT_ID>","display_name":"Demo application B"}},"portal":{"subscription_id":"portal-server","display_name":"Portal server"}}'
```

Replace both tenant placeholders with the explicit deployment tenant. These IDs
are persistent APIM subscription resource names, not key values or Entra user IDs.
`APPLICATION_SUBSCRIPTIONS` and `APPLICATION_REGISTRY` outputs contain only the
inference IDs, tenant IDs and display names. Both Function hosts receive the same
`APPLICATION_REGISTRY`. Portal subscriptions never enter cost-limited app metadata.
The portal product contains only the control-plane API; the inference product
contains only inference APIs. Every API and product requires a native subscription
key **and** policy-validated Entra authentication. Do not use all-access/API-scoped
subscriptions or put keys in URLs.

The managed example adds real `gpt-5.4`, `gpt-5.4-mini` and `gpt-5.4-nano`
deployments, each with explicit GlobalStandard capacity 10 and separate Chat and
Responses caps/price-card keys pinned to `azure-global-text-2026-11-06`. It
preserves the existing account and legacy
`sample-model` deployment. Configuring managed models hides legacy sample entries
from the active registry and removes their implicit model defaults; other enabled
protocol references and additional `LLM_MODELS` references remain supported.
Managed aliases cannot overwrite the
legacy deployment or duplicate referenced registry keys. Private and Government
attestations in this Commercial/public example are intentionally false; verify
and change them before using another cloud/network mode. No Marketplace terms
are accepted.

On 2026-11-06 the existing eastus2 account catalog reported all three GA model
versions in the example with Chat and Responses capability. GlobalStandard quota
used/limit was 0/3000 (`gpt-5.4`), 1060/3002 (mini), and 4484/15000 (nano).
Quota is subscription-wide and can change before provisioning.
[Azure OpenAI pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/)
and the [Azure Retail Prices API](https://prices.azure.com/api/retail/prices?%24filter=armRegionName%20eq%20%27eastus2%27%20and%20contains%28meterName%2C%20%275.4%27%29&currencyCode=%27USD%27)
agree on these Global Standard USD rates per million tokens:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| gpt-5.4 (under 272k input) | 2.50 | 0.25 | 15.00 |
| gpt-5.4-mini | 0.75 | 0.075 | 4.50 |
| gpt-5.4-nano | 0.20 | 0.02 | 1.25 |

These are references, not seeded price cards or contractual quotes. The example's
128000/64000/32000 input caps keep requests in the short-context pricing regime;
output caps are 4096/4096/2048. Seed and approve the three alias/version price cards
before enabling inference.

### Portal-only secret storage and Graph consent

The explicit hosting inputs retain the existing P1v2 plans and disabled Always On
for the main Function/web workloads; the stream host remains Always On. The Node
24 update does not resize plans or silently reconcile those live settings.

The dedicated `portal_key_vault` module has the standard four-file layout. Native
APIM product subscriptions intentionally require a key in addition to Entra,
so this credential is an explicit exception to managed-identity-only data-plane
authentication. Terraform stores the portal subscription's generated primary key
in Key Vault and protected remote state. There are no root key outputs, browser
settings or hardcoded credentials. Restrict remote-state access and never publish
plans/state or generated azd environment files. The deployer gets Secrets Officer
for initial IaC; only the web workload identity gets Secrets User. No inference
identity receives vault permissions.

The web App Service resolves the versionless secret through
`key_vault_reference_identity_id` and its server-only
`PORTAL_APIM_SUBSCRIPTION_KEY=@Microsoft.KeyVault(SecretUri=...)` setting.
`WEB_API_PROXY_ENABLED=true` keeps browser calls same-origin; `API_BASE_URL`
remains the absolute APIM `/portal` upstream. Browser code uses `/api` and
`X-Portal-Access-Token`, while the Node server injects the subscription key.
Key Vault diagnostics export every supported category/metric. Key Vault has no
native Application Insights agent; the web workload retains its native agent.
Private mode creates a policy-DNS-managed endpoint; the runner and web integration
subnet must reach it. APIM key rotation must update the vault secret; versionless
App Service references refresh automatically (allow the platform refresh interval
or request an authenticated configuration-reference refresh after rotation).

The existing portal registration retains native EasyAuth, SPA PKCE, API roles
and managed-identity federation. It adds only Microsoft Graph delegated
`User.Read`, with explicit tenant-wide delegated consent. The Graph enterprise
application/scope is resolved through the selected cloud's Entra provider, not a
cross-cloud object ID. `GRAPH_BASE_URL` is cloud-specific. Own-photo access uses
a separate Graph token, never the API token; no directory-wide application
permission or new registration is created. The operator needs sufficient Entra
permission/admin role to grant consent.

### Additional model references

`LLM_MODELS` is a required azd environment value. The checked-in example uses
`{}`; `main.tfvars.json` injects this value as a typed Terraform map, not a quoted
JSON string. Each entry is an already-deployed reference; Terraform never creates
the additional model deployment. Existing azd environments must explicitly add
`azd env set LLM_MODELS '{}'` before provisioning if they have no additional models.
This input differs from the generated runtime `MODEL_REGISTRY`; do not pass
`examples/model-registry.json` as `LLM_MODELS`. The exact object shape is:

```json
{
  "<api_protocol>:<alias>": {
    "api_protocol": "openai-chat | openai-responses | anthropic-messages",
    "resource_id": "/subscriptions/<subscription>/resourceGroups/<group>/providers/Microsoft.CognitiveServices/accounts/<account>",
    "endpoint": "https://<verified-account-origin>",
    "audience": "https://cognitiveservices.azure.com",
    "location": "eastus2",
    "deployment_name": "<actual-provider-deployment>",
    "price_version": "<published-price-card-version>",
    "max_input_tokens": 64000,
    "max_output_tokens": 2048,
    "role_definition_name": "Cognitive Services OpenAI User",
    "capability_verified": true,
    "government_verified": false,
    "byte_tokenizer_verified": true,
    "private_endpoint_verified": true,
    "api_version": "2024-10-21",
    "anthropic_version": "",
    "hard_input_cap_verified": false,
    "input_cap_evidence": ""
  }
}
```

All attributes are required; protocol-irrelevant values are explicit empty
strings or `false`. The key's protocol must equal `api_protocol`, and its suffix
is the client/accounting alias. `deployment_name` may differ from that alias.
Input/output caps are positive integers no greater than `MAX_INPUT_TOKENS` and
`gateway.max_output_tokens`. Origins must be HTTPS with no credentials, path,
query or fragment; resource, audience and region must match the selected cloud.
Set the tokenizer/capability/private-network attestations only after verifying
the referenced deployment. Messages additionally requires `hard_input_cap_verified`,
nonempty `input_cap_evidence`, an `anthropic_version`, and an input ceiling at
most the Function cap. Its `max_input_tokens` must be the verified full backend
hard input ceiling, not a preferred application cap. Government Responses requires its separate availability
attestation; Government Messages is rejected. Preflight checks each referenced
resource exists, has key authentication disabled, and is private-only with
verified DNS/routing when public access is disabled.

This complete shape illustrates two entries per protocol (replace sample
resource IDs/origins/deployment names with real same-cloud resources before
provisioning):

```json
{
  "openai-chat:chat-fast": {
    "api_protocol": "openai-chat", "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/chat",
    "endpoint": "https://chat.openai.azure.com", "audience": "https://cognitiveservices.azure.com", "location": "eastus2",
    "deployment_name": "gpt-4o-mini-fast", "price_version": "chat-v1", "max_input_tokens": 64000, "max_output_tokens": 2048,
    "role_definition_name": "Cognitive Services OpenAI User", "capability_verified": true, "government_verified": false,
    "byte_tokenizer_verified": true, "private_endpoint_verified": true, "api_version": "2024-10-21",
    "anthropic_version": "", "hard_input_cap_verified": false, "input_cap_evidence": ""
  },
  "openai-chat:chat-quality": {
    "api_protocol": "openai-chat", "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/chat",
    "endpoint": "https://chat.openai.azure.com", "audience": "https://cognitiveservices.azure.com", "location": "eastus2",
    "deployment_name": "gpt-4o-quality", "price_version": "chat-v2", "max_input_tokens": 128000, "max_output_tokens": 4096,
    "role_definition_name": "Cognitive Services OpenAI User", "capability_verified": true, "government_verified": false,
    "byte_tokenizer_verified": true, "private_endpoint_verified": true, "api_version": "2024-10-21",
    "anthropic_version": "", "hard_input_cap_verified": false, "input_cap_evidence": ""
  },
  "openai-responses:responses-fast": {
    "api_protocol": "openai-responses", "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/responses",
    "endpoint": "https://responses.openai.azure.com", "audience": "https://ai.azure.com", "location": "eastus2",
    "deployment_name": "gpt-4o-mini-responses", "price_version": "responses-v1", "max_input_tokens": 64000, "max_output_tokens": 1024,
    "role_definition_name": "Cognitive Services OpenAI User", "capability_verified": true, "government_verified": false,
    "byte_tokenizer_verified": true, "private_endpoint_verified": true, "api_version": "v1",
    "anthropic_version": "", "hard_input_cap_verified": false, "input_cap_evidence": ""
  },
  "openai-responses:responses-quality": {
    "api_protocol": "openai-responses", "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/responses",
    "endpoint": "https://responses.openai.azure.com", "audience": "https://ai.azure.com", "location": "eastus2",
    "deployment_name": "gpt-4o-responses", "price_version": "responses-v2", "max_input_tokens": 128000, "max_output_tokens": 2048,
    "role_definition_name": "Cognitive Services OpenAI User", "capability_verified": true, "government_verified": false,
    "byte_tokenizer_verified": true, "private_endpoint_verified": true, "api_version": "v1",
    "anthropic_version": "", "hard_input_cap_verified": false, "input_cap_evidence": ""
  },
  "anthropic-messages:messages-fast": {
    "api_protocol": "anthropic-messages", "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/messages",
    "endpoint": "https://messages.services.ai.azure.com", "audience": "https://ai.azure.com", "location": "eastus2",
    "deployment_name": "claude-3-5-haiku", "price_version": "messages-v1", "max_input_tokens": 128000, "max_output_tokens": 1024,
    "role_definition_name": "Azure AI User", "capability_verified": true, "government_verified": false,
    "byte_tokenizer_verified": false, "private_endpoint_verified": true, "api_version": "",
    "anthropic_version": "2023-06-01", "hard_input_cap_verified": true, "input_cap_evidence": "Replace with verified backend hard-cap evidence"
  },
  "anthropic-messages:messages-quality": {
    "api_protocol": "anthropic-messages", "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/messages",
    "endpoint": "https://messages.services.ai.azure.com", "audience": "https://ai.azure.com", "location": "eastus2",
    "deployment_name": "claude-sonnet-4-5", "price_version": "messages-v2", "max_input_tokens": 128000, "max_output_tokens": 2048,
    "role_definition_name": "Azure AI User", "capability_verified": true, "government_verified": false,
    "byte_tokenizer_verified": false, "private_endpoint_verified": true, "api_version": "",
    "anthropic_version": "2023-06-01", "hard_input_cap_verified": true, "input_cap_evidence": "Replace with verified backend hard-cap evidence"
  }
}
```

Terraform folds these references and enabled legacy inputs into one exact
`protocol:alias` registry. APIM rejects unknown/wrong-protocol aliases before
reservation and uses each entry's pricing/version/limits/endpoint. An omitted
`model` uses only the corresponding explicitly configured legacy deployment;
additional references never become an implicit default. The API and streaming
Functions receive the same `MODEL_REGISTRY`; the old `STREAM_BACKENDS` setting
remains for legacy runtime compatibility. `LLM_GATEWAY_ROUTES` includes every
alias under each route's `models` map; its legacy `model` field is empty when
that route has no explicit default.

When adding aliases for an account already created by this deployment, retain
the azd-captured `FOUNDRY_RESOURCE_ID` even with `CREATE_FOUNDRY=true`. That known
ID lets Terraform reuse the existing gateway/stream roles and diagnostics;
the module verifies it identifies the managed account.

Configured example sizes include classic APIM `Developer_1`, Dedicated Linux `P1v2`
hosting, Python 3.12/Node 24 LTS, ZRS storage and cloud-specific Redis. These are
**configuration examples**, not assertions about a deployed environment or production
recommendations. APIM Developer has no production SLA; do not select Functions Flex
Consumption for these packages.

Tag the existing application RG `azd-env-name=<environment-name>` for discovery;
keep the separate state RG outside that tag. `SecurityControl=Ignore` is specific
to the approved demo, not a baseline security setting.

## Service packaging and outputs

Run azd from the repository root. [`azure.yaml`](../azure.yaml) defines:

| Service | Package hook | Host/output |
| --- | --- | --- |
| `api` | [`package-function.sh`](scripts/package-function.sh) exports frozen requirements with uv | Root ASGI Function, `AZURE_FUNCTION_NAME` |
| `stream` | [`package-stream.sh`](scripts/package-stream.sh) builds project wheel and exports runtime dependencies | Separate Function, `AZURE_STREAM_FUNCTION_NAME` / `AZURE_STREAM_FUNCTION_ID` |
| `web` | [`package-web.sh`](scripts/package-web.sh) stages `dist/`, `server/`, `package.json` under ignored `.artifacts/web` | App Service, `AZURE_WEB_NAME` |

The portal production server needs only Node built-ins, not runtime `node_modules`.
Function content uses identity-based host storage and SCM/Oryx, not Azure Files
credentials. The root `.funcignore` excludes `stream/` and its wheel.

Other outputs include `API_AUDIENCE`, `API_SCOPE`, `WEB_CLIENT_ID`, `API_BASE_URL`,
`WEB_URL`, `GATEWAY_URL`, `FOUNDRY_RESOURCE_ID`, `LLM_GATEWAY_ROUTES`, and
`AZURE_DASHBOARD_ID`/`AZURE_DASHBOARD_URL`. Treat outputs marked sensitive and remote
state as protected even when a particular endpoint is not itself a credential.

## Dedicated streaming host

`streaming.enabled=true` creates a separate app on the existing Function plan.
It shares the Function identity/stores/Easy Auth audience, but has a distinct
name, diagnostics and `OTEL_SERVICE_NAME=rate-limiter-stream`.
Only it enables `PYTHON_ENABLE_INIT_INDEXING=1`.

Runtime backend JSON is keyed by enabled protocol and contains fixed endpoint,
path, model, audience and provider versions. It is assembled from Terraform's
enabled backends, not a client URL. AI grants are deduplicated by resource/role.

Use the **runtime-compatible intersection** when overriding limits:

| Setting | Configured example | Effective Python runtime range |
| --- | ---: | --- |
| `streaming.max_event_bytes` | 65536 | 8192–1048576 bytes |
| `streaming.timeout_seconds` | 180 | 10–210 seconds |

The current Terraform variable checks are looser (1024-byte minimum and
230-second maximum). Passing Terraform alone therefore does not prove a custom
value will start the Python app. Match [`Settings`](../src/apim_rate_limit_foundry/config.py);
the example values fit both. The body cap follows `gateway.max_body_bytes`.

Stream-only diagnostics/private endpoints are separate root modules,
`stream_diagnostics` and `stream_private_endpoints`. This avoids pulling the
existing application resources through a broad input-map dependency during a
carefully scoped change. The Function plan remains a dependency.

For `streaming.enabled=false`, no observer or its AI grants are created. Deploy
only `api` and `web`; direct provider streaming retains conservative accounting.
See [local development](../docs/local-development.md#dedicated-streaming-host)
for local host/debug instructions.

## Protocol enablement and hard-input-cap verification

Responses and Messages default disabled. Enablement flags are operator
attestations, not automatic proof of provider behavior. The exact wire subset
is owned by the [APIM contract](../apim/README.md).

### Responses

Provide `ENABLE_RESPONSES` and the capability/tokenizer/private-connectivity
attestations applicable to the target. It references an existing account and uses
`/openai/v1/responses`, its own `v1|preview` version, deployment alias and explicit
audience/role. It does not inherit Chat's dated REST version or deployment URL.

When referencing Chat's newly created account, retain its output `FOUNDRY_RESOURCE_ID`
even with `CREATE_FOUNDRY=true`; Terraform verifies ownership and reuses the role.
Government additionally requires `RESPONSES_GOVERNMENT_VERIFIED` and independently
verified account, audience, model/API and regional availability. Never enable it
by copying a Commercial endpoint.

### Messages

Reference an approved AI Services account with a deployed Claude model, explicit
audience/role, pinned `ANTHROPIC_VERSION`, and no Chat API-version query.
An OpenAI-only role is not sufficient. Marketplace terms and provider approvals
are operator responsibilities; Government enablement is rejected.

Before setting the capability flags:

1. Verify model/version, region, endpoint, standard-tier text behavior, Entra
   audience, role and local-key authentication being disabled.
2. Establish the full hard maximum accepted input, including system/tools/history
   and platform-added tokens. An arbitrary preferred application cap is not proof.
   Record documentation, controlled acceptance/rejection and approval in
   `ANTHROPIC_INPUT_CAP_EVIDENCE`.
3. Set `ANTHROPIC_HARD_INPUT_CAP_VERIFIED=true`,
   `ANTHROPIC_CONTEXT_INPUT_TOKENS` to at least that proven bound, and
   `MAX_INPUT_TOKENS` to at least the same number. Every request reserves this
   entire ceiling plus maximum output; no OpenAI byte-token assumption is reused.
4. Publish matching uncached/read/write-5m/write-1h/output prices and model rules.
5. In private mode, verify externally owned backend endpoints/DNS and connectivity
   from both the gateway and streaming host before attesting private reachability.

Disable and reverify after changes that can increase accepted context or change
the pricing contract. Consult the current [Responses](https://learn.microsoft.com/azure/foundry/openai/how-to/responses)
and [Claude on Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry)
documentation rather than treating example audiences or capacities as universal.

## Authentication and telemetry settings

Terraform permits the SPA/gateway client applications through Function Easy Auth;
`hosting.allowed_client_applications` adds approved automation. The example includes
Microsoft's Azure CLI client for setup/testing. Remove it if unnecessary; an allowed
client still needs tenant/audience/role authorization. Details and actual grants
are in [Azure topology](../docs/azure-topology.md#identity-and-token-boundaries).

The public portal config/runtime fields are documented in [web/README.md](../web/README.md);
backend variables are in [configuration reference](../docs/configuration-reference.md).
Do not maintain a second environment-variable list here.

Demo telemetry uses sampling ratio 1 and APIM sampling 100%; local hosting logs
retain seven days within 100 MB, independent of workspace retention.
`REDIS_INSPECTION_ENABLED=false` is normal. Enabling it explicitly gives the
deployer read-only inspection, not write/reset access: Commercial uses AzAPI's
`2026-05-01-preview` custom ACL because the stable AzureRM assignment is broader;
Government uses `Data Reader`. Disable inspection again after verification.
The baseline engines are nonclustered/no-eviction, and counter keys share a
`{limiter}` slot tag. A cold readiness gate requires protected
[recovery](../docs/operations.md#recovery), not flushing state or waiting for TTL.

## Shared Azure portal rate-limiter dashboard

The monitoring module publishes the dashboard outputs and inherits tags.
The [observability guide](../docs/observability.md) owns the complete 13-chart/
9-grid inventory, schemas, viewer RBAC, scope/time behavior and source queries.
It is the single dashboard operator reference.

## APIM provider maintenance

The parent APIM service uses cloud-aware AzAPI. AzureRM's legacy tenant-access
secret read can return HTTP 405 when direct management is disabled; do not enable
the retired API to work around provisioning. APIM child resources use AzureRM.

For an existing deployment being migrated between those parent resource addresses:
back up remote state, import the unchanged service ID at
`module.apim.azapi_resource.this`, then remove **only**
`module.apim.azurerm_api_management.this` from state. Review a no-destruction plan
before applying; never recreate a gateway merely to change its Terraform provider.

## Validation boundary

Use [local validation commands](../docs/local-development.md#tests-and-checks)
and the live [acceptance checklist](../docs/operations.md#operator-acceptance-checklist).
Offline mocked plans, schema validation and XML tests do not prove quotas,
private DNS, Entra issuance, APIM compilation, or actual client acceptance.
