# Infrastructure operator notes

This is a non-production reference deployment. No resources are provisioned by validation.
`azure.yaml` packages the **root** Python Function host and the portal's `dist/`,
`server/`, and `package.json`. Run azd from the repository root. The Function prepackage
hook exports `requirements.txt` with uv; do not commit generated credentials or state.
The portal uses `node server/index.mjs` and has no runtime npm dependencies.
Its prepackage hook stages only those three artifacts under ignored `infra/.artifacts/web`,
excluding test sources and npm development dependencies from the App Service package.

## Required configuration

Set `REDIS_INSPECTION_ENABLED=false` normally. Explicitly enabling it grants the
deployment operator read-only Redis inspection for diagnostics; disable it again
after verification. Commercial uses the documented `2026-05-01-preview` custom ACL
API through AzAPI because AzureRM's stable assignment grants full data access.
Government uses the existing `Data Reader` policy. Neither path grants write/reset
commands. The application's workload assignment is unchanged.

Telemetry retains all requests in this demo (`hosting.telemetry_sampling_ratio=1`,
`gateway.diagnostic_sampling_percentage=100`). Local hosting logs retain seven days
within 100 MB; the shared workspace retains its separately configured period.
APIM logs only correlation/reservation headers, never Authorization or message bodies.
Managed Redis connection audit logs belong to its **default database**, not the
parent instance; both database logs and parent metrics are routed to the workspace.
Services without native Application Insights instrumentation (Redis, Storage and AI
accounts) emit resource logs/metrics to Log Analytics and are observed as application
dependencies in Application Insights. Native resource logs can contain platform
network metadata; application telemetry excludes credentials, prompts and raw identities.

