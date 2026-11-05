# Configuration Reference

<!-- TODO: Update with project-specific configuration details. -->

## Application Environment Variables

Set these in `.env` for local development or as app settings in Azure.

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `PORT` | API server port | `8000` |

## Terraform Variables

Supplied via `infra/main.tfvars.json` with `${PLACEHOLDER}` syntax for azd substitution.

### Core Azure Context

| Variable | Description | Source |
|----------|-------------|--------|
| `AZURE_SUBSCRIPTION_ID` | Azure subscription | `azd init` |
| `AZURE_TENANT_ID` | Azure AD tenant | `azd init` |
| `AZURE_LOCATION` | Azure region | `azd env set` |
| `AZURE_ENV_NAME` | Environment name (dev, prod) | `azd init` |
| `AZURE_RESOURCE_GROUP` | Target resource group | `azd env set` |
| `AZURE_PRINCIPAL_ID` | Deployer's Entra object ID | `azd env set` |

### Remote State

| Variable | Description |
|----------|-------------|
| `RS_RESOURCE_GROUP` | Resource group for state storage |
| `RS_STORAGE_ACCOUNT` | Storage account for state |
| `RS_CONTAINER_NAME` | Blob container for state |

## Terraform Outputs

Terraform outputs use SCREAMING_SNAKE_CASE and are automatically captured by azd as environment variables.

<!-- TODO: List project-specific outputs here. -->
