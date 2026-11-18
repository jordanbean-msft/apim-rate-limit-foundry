---
title: Deployment
description: Prepare, provision and deploy the gateway with azd, Terraform and GitHub Actions.
---

## Deployment sequence

Deployment uses **azd + Terraform** with remote state in Azure Blob Storage.
The resource group, network and private DNS policies are pre-created.
Do not provision directly from an unconfigured environment.

1. Select the intended Azure cloud, tenant, subscription, region and existing group.
2. Set azd remote-state coordinates (`RS_RESOURCE_GROUP`, `RS_STORAGE_ACCOUNT`,
   `RS_CONTAINER_NAME`) and explicit infrastructure inputs.
3. Configure OpenAI deployment aliases, price versions, Event Hub sizing/retention,
   Function Event Hub sender identity, private connectivity and portal identity.
4. For existing deployments, back up configuration, usage and Terraform state.
   Review schema compatibility and explicitly approve any reset of operational
   spend; persisted history is not replayed into Redis.
5. Run local validation and review the Terraform plan, especially resource
   deletions/replacements. Preserve unrelated hosting drift and existing model
   deployments unless intentionally changing them.
6. Run `azd provision` and `azd deploy` only against that reviewed environment.
7. Configure reviewed organization/assignment/price/budget records through the
   authenticated portal API. The separate [demo loader](../demo/README.md)
   defaults to preview and only applies to explicitly isolated stores.
8. Verify cold configuration loading, warm Redis-only admission and Admin cache
   invalidation; execute the [operational acceptance checks](operations.md).
   No automatic ledger rebuild initializes or restores Redis spend.

## Models and runtime configuration

The managed model account is direct Azure OpenAI (`OpenAI`, S0), not a Foundry
project/ML hub. Routing preserves the native `.openai.azure.com` origin in
Commercial and the explicitly verified sovereign equivalent in Government.
The current native APIM backend-ID routing is retained.

Aliases may list `additional_endpoints` for the same model. Terraform then creates
native APIM backends with circuit breakers and a pool resource (via `azapi`, since
`azurerm` has no pool resource) for those aliases only. Before applying: deploy the
same deployment name on each extra account, grant the APIM gateway identity its
OpenAI User role there, and confirm APIM network/DNS reach it. Converting an alias
between single and pooled creates new backends and deletes the old one; plan to see
this. Streaming still uses the primary endpoint through the relay (no failover).
Tune `gateway.backend_circuit_breaker` in `main.tfvars.json`.

The budget and streaming Functions publish usage events to Event Hubs with their
managed identity, not a connection string secret. Verify the Function's Sender
RBAC, `EVENT_HUB_FQDN`/`EVENT_HUB_NAME` and network reachability, including
private networking. Acceptance/export does not prove Table persistence.

Before allowing traffic, accept the
[operational data-loss contract](operations.md): Redis is the live budget
authority, and process-local history/export jobs are not durable.
The [configuration reference](configuration-reference.md#runtime-groups) owns
runtime TTLs and bounds. Terraform supplies the same cache settings to both
Function hosts; both enable Always On, which does not make background jobs durable.

Terraform modules configure deployed application settings directly; azd captures
root outputs for service deployment targeting and operator use. See the
[infrastructure reference](../infra/README.md) for exact variables. Never deploy
local auth bypasses, copy `.env` to Function settings, or expose the portal's
server product key to the browser.

Disabling `streaming.enabled` removes the streaming site and rejects streaming at
the gateway, but [azure.yaml](../azure.yaml) still declares the `stream` service.
An unqualified `azd deploy` assumes all declared services exist. When streaming
is disabled, deploy only `api` and `web` with `azd deploy api` and `azd deploy web`;
the stock application deployment workflow also assumes the streaming site exists.

## GitHub Actions deployment

The [Terraform workflow](../.github/workflows/deploy-terraform.yml) provisions
resources; the [application workflow](../.github/workflows/deploy-application.yml)
packages/deploys the hosts without loading demo data. Configure the GitHub
environment with `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID` and `AZD_ENV_JSON`. The workflows use OIDC
(`id-token: write`) and run
[`scripts/configure_ci.py`](../scripts/configure_ci.py) without arguments.
That script reads environment variables and creates/configures the azd
environment; it does not provision resources. `AZD_ENV_JSON` must be a nonempty
JSON object with uppercase keys and string values.

Set `DEPLOY_RUNNER` to a runner with the required private routes and DNS for
private deployments. OIDC authentication does not provide network access.
Fresh application runners restore the provisioned service-target outputs into
the azd environment before deployment; preserve this step when adapting the
workflow.

## Acceptance boundary

Cloud parity, interactive MFA/client integration and live policy compilation must
be verified in the target environment. This sample makes no GCCH/FedRAMP
certification, strict spending-cap or exactly-once Event Hub delivery claim.

Start at the [README](../README.md) for environment setup, consult
[topology](azure-topology.md) for network/identity responsibilities and use
[operations](operations.md) for post-deployment checks.
