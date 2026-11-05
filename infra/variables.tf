variable "azure" {
  description = "Pre-existing deployment context; the resource group is never created."
  type = object({
    subscription_id     = string
    tenant_id           = string
    location            = string
    environment_name    = string
    resource_group_name = string
    principal_id        = string
  })
  validation {
    condition = var.azure_cloud == "AzureUSGovernment" ? contains(
      ["usgovvirginia", "usgovarizona", "usgovtexas"], lower(var.azure.location)
    ) : !startswith(lower(var.azure.location), "usgov")
    error_message = "The deployment region must belong to the selected Azure cloud."
  }
}
variable "azure_cloud" {
  description = "Explicit sovereign cloud selection."
  type        = string
  validation {
    condition     = contains(["AzureCloud", "AzureUSGovernment"], var.azure_cloud)
    error_message = "Use AzureCloud or AzureUSGovernment (azd/CLI cloud names)."
  }
}
variable "naming" {
  description = "Short deterministic resource prefix."
  type        = object({ project_name = string })
  validation {
    condition     = can(regex("^[a-z0-9]{1,8}$", var.naming.project_name))
    error_message = "project_name must contain 1–8 lowercase alphanumeric characters."
  }
}
variable "public_network_access_enabled" {
  description = "Explicit development opt-in. Production tfvars must set false."
  type        = bool
}
variable "network" {
  description = "Existing subnet IDs; private DNS and routing are operator/policy managed."
  type = object({
    private_endpoint_subnet_id = string
    functions_subnet_id        = string
    web_subnet_id              = string
    apim_subnet_id             = string
  })
  validation {
    condition     = var.public_network_access_enabled || alltrue([for id in values(var.network) : startswith(id, "/subscriptions/")])
    error_message = "Private deployment requires existing subnet resource IDs for every service."
  }
}
variable "monitoring" {
  description = "Explicit shared telemetry specifications."
  type = object({
    sku               = string
    retention_in_days = number
  })
}
variable "hosting" {
  description = "Portable Linux Premium/Dedicated function and Node App Service specifications."
  type = object({
    functions_sku       = string
    web_sku             = string
    python_version      = string
    node_version        = string
    function_workers    = number
    web_workers         = number
    minimum_tls_version = string
    cors_origins        = list(string)
  })
  validation {
    condition     = can(regex("^(EP[123]|[PS][0-9].*)$", var.hosting.functions_sku)) && var.hosting.python_version == "3.12"
    error_message = "Use Linux Python 3.12 on Elastic Premium or Dedicated (not Flex/Consumption)."
  }
}
variable "storage" {
  description = "Explicit durable/host storage specifications."
  type = object({
    account_tier             = string
    account_replication_type = string
    table_name               = string
  })
}
variable "redis" {
  description = "Cloud-specific nonclustered Redis, with no-eviction and Entra authentication."
  type = object({
    managed_sku         = string
    high_availability   = bool
    government_capacity = number
    minimum_tls_version = string
    token_scope         = string
  })
  validation {
    condition     = endswith(var.redis.token_scope, "/.default")
    error_message = "Set an explicitly verified Redis token scope, including /.default."
  }
}
variable "identity" {
  description = "Additional Entra role recipients and explicit propagation wait."
  type = object({
    admin_object_ids          = set(string)
    reader_object_ids         = set(string)
    propagation_wait_duration = string
  })
}
variable "gateway" {
  description = "Portable classic APIM tier, validated token audience, routing, and admission caps."
  type = object({
    sku_name                    = string
    publisher_name              = string
    publisher_email             = string
    client_audiences            = list(string)
    subscription_tenant_mapping = map(string)
    burst_calls                 = number
    burst_seconds               = number
    max_body_bytes              = number
    max_output_tokens           = number
    max_document_pages          = number
    max_language_characters     = number
    send_request_timeout        = number
    enable_optional_llm_policy  = bool
    llm_policy_verified         = bool
    llm_tokens_per_minute       = number
  })
  validation {
    condition     = can(regex("^(Developer|Premium)_", var.gateway.sku_name))
    error_message = "The shared internal-VNet baseline supports classic Developer/Premium only."
  }
  validation {
    condition     = !var.gateway.enable_optional_llm_policy || (var.gateway.llm_policy_verified && var.azure_cloud == "AzureCloud")
    error_message = "Optional llm-token-limit requires an explicitly verified Commercial capability."
  }
  validation {
    condition = (
      var.gateway.max_document_pages >= 1 && var.gateway.max_document_pages <= 20 &&
      var.gateway.max_output_tokens >= 1 && var.gateway.max_output_tokens <= 999999 &&
      var.gateway.max_language_characters >= 1 && var.gateway.max_language_characters <= 5120 &&
      var.gateway.burst_calls >= 1 && var.gateway.burst_seconds >= 1 && var.gateway.burst_seconds <= 300 &&
      var.gateway.max_body_bytes >= 1 && var.gateway.send_request_timeout >= 1 && var.gateway.send_request_timeout <= 240
    )
    error_message = "Gateway bounds must be positive and within the supported policy/service caps."
  }
  validation {
    condition = (
      length(var.gateway.client_audiences) + length(var.gateway.subscription_tenant_mapping) > 0 &&
      alltrue([for audience in var.gateway.client_audiences : can(regex("^[A-Za-z0-9:/._-]+$", audience))]) &&
      alltrue([for subscription, tenant in var.gateway.subscription_tenant_mapping :
        can(regex("^[A-Za-z0-9_-]+$", subscription)) && can(regex("^[0-9a-fA-F-]{36}$", tenant))
      ])
    )
    error_message = "Configure safe explicit token audiences or subscription-ID-to-tenant mappings."
  }
}
variable "ai" {
  description = "Create or reference each AI backend; endpoint and audience are explicit, not suffix guesses."
  type = map(object({
    enabled             = bool
    create              = bool
    resource_id         = string
    endpoint            = string
    audience            = string
    sku_name            = string
    location            = string
    deployment_name     = string
    model_name          = string
    model_version       = string
    deployment_sku      = string
    deployment_capacity = number
    api_version         = string
    price_version       = string
  }))
  validation {
    condition     = toset(keys(var.ai)) == toset(["foundry", "document-intelligence", "language"])
    error_message = "Specify foundry, document-intelligence, and language, including disabled entries."
  }
  validation {
    condition = alltrue([for item in values(var.ai) : !item.enabled || (
      (item.create || startswith(item.endpoint, "https://")) && contains(["https://cognitiveservices.azure.com", "https://cognitiveservices.azure.us"], item.audience) &&
      (item.create || startswith(item.resource_id, "/subscriptions/"))
    )])
    error_message = "Enabled AI backends require exact HTTPS endpoints, explicit resource IDs when referenced, and an explicitly verified Cognitive Services audience."
  }
  validation {
    condition = alltrue([for item in values(var.ai) : !item.enabled || (
      can(regex("^[A-Za-z0-9._-]{1,200}$", item.price_version)) &&
      can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", item.deployment_name)) &&
      (var.azure_cloud == "AzureUSGovernment" ? contains(["usgovvirginia", "usgovarizona", "usgovtexas"], lower(item.location)) : !startswith(lower(item.location), "usgov"))
    )])
    error_message = "Enabled backends require safe model/version identifiers, explicit price-version pins and cloud-appropriate regions."
  }
}
variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
