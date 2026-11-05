# Deployment

## Prerequisites and boundaries

Use Azure CLI, Azure Developer CLI (`azd`), Terraform 1.9+, Python 3.12/uv, and Node.js 22+.
The deployment uses a **pre-created resource group**. Private mode also requires existing
subnets, appropriate delegation/routing, and private DNS configured by your Azure policies.
Do not run a private deployment from a runner that cannot reach the relevant private endpoints.

The identity provisioning resources require permission to create/manage Entra applications and
app-role assignments in addition to Azure resource deployment permissions. Assign administrators
and consumers deliberately; never grant gateway permissions to ordinary portal users.

Verify service/SKU/model/API-version availability and quota in the selected region. Azure
Government Foundry does not have every Commercial feature. This sample does not depend on
Foundry Agents or serverless model endpoints.

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
5. Test the gateway for allow, deny, backend errors, actual settlement, streaming conservative
   accounting, cached usage, Language records, and Document Intelligence operation polling.
6. Confirm required platform diagnostics reach the selected cloud's Log Analytics workspace.

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
