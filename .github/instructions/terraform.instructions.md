---
description: Terraform infrastructure-as-code standards for this repository
applyTo: "infra/**/*.tf"
---

## Tooling and orchestration

- Use **Terraform** (not Bicep or ARM) for all Azure infrastructure.
- Use **Azure Developer CLI (azd)** to orchestrate provisioning (`azd provision`) and deployment (`azd deploy`).
- Store remote state in **Azure Blob Storage** via an `azurerm` backend. Backend configuration is supplied through `infra/provider.conf.json` with `${RS_*}` and `${AZURE_ENV_NAME}` placeholders that azd substitutes at runtime.
- Variable values are supplied through `infra/main.tfvars.json` with `${VAR_NAME}` placeholders that azd substitutes from its environment. This is the primary mechanism for passing configuration from azd to Terraform.
- Before provisioning, the operator sets remote state coordinates: `azd env set RS_RESOURCE_GROUP <rg>`, `azd env set RS_STORAGE_ACCOUNT <sa>`, `azd env set RS_CONTAINER_NAME <container>`.
- Always look up the latest stable versions of Terraform providers during development before pinning.

## Formatting and validation

- Format every Terraform change during development with `terraform -chdir=infra fmt -recursive`.
- Before considering a Terraform change complete, run `terraform -chdir=infra fmt -check -recursive` and `terraform -chdir=infra validate`.
- Run `terraform -chdir=infra init -backend=false` before validation when the working directory has not been initialized or provider/module requirements have changed.
- Treat Terraform warnings as failures. A Terraform change is complete only when formatting checks and validation finish with zero errors and zero warnings.
- Resolve all formatting and validation findings caused by the change; do not suppress, ignore, or defer them.

## Azure Developer CLI (azd) variable flow

- azd owns the lifecycle of environment variables. Terraform receives them via `main.tfvars.json` placeholder substitution.
- Core Azure context variables are supplied by azd automatically or set by the operator:
  - `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_LOCATION` — set during `azd init` or `azd env set`.
  - `AZURE_ENV_NAME` — the azd environment name (e.g., `dev`, `prod`).
  - `AZURE_RESOURCE_GROUP` — the target resource group.
  - `AZURE_PRINCIPAL_ID` — the deployer's Entra object ID (used for RBAC bootstrapping).
- Additional variables (networking, service-specific config) are set via `azd env set` and referenced in `main.tfvars.json`:
  ```json
  {
    "azure": {
      "subscription_id": "${AZURE_SUBSCRIPTION_ID}",
      "tenant_id": "${AZURE_TENANT_ID}",
      "location": "${AZURE_LOCATION}",
      "environment_name": "${AZURE_ENV_NAME}",
      "resource_group_name": "${AZURE_RESOURCE_GROUP}",
      "principal_id": "${AZURE_PRINCIPAL_ID}"
    }
  }
  ```
- Terraform root-module outputs are automatically captured by azd and made available as environment variables for subsequent `azd deploy` steps and service configuration.
- Assume every useful child-module output will be mapped by the root module to the canonical environment-variable name expected by azd. When azd defines or conventionally expects a name for a value, always use that exact name instead of inventing a project-specific alternative. For example, expose an Azure Container Registry name as `AZURE_CONTAINER_REGISTRY` and its login server as `AZURE_CONTAINER_REGISTRY_ENDPOINT`.
- When adding infrastructure that produces values needed by the application or by azd service mappings, add corresponding root-module outputs with canonical azd-compatible SCREAMING_SNAKE_CASE names.

## Provider configuration

- Require `terraform >= 1.9`.
- Pin providers with pessimistic constraints (`~>`) in both root and child modules.
- Commonly used providers: `azurerm`, `azurecaf`, `azuread`, `azapi`, `random`, `time`.
- Use `azapi` when a resource or property is not yet supported by `azurerm`.
- Configure `azurerm` with `storage_use_azuread = true` for Entra-based storage auth.
- Set `features` block: `purge_soft_delete_on_destroy = false`, `recover_soft_deleted_key_vaults = true`, `prevent_deletion_if_contains_resources = true`.
- Declare `backend "azurerm" {}` with no inline config; all values come from `provider.conf.json`.

## Resource group convention

- **Never create the resource group in Terraform.** Assume the resource group is pre-created and passed in via `var.azure.resource_group_name`.
- Reference the resource group with a data source:
  ```hcl
  data "azurerm_resource_group" "rg" {
    name = var.azure.resource_group_name
  }
  ```
- Use `data.azurerm_resource_group.rg.name` and `data.azurerm_resource_group.rg.location` throughout.

## Azure resource implementation

- **Do not use Azure Verified Modules** (`Azure/avm-res-*`).
- Define Azure resources directly with `azurerm_*` resources whenever the AzureRM provider supports the required resource and properties.
- Use `azapi_*` resources only when the required resource or property is unavailable in `azurerm`.
- Prefer dedicated resources for role assignments, diagnostic settings, and private endpoints so their lifecycle and dependencies remain explicit.
- Pin `azurerm` and `azapi` provider versions with `~>` constraints. Look up the latest stable versions on the Terraform registry before using.

