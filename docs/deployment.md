# Deployment

## Prerequisites and boundaries

Use Azure CLI, Azure Developer CLI (`azd`), Terraform 1.9+, Python 3.12/uv, and Node.js 24 LTS.
See [Azure topology and identity](azure-topology.md) for resource ownership,
network paths, role grants and the audiences used on each hop.
The [physical draw.io views](diagrams/README.md) distinguish the observed public
demo from the non-deployed private-network reference; neither proves Government
availability or compliance.
The deployment uses a **pre-created resource group**. Private mode also requires existing
subnets, appropriate delegation/routing, and private DNS configured by your Azure policies.
Do not run a private deployment from a runner that cannot reach the relevant private endpoints.

The identity provisioning resources require permission to create/manage Entra applications and
app-role assignments in addition to Azure resource deployment permissions. Assign administrators
and consumers deliberately; never grant gateway permissions to ordinary portal users.

Terraform creates a single-tenant portal registration (reusing it on later applies),
both SPA and native `/.auth/login/aad/callback` redirects, and a federated credential
trusting only the dedicated web identity. App Service requires Entra sign-in before
serving website/config/assets; MSAL separately obtains delegated limiter API tokens.
No client secret is needed. Federation uses the selected cloud's tenant issuer and
`AzureADTokenExchange` / `AzureADTokenExchangeUSGov` audience.
See Microsoft's [secretless App Service sign-in guidance](https://learn.microsoft.com/azure/app-service/configure-authentication-provider-aad#use-a-managed-identity-instead-of-a-secret).

Both Functions require Easy Auth. APIM's internal reserve/settle, ownership and
streaming calls use its managed identity with `RateLimit.Gateway`. The `/portal`
API instead forwards the user's API access token unchanged, preserving
`RateLimit.Admin`/`RateLimit.Reader` and caller scoping. Do not replace portal user
tokens with the gateway identity or enable anonymous Function access.

All APIM APIs require product subscription keys as well as Entra tokens. The
website's Node proxy retrieves its separate portal key through an App Service
Key Vault reference using the web managed identity. Browser public configuration
uses same-origin `/api`; the upstream server URL is the APIM `/portal` API.
Never put a key into browser runtime JSON, application telemetry or a URL.
Graph own-photo access uses separate delegated `User.Read` consent and a
same-cloud Graph token; a missing/denied photo falls back to initials.

The in-app **Azure dashboard** reuses the deployed Azure dashboard and workspace.
Terraform supplies its three fixed resource/customer-ID settings and grants the
Function identity dashboard-scoped Reader plus workspace-scoped Log Analytics
Reader. No additional browser permissions are needed. Verify the Admin-only
`GET /portal/dashboard?period=24h` returns 22 tile results without errors after
RBAC propagation; Readers must receive 403. Query failures must remain explicit,
not silently replaced with fixture charts.

## Application-subscription cutover

Back up current configuration and preserve the immutable ledger before switching
an existing per-user deployment. Stop/fail-close inference during the coordinated
API, gateway and configuration cutover; do not operate mixed identity versions.

1. Provision the separate inference/portal products, explicit application
   subscriptions, Key Vault reference and non-secret `APPLICATION_REGISTRY`.
   Review that existing Foundry resources/models are not replaced and hosting
   changes do not reconcile unrelated live drift.
2. Deploy compatible backend, streaming and portal code and the APIM policies.
   The supported portal runtime is `NODE|24-lts`, not the expiring Node 22 line.
   Verify Key Vault resolution and native website/API authentication before
   opening traffic.
3. Replace per-user policies/assignments using an **explicit, reviewed mapping**
   to registered subscription IDs. New policies require `subscription_id`;
   assignments require that ID and explicit `reader_principal_ids`. Missing
   legacy selectors must never become wildcards. Save backups and migration
   audit evidence; do not erase or relabel historical per-user consumption.
4. Publish reviewed price cards for every active alias/version, then verify the
   registry pins. Real managed model deployments and their prices are separate
   from the invented examples. Recover the new accounting namespace through the
   protected API; do not flush Redis or erase old liabilities to initialize it.
5. Verify missing/invalid token/key and wrong-product rejection; same-subscription
   sharing across keys/users; isolation across subscriptions; Reader ACLs; model
   invocation, settlement and denial reports. Only then resume application traffic.

Historical requests without a provable application identity are not attributable
to a subscription. Keep them as historical evidence, excluded from current
application totals rather than guessed. Reconcile any outstanding legacy holds
as an explicit operational cutover decision. The new portal key is never an
inference application or a substitute for the user's Admin/Reader role.

For exported JSON configuration, preview the explicit migration before writing:

```bash
uv run python tools/migrate_application_config.py \
  --policies policies.json --assignments assignments.json --mapping mapping.json
```

