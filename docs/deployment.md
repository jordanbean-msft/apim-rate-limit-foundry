# Deployment

<!-- TODO: Update with project-specific deployment details. -->

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Terraform >= 1.9](https://developer.hashicorp.com/terraform/install)

## Azure Authentication

```bash
az login
azd auth login
```

## Configure Remote State

```bash
azd env set RS_RESOURCE_GROUP <resource-group-name>
azd env set RS_STORAGE_ACCOUNT <storage-account-name>
azd env set RS_CONTAINER_NAME <container-name>
```

## Configure Environment

```bash
azd env set AZURE_LOCATION <region>
azd env set AZURE_RESOURCE_GROUP <resource-group-name>
azd env set AZURE_PRINCIPAL_ID <your-entra-object-id>
```

## Provision Infrastructure

```bash
azd provision
```

## Deploy Application

```bash
azd deploy
```

## Full Provision + Deploy

```bash
azd up
```

## GitHub Actions

Deployment workflows are available under `.github/workflows/`:

- `deploy-application.yml` — deploys application code via `azd deploy`
- `deploy-terraform.yml` — provisions infrastructure via `azd provision`

Both require repository secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, and `AZURE_CLIENT_SECRET`.
