# Infrastructure operator notes

This is a non-production reference deployment. No resources are provisioned by validation.
`azure.yaml` packages the **root** Python Function host and the portal's `dist/`,
`server/`, and `package.json`. Run azd from the repository root. The Function prepackage
hook exports `requirements.txt` with uv; do not commit generated credentials or state.
The portal uses `node server/index.mjs` and has no runtime npm dependencies.
Its prepackage hook stages only those three artifacts under ignored `infra/.artifacts/web`,
excluding test sources and npm development dependencies from the App Service package.

## Required configuration

Set every `${PLACEHOLDER}` in `main.tfvars.json` and `provider.conf.json` in the azd
environment. Unused service strings may be explicitly empty, but enable/create flags
must always be explicit `true`/`false`. Set `PUBLIC_NETWORK_ACCESS_ENABLED=false`
normally; `true` is a deliberate public development exception, never a fallback.
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
| `ENABLE_DOCUMENT_INTELLIGENCE`, `CREATE_DOCUMENT_INTELLIGENCE`, `DOCUMENT_INTELLIGENCE_RESOURCE_ID`, `DOCUMENT_INTELLIGENCE_ENDPOINT`, `DOCUMENT_INTELLIGENCE_LOCATION`, `DOCUMENT_INTELLIGENCE_TOKEN_AUDIENCE` | Optional Document Intelligence backend |
| `ENABLE_LANGUAGE`, `CREATE_LANGUAGE`, `LANGUAGE_RESOURCE_ID`, `LANGUAGE_ENDPOINT`, `LANGUAGE_LOCATION`, `LANGUAGE_TOKEN_AUDIENCE` | Optional Language sentiment backend |
| `FOUNDRY_PRICE_VERSION`, `DOCUMENT_INTELLIGENCE_PRICE_VERSION`, `LANGUAGE_PRICE_VERSION` | Explicit operator-pinned catalog versions; creating a new price version does not silently change admission pricing |

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
and `APPLICATIONINSIGHTS_CONNECTION_STRING`.

Portal settings: `AZURE_CLOUD`, `AZURE_TENANT_ID`, `WEB_CLIENT_ID`, `API_AUDIENCE`,
`API_SCOPE=api://<limiter-app-id>/access_as_user`, `API_BASE_URL=https://<gateway>/portal`.
Root outputs export service names for azd, API identifiers, portal/gateway URLs, and
telemetry/data endpoints. Application Insights connection information and private
data-plane endpoint outputs are sensitive.

## Observability and validation

Supported resource logs and metrics are discovered and sent to the shared workspace
for APIM, compute plans/apps, storage and all four subservices, Redis, AI accounts,
Application Insights, and the workspace. Resource-specific tables use `Dedicated`.
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
uv run python -W error -m unittest discover -s apim/tests -v
```

These are offline structural/schema checks, not proof of regional quota, successful
Entra issuance, APIM's server-side policy compiler, policy-managed DNS convergence,
or a working deployment. Before production, run a configured private-network smoke
test for identity rejection, allow/deny, actual settlement, streaming conservative
finalization, Redis recovery, and cross-principal document-poll rejection.