## Variable design

- Group related configuration into **typed objects** rather than using many flat variables. Deployment-specific settings must be required object attributes without Terraform defaults. Examples:
  ```hcl
  variable "azure" {
    type = object({
      subscription_id     = string
      tenant_id           = string
      location            = string
      environment_name    = string
      resource_group_name = string
      principal_id        = string
    })
  }

  variable "sql" {
    type = object({
      sku_name    = string
      max_size_gb = number
    })
  }
  ```
- Specify all deployment sizing and runtime configuration explicitly in `main.tfvars.json`. This includes SKUs, tiers, VM sizes, CPU, memory, capacity, replica counts, storage sizes, throughput, retention periods, port numbers, timeouts, and similar service-specific settings.
- Do not default deployment-specific settings in `variable` blocks, `optional()` type attributes, locals, resources, or modules. Root variables and child-module inputs for these settings must be required, and the root module must pass them explicitly.
- Keep environment-specific values as azd `${PLACEHOLDER}` entries in `main.tfvars.json`; keep fixed project choices as explicit literal values in that file. The tfvars file must remain the visible source of every deployed specification.
- Add `validation` blocks for variables that have constrained value sets or formats.
- Use a `tags` variable (`map(string)`, default `{}`) for user-provided tag overrides.
- Use a `naming` object variable with a short `project_name` (1–8 lowercase alphanumeric) for resource naming.
- Require a `public_network_access_enabled` boolean at the root, set it explicitly in `main.tfvars.json`, and propagate it to every module. This enables deliberate toggling between public-accessible and private-only deployments.
- When a new deployment-specific variable is needed, add it to `variables.tf` without a default and to `main.tfvars.json` with an azd `${PLACEHOLDER}` if operator-supplied or an explicit literal value if fixed per project.

## Naming conventions

- Use the `azurecaf` provider (`azurecaf_name` resources) to generate Azure-compliant resource names.
- Derive a deterministic **resource token** from location, subscription, and resource group:
  ```hcl
  locals {
    resource_token_sha = base64encode(sha256("${var.azure.location}${data.azurerm_client_config.current.subscription_id}${var.azure.resource_group_name}"))
    resource_token     = substr(join("", regexall("[a-z0-9]", lower(local.resource_token_sha))), 0, 13)
  }
  ```
- Pass `resource_token` to all child modules and use it as the `name` argument in `azurecaf_name`.
- Always set `random_length = 0` and `clean_input = true` for deterministic, idempotent naming.
- Use `suffixes` to distinguish resources (e.g., `["identity"]`, `["law"]`, `["stor"]`, `["plan"]`).

## Tagging

- Build `default_tags` in a `locals` block by merging a base set with user-provided `var.tags`:
  ```hcl
  locals {
    default_tags = merge(
      {
        project     = "<repo-name>"
        environment = var.azure.environment_name
        managed_by  = "terraform"
      },
      var.tags
    )
  }
  ```
- Pass `local.default_tags` (or `tags = var.tags` inside modules) to every resource and module.
- For azd-deployed services, add `azd-env-name` and `azd-service-name` tags.

## Module structure

- Organize infrastructure into **child modules** under `infra/modules/<service>/`.
- Every module contains exactly four files:
  - `providers.tf` — required providers (version-pinned, matching root constraints).
  - `variables.tf` — input variables with types, descriptions, defaults, and validations.
  - `main.tf` — resource definitions.
  - `outputs.tf` — exported values for the root to consume.
- Common module input variables: `resource_token`, `resource_group_name`, `location`, `tags`, `public_network_access_enabled`.
- Use `count` on modules to make entire service blocks optional (e.g., `count = var.app_service.enabled ? 1 : 0`).
- Use `for_each` for sets of similar resources (e.g., multiple web apps).

## Networking and private endpoints

- Assume the target virtual network and subnets already exist. Reference them with `data "azurerm_virtual_network"` and `data "azurerm_subnet"` data sources, or accept existing subnet IDs as inputs; do not create VNets or subnets in this Terraform configuration.
- Pass an existing `private_endpoint_subnet_id` into modules that need private endpoints.
- Assume the required private DNS zones already exist and are associated with Azure Deploy If Not Exists (DINE) policies that configure private endpoint DNS zone groups and virtual network links.
- Create only the private endpoints with `azurerm_private_endpoint` resources, or `azapi_resource` only when AzureRM lacks required functionality. Do not create or manage private DNS zones, private DNS virtual network links, or private DNS zone groups in Terraform.
- Every `azurerm_private_endpoint` resource, regardless of service or module, must ignore changes to its policy-managed DNS zone group:
  ```hcl
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
  ```
  This is required even when the resource does not declare a `private_dns_zone_group` block, because DINE policies add the block after endpoint creation and Terraform must not remove it or report drift.