`mapping.json` contains exactly `policies` and `assignments` objects, mapping every
legacy record ID to a concrete registered subscription ID. No wildcard or inferred
mapping is accepted. Add `--apply --acknowledge-legacy-liabilities` only after review;
the helper saves backups and a cutover manifest and does not change usage or
liabilities. Publish the reviewed records with the authenticated administration API.

Verify service/SKU/model/API-version availability and quota in the selected region. Azure
Government Foundry does not have every Commercial feature. This sample does not depend on
Foundry Agents or serverless model endpoints.
Microsoft documents Foundry in US Gov Virginia and US Gov Arizona; check its current
[Government feature matrix](https://learn.microsoft.com/azure/foundry/concepts/foundry-azure-government)
and verify the selected model/deployment rather than assuming Commercial parity.

## Upgrade an existing OpenAI account

The managed Foundry backend is now an `AIServices` account with project management
enabled and a dedicated user-assigned identity. Microsoft supports upgrading
`OpenAI` to `AIServices` **in place** with AzureRM >= 4.56.0; this repository pins
5.13.x. Keep the existing Terraform address, account name/custom subdomain,
resource ID, model deployment and captured `FOUNDRY_RESOURCE_ID`.

Preview with `azd provision --preview` and inspect the plan: the account must be
an **in-place update**, never a delete/create. Review all other changes before
`azd provision`. Preserve unrelated live drift rather than running an unrestricted
apply. The migration does not add model capacity, accept provider terms, create a
project, grant broader inference roles or change price pins.
After provisioning, compare actual hosting settings with the recorded baseline:
provider app-settings updates can reapply configured site defaults even when the
preview shows no site-configuration change.

The existing `.openai.azure.com` / `.openai.azure.us` inference endpoints remain
valid on Foundry; OpenAI is the wire protocol, not an assertion of resource kind.
Terraform explicitly selects this inference origin for created accounts, so
Chat and Responses do not accidentally use a general endpoint or `/api/projects`
URL. Referenced Foundry deployments still require verified endpoints/audiences.

**Private upgrades need extra review:** existing private endpoints must be
updated/recreated for Foundry's additional IP configurations. Have your network
team verify all applicable `openai`, `services.ai` and `cognitiveservices` private
DNS names. DNS zone groups/links remain DINE-policy managed, not Terraform-owned.
Do not delete private endpoints or enable public access as an implicit workaround.
Verify `AIServices`, project-management and model availability in the selected
Government region; Commercial upgrade evidence is not Government certification.

See Microsoft's [upgrade guidance](https://learn.microsoft.com/azure/foundry/how-to/upgrade-azure-openai).

## LLM protocol capabilities

To add multiple approved referenced deployments, follow the
[model registry workflow](model-registry.md). `LLM_MODELS` is an azd JSON input
for Terraform's `llm_models`; existing singular inputs remain compatible.
Deploy registry pin changes with `azd provision` and `azd deploy`.

Chat Completions, Responses and Messages are distinct API contracts; a deployment exposing one
does not automatically expose the others. Enable only routes verified against the actual target
resource/model/API version. Use the explicit protocol capabilities and backend settings documented
in `infra/README.md` and `infra/environment.example.json`.
`ENABLE_RESPONSES` and `ENABLE_ANTHROPIC` are false in the example environment until verified.
Government Responses additionally requires `RESPONSES_GOVERNMENT_VERIFIED`; Government Anthropic
enablement is rejected rather than silently using a Commercial backend.

Responses forwards to the configured OpenAI Responses backend with its own API version/audience
requirements, not a Chat Completions URL with a different JSON body. The sample uses bounded,
stateless input and does not expose stored-response retrieval or background work.

Messages references an existing, separately approved Anthropic-compatible Foundry deployment.
The sample does not silently provision an OpenAI account and call it Claude, accept Marketplace
terms for you, or copy a Commercial Claude endpoint into a Government environment. Verify model
hosting/data-residency terms, regional availability, managed-identity RBAC, version headers,
and network access. The managed-identity route does not use a client-supplied Anthropic API key.
`ANTHROPIC_VERSION` pins the provider header; `RESPONSES_API_VERSION` independently pins
`v1` or `preview`, not Chat's dated version.

For Messages, verify the configured input ceiling covers the actual model context bound and that
the Function's admission maximum accommodates it. This route reserves the full verified ceiling,
not an unproven OpenAI byte-token estimate. Publish read, uncached-input, both cache-write TTL
prices, output prices and a matching model policy before enabling traffic. Conservative streaming
charges can therefore be much larger than short prompts' eventual actual charges.

## Select the cloud before login

For Commercial:

```bash
az cloud set --name AzureCloud
azd config set cloud.name AzureCloud
az login
azd auth login
```

For Government:

```bash
az cloud set --name AzureUSGovernment
azd config set cloud.name AzureUSGovernment
az login
azd auth login
```

Authenticate Terraform to the **same** cloud/subscription/tenant. Configure the Terraform
provider environment and remote-state environment from the selected cloud, not simply endpoint
suffixes. Never use public-cloud fallback for a Government configuration.

## Configure azd and remote state

Create/select an environment and set explicit values:

```bash
azd env new dev
azd env set AZURE_CLOUD AzureCloud
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_TENANT_ID <tenant-id>
azd env set AZURE_LOCATION <supported-region>
azd env set AZURE_RESOURCE_GROUP <existing-resource-group>
azd env set AZURE_PRINCIPAL_ID <deployer-object-id>
azd env set RS_RESOURCE_GROUP <existing-state-resource-group>
azd env set RS_STORAGE_ACCOUNT <existing-state-account>
azd env set RS_CONTAINER_NAME <existing-state-container>
```

Set `AZURE_CLOUD` to `AzureUSGovernment` for Government. Read **every placeholder** in
`infra/main.tfvars.json` and `infra/provider.conf.json` before provisioning; the files are the
source of deployment sizing/network/runtime choices. Supply required API audiences, application
registrations, backend endpoints/deployments, networking, and explicit service sizes as applicable.
Do not assume these core values alone are enough.

The existing state account/container must support Entra data-plane access for the deployment
identity. Remote state may contain sensitive infrastructure configuration; restrict access.
Do not check generated `.azure/` state, `.env`, or local Terraform state into source control.

## Validate, provision, deploy

```bash
uv sync --extra dev
npm --prefix web ci
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
azd provision
azd deploy
```

Terraform validation checks syntax/provider schema, not actual regional capacity, role propagation,
private DNS resolution, or model quota. Review the Terraform plan and Azure policy implications
before accepting provisioning.

After provisioning:

1. Assign the portal admin/reader roles to intended users/groups and verify access-token audiences.
2. Verify APIM can reach and authenticate to the Function and AI endpoints over the selected network.
3. Configure model/service price cards and rules using the portal. The seed catalog is illustrative;
   replace it with approved regional/contract pricing before admitting real traffic.
4. Initialize/recover durable counter state through the documented protected administration path.
   Never delete a Redis marker or reset live counters to bypass recovery.
5. Test the gateway for allow, deny, backend errors, actual JSON/stream settlement,
   conservative missing-usage behavior, cached usage, Language records, and Document Intelligence polling.
6. Confirm required platform diagnostics reach the selected cloud's Log Analytics workspace.

The normal azd deployment includes `api`, `stream`, and `web`. If
`streaming.enabled=false`, deploy only `api` and `web`; there is no stream resource
to target. Follow the [packaging/output reference](../infra/README.md#service-packaging-and-outputs).
Use the [operator walkthrough](rate-limiting-walkthrough.md) for a controlled
configuration/allow/deny exercise and [observability](observability.md) for charts.

## Government lifecycle gate

Commercial's Azure Managed Redis is not currently documented as available in Government.
The Government path uses Azure Cache for Redis while supported; its currently published retirement
is **September 30, 2028**. An interface around Redis does not remove this operational dependency.
Revalidate current Microsoft availability guidance and approve a migration/replacement before a
production commitment. Do not promise perpetual Government deployment support.

Likewise, do not assume APIM v2/AI analytics, Foundry model providers, APIs, or private-network SKUs
have cross-cloud parity. Use the supported baseline or explicitly opt into a verified capability.

## GitHub Actions

Deployment workflows are **manual**, environment-scoped, and use OIDC rather than client secrets.
Configure GitHub environment protection and federated identity credentials for each target
environment. For private deployment targets, set the repository variable `DEPLOY_RUNNER` to an
appropriately networked self-hosted runner label; the default `ubuntu-latest` runner cannot reach
your private SCM or data endpoints.

Environment variables:

| GitHub environment variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | Federated deployment identity client ID |
| `AZURE_TENANT_ID` | Target Entra tenant |
| `AZURE_SUBSCRIPTION_ID` | Target subscription |
| `AZD_ENV_JSON` | JSON object of explicit azd variable names to **string** values |

Start with `infra/environment.example.json`. `AZD_ENV_JSON` must contain the complete values required by the Terraform/azd configuration,
including remote-state coordinates. For application-only deployment, include the provisioned
service resource names/IDs expected by azd; an ephemeral CI runner has no local `.azure/` state.
Also include `ARM_ENVIRONMENT` (`public` or `usgovernment`) for the state backend/provider.
The selected workflow cloud and environment cannot be overridden by conflicting JSON values.
Do not place secrets in repository/environment variables; this sample uses managed identity.

## Live validation status

Local test/build/provider-schema checks do not constitute a live Azure deployment. Deployment
smoke testing requires actual target subscriptions, models, Entra assignments, private network
connectivity, and approved prices in **each** cloud. Run and record those checks before promotion.