Set every `${PLACEHOLDER}` in `main.tfvars.json` and `provider.conf.json` in the azd
environment. Unused service strings may be explicitly empty, but enable/create flags
must always be explicit `true`/`false`. Set `PUBLIC_NETWORK_ACCESS_ENABLED=false`
normally; `true` is a deliberate public development exception, never a fallback.
The requested demo configuration also sets `SecurityControl=Ignore` in the resource
tags. Remove this exemption before using the sample outside the approved demo.
`environment.example.json` enumerates the complete non-secret operator environment
(suitable as the starting shape for a GitHub environment's `AZD_ENV_JSON`). Replace
all placeholders, align `*_PRICE_VERSION` to the catalog you seed, and never copy
Commercial token audience examples to Government without service-specific verification.

| Input | Meaning |
|---|---|
| `AZURE_CLOUD` | `AzureCloud` or `AzureUSGovernment` (not the application's lowercase cloud enum) |
| `ARM_ENVIRONMENT` | `public` or `usgovernment`, including for the remote state backend |
| `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_LOCATION`, `AZURE_ENV_NAME`, `AZURE_RESOURCE_GROUP`, `AZURE_PRINCIPAL_ID` | Existing deployment context and initial administrator object ID |
| `RS_RESOURCE_GROUP`, `RS_STORAGE_ACCOUNT`, `RS_CONTAINER_NAME` | Existing Entra-authenticated state storage in the selected cloud |
| `PRIVATE_ENDPOINT_SUBNET_ID`, `FUNCTIONS_SUBNET_ID`, `WEB_SUBNET_ID`, `APIM_SUBNET_ID` | Existing subnet IDs; app subnets delegated to `Microsoft.Web/serverFarms`; APIM subnet configured for classic internal VNet injection |
| `APIM_PUBLISHER_NAME`, `APIM_PUBLISHER_EMAIL`, `GATEWAY_CLIENT_AUDIENCE` | APIM owner and allowed client-token audience, distinct from the generated limiter API audience |
| `REDIS_TOKEN_SCOPE` | Explicit Entra scope, including `/.default`; see sovereign validation caveat below |
| `ENABLE_FOUNDRY`, `CREATE_FOUNDRY`, `FOUNDRY_RESOURCE_ID`, `FOUNDRY_ENDPOINT`, `FOUNDRY_LOCATION`, `FOUNDRY_DEPLOYMENT_NAME`, `FOUNDRY_MODEL_NAME`, `FOUNDRY_MODEL_VERSION`, `FOUNDRY_DEPLOYMENT_SKU`, `FOUNDRY_TOKEN_AUDIENCE` | Foundry Azure OpenAI-compatible create/reference inputs; no serverless inference/Agents assumption |
| `FOUNDRY_DEPLOYMENT_CAPACITY`, `FOUNDRY_API_VERSION` | Explicit deployment capacity and dated Chat REST version; verify new-deployment eligibility, not just catalog presence and quota |
| `ENABLE_DOCUMENT_INTELLIGENCE`, `CREATE_DOCUMENT_INTELLIGENCE`, `DOCUMENT_INTELLIGENCE_RESOURCE_ID`, `DOCUMENT_INTELLIGENCE_ENDPOINT`, `DOCUMENT_INTELLIGENCE_LOCATION`, `DOCUMENT_INTELLIGENCE_TOKEN_AUDIENCE` | Optional Document Intelligence backend |
| `ENABLE_LANGUAGE`, `CREATE_LANGUAGE`, `LANGUAGE_RESOURCE_ID`, `LANGUAGE_ENDPOINT`, `LANGUAGE_LOCATION`, `LANGUAGE_TOKEN_AUDIENCE` | Optional Language sentiment backend |
| `FOUNDRY_PRICE_VERSION`, `DOCUMENT_INTELLIGENCE_PRICE_VERSION`, `LANGUAGE_PRICE_VERSION` | Explicit operator-pinned catalog versions; creating a new price version does not silently change admission pricing |
| `MAX_INPUT_TOKENS`, `OPENAI_BYTE_TOKENIZER_VERIFIED` | Function input admission bound (positive integer) and explicit Chat byte-tokenizer/framing verification |
| `ENABLE_RESPONSES`, `RESPONSES_CAPABILITY_VERIFIED`, `RESPONSES_GOVERNMENT_VERIFIED`, `RESPONSES_BYTE_TOKENIZER_VERIFIED`, `RESPONSES_PRIVATE_ENDPOINT_VERIFIED` | Explicit Responses enablement and target-cloud/model/API/tokenizer/private-connectivity acceptance flags |
| `RESPONSES_RESOURCE_ID`, `RESPONSES_ENDPOINT`, `RESPONSES_TOKEN_AUDIENCE`, `RESPONSES_LOCATION`, `RESPONSES_DEPLOYMENT_NAME`, `RESPONSES_PRICE_VERSION`, `RESPONSES_ROLE_NAME`, `RESPONSES_API_VERSION` | Referenced Responses account, exact endpoint/resource audience/region/model/catalog, RBAC role and independent `v1` or `preview` version |
| `ENABLE_ANTHROPIC`, `ANTHROPIC_CAPABILITY_VERIFIED`, `ANTHROPIC_PRIVATE_ENDPOINT_VERIFIED`, `ANTHROPIC_HARD_INPUT_CAP_VERIFIED` | Explicit Messages enablement, Commercial capability, private-connectivity and hard-input-cap verification |
| `ANTHROPIC_INPUT_CAP_EVIDENCE`, `ANTHROPIC_CONTEXT_INPUT_TOKENS` | Recorded verification evidence and full backend-enforced maximum accepted input, not a desired per-request cap |
| `ANTHROPIC_RESOURCE_ID`, `ANTHROPIC_ENDPOINT`, `ANTHROPIC_TOKEN_AUDIENCE`, `ANTHROPIC_LOCATION`, `ANTHROPIC_DEPLOYMENT_NAME`, `ANTHROPIC_PRICE_VERSION`, `ANTHROPIC_VERSION`, `ANTHROPIC_ROLE_NAME` | Referenced Foundry AI Services account, exact endpoint/resource audience/region/model/catalog, pinned date header and non-OpenAI-only role |

Review fixed specifications in `main.tfvars.json` before provision: classic `Developer_1`
APIM (no SLA; change to `Premium_1` for production evaluation), Linux Dedicated `P1v3`
Python 3.12 Functions and Node 22 portal, storage `Standard_ZRS`, Commercial
`Balanced_B1` Managed Redis and Government nonclustered Premium P1 Cache. The Function
uses identity-authenticated blob/queue host storage, no Azure Files credentials, and
disables automatic Azure Files content-share configuration. Function content deploys
through SCM/Oryx on the Dedicated plan. Do not select Flex Consumption.

The Entra deployer needs application/service-principal creation, application role assignment,
and tenant-wide delegated consent rights, plus Azure role-assignment write rights.
Remote state needs Blob Data Contributor access. Pre-created resource groups and subnets
must be in the intended region; no shared networking or resource groups are created.
Tag the application resource group with `azd-env-name=<environment-name>` so `azd show`
can discover the existing deployment. Keep the separate state group outside that tag.

Function Easy Auth explicitly allows the portal and gateway client applications.
`hosting.allowed_client_applications` in `main.tfvars.json` adds approved automation clients;
the sample includes Microsoft's Azure CLI client for authenticated setup and smoke testing.
Remove that entry if CLI access is not required. The tenant, token audience and backend
application roles are still required; an approved client ID alone grants no permissions.

## Protocol enablement and hard-input-cap verification

Optional protocols default **disabled**. Even disabled fields must be present in the azd
environment; use the explicit empty strings/false flags in `environment.example.json`.
No new protocol creates an AI account/deployment. Responses can reuse Chat's resource;
Anthropic references an existing **AI Services** account with an already deployed Claude
model. RBAC is deduplicated by principal/scope/role, preserving existing bindings, and
diagnostic settings are deduplicated by resource ID.

Responses uses `https://<account>.openai.azure.com/openai/v1/responses`, with its own
`api-version=v1|preview`, and the deployment alias in the JSON model. It does **not**
inherit Chat's dated version or `/deployments/...` path. Its audience is explicit;
current [Responses documentation](https://learn.microsoft.com/azure/foundry/openai/how-to/responses)
examples use `https://ai.azure.com/.default` (set resource audience `https://ai.azure.com`).
Government requires a `.openai.azure.us` account and independently recorded model, API,
regional availability and audience verification via `RESPONSES_GOVERNMENT_VERIFIED=true`.
Protocol portability is not an availability claim; keep disabled without this verification.

After creating Chat's account, azd captures its `FOUNDRY_RESOURCE_ID`. Retain that
value when enabling Responses against the same account, even with `CREATE_FOUNDRY=true`,
so the existing gateway role is reused rather than assigned twice. Terraform verifies
that a supplied ID identifies the account it manages; do not put another account's ID
in a create configuration.

Messages uses the exact referenced
`https://<account>.services.ai.azure.com/anthropic/v1/messages`, with a pinned
`anthropic-version` header (example `2023-06-01`) and **no** Chat API-version query.
[Claude on Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry)
documents Entra resource audience `https://ai.azure.com` and Cognitive Services User /
Foundry User roles. Set a real role available in the target tenant (`Azure AI User` is
also accepted as a named configuration), not Cognitive Services OpenAI User.
Government Anthropic enablement is rejected: this sample has no verified sovereign Claude
availability and never falls back to Commercial.

Before enabling Messages, the operator must:

1. Verify the referenced deployment, model/version, region, pinned API header, Entra
   audience and **standard-tier text** capability against current provider documentation
   and a controlled endpoint test. Verify local-key authentication is disabled.
2. Establish the backend's hard maximum accepted input, including system/tools/history
   and platform-added tokens. Use the full maximum possible accepted input for this
   deployment/configuration, not an arbitrary smaller application preference. If only a
   total context-window bound is established, reserving that entire window is conservative.
   Record the model/version, documented limit, controlled acceptance/rejection evidence and
   approval reference in `ANTHROPIC_INPUT_CAP_EVIDENCE`; set
   `ANTHROPIC_HARD_INPUT_CAP_VERIFIED=true` only when established.
3. Set `ANTHROPIC_CONTEXT_INPUT_TOKENS` to at least that verified maximum and
   `MAX_INPUT_TOKENS` to at least the same number (example 200000, **not** a universal
   Claude maximum). Terraform and preflight fail closed if the shared Function bound is
   smaller. Every Messages request reserves this full input ceiling plus its output cap.
   No UTF-8-byte assumption is made for Anthropic tokenizers.
4. Seed the pinned `ANTHROPIC_PRICE_VERSION` for `service=foundry` and its deployment
   alias, including explicit uncached/read/write-5m/write-1h decimal rates. Confirm the
   gateway identity can invoke the backend and the limiter can admit/conservatively settle it.
5. In private mode, verify existing backend private endpoints, DNS and APIM connectivity;
   set `*_PRIVATE_ENDPOINT_VERIFIED=true` only after that check. Terraform does not take
   ownership of referenced account networking.

If a model upgrade, endpoint/API/header change or platform feature can increase the input
ceiling or change prices, disable the route and reverify before enabling it again.
Caller beta/tier/geography overrides, built-in tools, opaque history and media are rejected
or removed at the gateway; supported request formats are listed in [the gateway notes](../apim/README.md).
The verification flags are deliberate operator attestations, not automated proof of a model
hard limit. Preflight checks selected cloud/resource properties and disabled public/local-key
access where required; no offline test certifies model availability or provider behavior.

## Private networking

Private ingress is the default explicit tfvars choice. Classic APIM uses **internal VNet
injection**, not APIM private endpoints, because these modes cannot be combined. Its
management/control-plane endpoint remains subject to Azure's APIM management routing
requirements. Functions, web, Redis, and newly created AI resources receive private
endpoints; Storage gets blob, queue, table, and file endpoints. Public development mode
omits private endpoints and VNet integration and enables public data-plane access.

Existing DNS zones, links, and private DNS zone groups are policy-managed. Every endpoint
ignores `private_dns_zone_group` drift. Referenced AI accounts must already have private
connectivity and local-auth disabled; Terraform grants RBAC and diagnostics but does not
silently change externally owned networking. The deployment runner and portal users need
private routing, private SCM DNS resolution, and connectivity to the private endpoints.
Permit APIM control-plane dependencies, Entra, package feeds, Azure Monitor ingestion,
and the correct cloud's ARM endpoints. Private deployment is not supported on an
unconnected public GitHub-hosted runner.

## Cloud audiences are not DNS suffixes

The backend and portal receive `AZURE_CLOUD=commercial|government`, the explicit tenant,
and the cloud-specific Entra authority. Terraform's AzureRM, AzureAD, and remote-state
backend select their own explicit cloud configuration.

The APIM service uses Microsoft's cloud-aware AzAPI provider and its ARM service API.
AzureRM currently unconditionally reads legacy tenant-access secrets, which returns
HTTP 405 when the retired direct-management API is disabled. Do not enable that API to
work around provisioning. APIM child resources continue to use AzureRM. For an existing
deployment, back up remote state, import the unchanged service ID at
`module.apim.azapi_resource.this`, then remove only
`module.apim.azurerm_api_management.this` from state. Preview must show no destruction
before applying; never recreate the gateway merely to change its Terraform provider.

For AI backend managed-identity policies, set **resource audiences**, not `/.default`
scopes. Commercial commonly uses `https://cognitiveservices.azure.com`. Microsoft
explicitly documents Azure OpenAI Government's audience/scope as
`https://cognitiveservices.azure.us` (scope `https://cognitiveservices.azure.us/.default`) in the
[Microsoft Azure OpenAI SDK sovereign-cloud guidance](https://learn.microsoft.com/dotnet/api/overview/azure/ai.openai-readme).
Do not assume the same audience for every AI service merely from `.azure.us` hostnames:
each service has an explicit `*_TOKEN_AUDIENCE` input. Validate the selected Government
service's Entra audience and REST API version in the target tenant before enabling it.
Endpoints for referenced accounts must be copied from that account's properties.
New accounts use the exact endpoint returned by ARM.

[Redis Entra documentation](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-azure-active-directory-for-authentication)
documents `https://redis.azure.com/.default` (or its documented application-ID scope).
It does **not** establish a `redis.azure.us` audience. The Government input is deliberately
required and must be tenant-validated; this sample does not invent a sovereign scope.

[Government Cache retirement](https://learn.microsoft.com/azure/azure-cache-for-redis/retirement-faq)
is an explicit production gate: Basic/Standard/Premium retire September 30, 2028.
Managed Redis Government availability is not assumed. Both cloud baselines use
nonclustered/no-eviction engines; backend keys additionally use a common `{limiter}`
hash tag. Cache cold start fails closed until an administrator recovers durable counters.

## Authentication and runtime

Easy Auth validates every Function route with Entra; unauthenticated requests return 401,
including the health endpoint. No excluded route trusts a caller-supplied principal header.
APIM removes caller `X-MS-CLIENT-PRINCIPAL` on portal forwarding; App Service supplies
the validated header. Gateway workload calls use a distinct UAMI and `RateLimit.Gateway`
application role. The API registration separately exposes `RateLimit.Admin` and
`RateLimit.Reader`; the deployer is initially assigned Admin. The public SPA registration
has the generated `access_as_user` scope with explicit consent and redirect URLs.
Browser requests must use APIM `/portal`, whose CORS policy handles preflight before
JWT validation; a direct Function browser integration is not configured.

Function settings: `AZURE_CLOUD`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `TABLE_ENDPOINT`,
`TABLE_NAME=RateLimiter`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_USERNAME` (UAMI **object**
ID), `REDIS_TOKEN_SCOPE`, `LOCAL_AUTH_ENABLED=false`, `LOCAL_STORE_ENABLED=false`,
`WEBSITE_AUTH_ENABLED=true`, identity-based `AzureWebJobsStorage__credential/clientId`
and exact ARM-returned `AzureWebJobsStorage__blobServiceUri/queueServiceUri/tableServiceUri`
(avoiding reliance on Global-cloud account-name shorthand),
and `APPLICATIONINSIGHTS_CONNECTION_STRING`. `MAX_INPUT_TOKENS` comes from
`hosting.max_input_tokens`; `MAX_OUTPUT_TOKENS` comes from `gateway.max_output_tokens`.
These settings align backend validation with gateway admission; the portal does not need
provider credentials or protocol configuration.

Portal settings: `AZURE_CLOUD`, `AZURE_TENANT_ID`, `WEB_CLIENT_ID`, `API_AUDIENCE`,
`API_SCOPE=api://<limiter-app-id>/access_as_user`, `API_BASE_URL=https://<gateway>/portal`.
Root outputs export service names for azd, API identifiers, portal/gateway URLs, and
telemetry/data endpoints. Application Insights connection information and private
data-plane endpoint outputs are sensitive. `LLM_GATEWAY_ROUTES` publishes enabled client
paths, protocol names, pinned models, backend paths and protocol-specific versions.

## Observability and validation

Supported resource logs and metrics are discovered and sent to the shared workspace
for APIM, compute plans/apps, storage and all four subservices, Redis, AI accounts,
and the workspace. Resource-specific tables use `Dedicated`. Workspace-based
Application Insights writes application telemetry directly to that workspace.
Do not add a diagnostic export from Application Insights back to its linked workspace:
this duplicates telemetry and is an
[unsupported destination](https://learn.microsoft.com/azure/azure-monitor/platform/diagnostic-settings#diagnostic-settings-for-application-insights).
UAMIs, Entra registrations, RBAC assignments and private endpoints do not expose
resource diagnostic categories; their changes are covered by platform Activity Logs
(subscription-level export remains the landing-zone owner's responsibility).
Function Insights integration and APIM application diagnostics are configured without
logging request/response bodies, auth headers, subscription keys, or document content.

```sh
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate -json
terraform -chdir=infra test
tflint --chdir=infra --recursive
uv run --frozen python -W error -m unittest discover -s apim/tests -v
```

These are offline structural/schema checks, not proof of regional quota, successful
Entra issuance, APIM's server-side policy compiler, policy-managed DNS convergence,
or a working deployment. Before production, run a configured private-network smoke
test for identity rejection, allow/deny, actual settlement, streaming conservative
finalization, Redis recovery, and cross-principal document-poll rejection.