- Name private endpoints as `{resource_name}-pe` and service connections as `{resource_name}-psc`.
- Default to private-only access (`public_network_access_enabled = false`). The root variable allows toggling for development.

## RBAC and identity

- Always favor **user-assigned managed identities** and Azure RBAC for authentication and authorization between Azure services.
- Create a user-assigned managed identity for each application or workload identity boundary, and pass its resource ID, principal ID, and client ID to every module that requires service-to-service access.
- Prefer user-assigned identities over system-assigned identities so identity lifecycle, role assignments, and reuse remain explicit and independent of a single resource.
- Use identity-based SDK authentication and service endpoints at runtime. Do not use access keys, shared secrets, embedded credentials, or connection strings containing credentials when managed identity and Azure RBAC are supported.
- Use credential-based authentication only when the target service does not support managed identity or Azure RBAC; document the limitation and store required secrets in Azure Key Vault.
- Create role assignments with `azurerm_role_assignment` resources, using `azapi_resource` only when AzureRM cannot express the required assignment.
- Apply least-privilege roles (e.g., `Storage Blob Data Contributor` not `Owner`).
- For role assignments on resources with eventual-consistency identity propagation, use `time_sleep` resources as explicit dependencies.
- Use `uuidv5("dns", ...)` for deterministic role assignment `name` fields to ensure idempotency.
- Grant the deployer principal (`var.azure.principal_id`) admin-level access for initial setup (e.g., `Key Vault Secrets Officer`).
- Grant the app identity only data-level access (e.g., `Key Vault Secrets User`, `Storage Blob Data Contributor`).

## Outputs

- Export values that downstream azd deployment or application configuration needs (connection strings, URIs, resource names).
- Mark sensitive outputs with `sensitive = true` (connection strings, instrumentation keys, FQDNs).
- Design child-module outputs with the assumption that the root module will map them to azd environment variables. Child-module output names may describe the value idiomatically, but their corresponding root-module outputs must use the expected azd names.
- Before naming a root-module output, determine whether azd has a standard or expected environment-variable name for that resource or value. If one exists, always use it exactly; only introduce a new SCREAMING_SNAKE_CASE name when azd has no applicable convention.
- Prefer azd-compatible names such as `AZURE_CONTAINER_REGISTRY` and `AZURE_CONTAINER_REGISTRY_ENDPOINT` over custom alternatives such as `ACR_NAME`, `REGISTRY_LOGIN_SERVER`, or service-prefixed variants.
- Use ternary expressions for outputs from conditional modules: `var.x.enabled ? module.x[0].output : null`.
- Terraform outputs are automatically captured by azd after `azd provision` and become available as environment variables for `azd deploy` and application runtime.

## Monitoring and diagnostics

- Always deploy a **Log Analytics Workspace** and a workspace-based **Application Insights** resource in the monitoring module. Configure Application Insights with `workspace_id` so telemetry is stored in the shared Log Analytics workspace.
- Pass the Log Analytics workspace resource ID and the Application Insights connection string to every module that needs them.
- Every Azure resource that supports Azure Monitor diagnostic settings must have a dedicated `azurerm_monitor_diagnostic_setting` resource. Do not omit diagnostics for cost, convenience, or because platform logs are not currently queried.
- Send all supported resource log categories and metrics to the shared Log Analytics workspace. Use `data "azurerm_monitor_diagnostic_categories"` when practical so newly supported categories are enabled without maintaining hard-coded category lists.
- Set `log_analytics_destination_type = "Dedicated"` when the resource supports resource-specific Log Analytics tables; use `AzureDiagnostics` only when dedicated tables are unavailable or incompatible.
- Give diagnostic settings deterministic names and keep them in the same child module as the monitored resource. Create separate diagnostic settings when Azure requires different destinations or category combinations.
- Enable native Application Insights integration for every service that supports it, including application hosting and compute services. Supply the Application Insights connection string through the service's supported configuration mechanism, enable platform or agent-based instrumentation when available, and configure application telemetry collection rather than relying only on Azure Monitor resource logs.
- Prefer `APPLICATIONINSIGHTS_CONNECTION_STRING` over instrumentation keys for application runtime configuration. Treat the connection string as sensitive in Terraform variables and outputs, and never hard-code it.
- Diagnostic settings and Application Insights integration are mandatory acceptance criteria for every new or modified Azure service. If a resource supports neither capability, document that limitation in the Terraform module.

## General best practices

- Use `data` sources to reference pre-existing resources (VNets, subnets, resource groups) — never recreate shared infrastructure.
- Prefer explicit `depends_on` over implicit dependency when ordering matters for identity propagation or RBAC.
- Keep modules focused on a single Azure service or logical grouping.
- Add descriptions to all variables, outputs, and complex locals.
- Use `lifecycle { ignore_changes = [...] }` sparingly and only for properties managed outside Terraform, including private endpoint DNS zone groups managed by Azure DINE policies.
