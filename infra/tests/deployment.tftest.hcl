mock_provider "azurerm" {
  override_during = plan
  mock_data "azurerm_resource_group" {
    defaults = {
      name = "sample-rg", location = "usgovvirginia"
      id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "00000000-0000-0000-0000-000000000001"
      tenant_id       = "00000000-0000-0000-0000-000000000002"
      object_id       = "00000000-0000-0000-0000-000000000003"
    }
  }
  mock_resource "azurerm_service_plan" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Web/serverFarms/sample-plan"
    }
  }
  mock_resource "azurerm_managed_redis" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Cache/redisEnterprise/sample-redis"
      hostname = "sample.example.net", default_database = [{ port = 10000 }]
    }
  }
  mock_resource "azurerm_redis_cache" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Cache/redis/sample-redis"
      hostname = "sample.redis.cache.usgovcloudapi.net", ssl_port = 6380
    }
  }
  mock_resource "azurerm_eventhub_namespace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.EventHub/namespaces/sample-events"
    }
  }
  mock_resource "azurerm_eventhub" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.EventHub/namespaces/sample-events/eventhubs/usage"
    }
  }
  mock_resource "azurerm_cognitive_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/foundry"
    }
  }
}
mock_provider "azuread" {}
mock_provider "azapi" {
  override_during = plan
  mock_resource "azapi_resource" {
    defaults = {
      id     = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.ApiManagement/service/sample-gateway"
      output = { properties = { gatewayUrl = "https://sample-gateway.azure-api.us" } }
    }
  }
}
mock_provider "azurecaf" {
  override_during = plan
  mock_resource "azurecaf_name" {
    defaults = { result = "sample-resource" }
  }
}
mock_provider "time" {}
override_module {
  target = module.identity
  outputs = {
    function = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/function"
      client_id    = "00000000-0000-0000-0000-000000000004"
      principal_id = "00000000-0000-0000-0000-000000000005"
    }
    gateway = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gateway"
      client_id    = "00000000-0000-0000-0000-000000000006"
      principal_id = "00000000-0000-0000-0000-000000000007"
    }
    web = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/web"
      client_id    = "00000000-0000-0000-0000-000000000008"
      principal_id = "00000000-0000-0000-0000-000000000009"
    }
    api_client_id = "00000000-0000-0000-0000-000000000010"
    api_audience  = "api://00000000-0000-0000-0000-000000000010"
    web_client_id = "00000000-0000-0000-0000-000000000011"
  }
}
override_module {
  target = module.monitoring
  outputs = {
    workspace_id                     = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.OperationalInsights/workspaces/sample"
    workspace_customer_id            = "00000000-0000-0000-0000-000000000012"
    dashboard_id                     = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Portal/dashboards/sample"
    app_insights_id                  = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Insights/components/sample"
    app_insights_connection_string   = "InstrumentationKey=00000000-0000-0000-0000-000000000012"
    app_insights_instrumentation_key = "00000000-0000-0000-0000-000000000012"
  }
}
override_module {
  target = module.storage
  outputs = {
    id             = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Storage/storageAccounts/sample"
    name           = "samplestorage"
    table_endpoint = "https://sample.table.core.usgovcloudapi.net/"
    blob_endpoint  = "https://sample.blob.core.usgovcloudapi.net/"
    queue_endpoint = "https://sample.queue.core.usgovcloudapi.net/"
  }
}
override_module {
  target  = module.diagnostics
  outputs = { ids = {} }
}
variables {
  azure_cloud = "AzureUSGovernment"
  azure = {
    subscription_id = "00000000-0000-0000-0000-000000000001", tenant_id = "00000000-0000-0000-0000-000000000002",
    location        = "usgovvirginia", environment_name = "sample", resource_group_name = "sample-rg",
    principal_id    = "00000000-0000-0000-0000-000000000003"
  }
  naming                        = { project_name = "sample" }
  public_network_access_enabled = false
  network = {
    for key in ["private_endpoint_subnet_id", "functions_subnet_id", "web_subnet_id", "apim_subnet_id"] :
    key => "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/${key}"
  }
  monitoring = { sku = "PerGB2018", retention_in_days = 30 }
  event_hubs = {
    sku                 = "Standard", capacity = 1, partition_count = 2, message_retention = 7,
    minimum_tls_version = "1.2", propagation_wait_duration = "60s"
  }
  hosting = {
    functions_sku      = "P1v3", web_sku = "P1v3", python_version = "3.12", node_version = "24-lts",
    function_always_on = false, web_always_on = false, stream_always_on = true,
    function_workers   = 1, web_workers = 1, minimum_tls_version = "1.2", cors_origins = [],
    max_input_tokens   = 200000, allowed_client_applications = [], telemetry_sampling_ratio = 1,
    log_retention_days = 7, log_disk_quota_mb = 100
  }
  storage = { account_tier = "Standard", account_replication_type = "ZRS", table_name = "RateLimiter" }
  redis = {
    managed_sku        = "Balanced_B1", high_availability = true, government_capacity = 1,
    inspection_enabled = false, minimum_tls_version = "1.2", token_scope = "https://redis.azure.com/.default"
  }
  identity = { admin_object_ids = [], reader_object_ids = [], propagation_wait_duration = "60s" }
  gateway = {
    sku_name                       = "Developer_1", publisher_name = "Sample", publisher_email = "sample@example.com",
    client_audiences               = ["api://client"], burst_calls = 60, burst_seconds = 60, max_body_bytes = 1048576,
    max_output_tokens              = 4096, send_request_timeout = 10, enable_optional_llm_policy = false,
    llm_policy_verified            = false, llm_tokens_per_minute = 100000, diagnostic_sampling_percentage = 100,
    openai_byte_tokenizer_verified = true
  }
  llm_protocols = {
    responses = {
      enabled                   = false, capability_verified = false, government_verified = false, byte_tokenizer_verified = false,
      private_endpoint_verified = false, resource_id = "", endpoint = "", audience = "", location = "",
      deployment_name           = "", price_version = "", role_definition_name = "Cognitive Services OpenAI User", api_version = "v1"
    }
  }
  llm_models     = {}
  managed_models = {}
  streaming      = { enabled = true, max_event_bytes = 65536, timeout_seconds = 180 }
  applications = {
    inference = { demo-app = { tenant_id = "00000000-0000-0000-0000-000000000002", display_name = "Demo" } }
    portal    = { subscription_id = "portal-server", display_name = "Portal server" }
  }
  portal_key_vault = {
    sku_name = "standard", soft_delete_retention_days = 90, purge_protection_enabled = true, propagation_wait_duration = "60s"
  }
  ai = {
    foundry = {
      enabled       = true, create = false,
      resource_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/foundry",
      endpoint      = "https://sample.openai.azure.us", audience = "https://cognitiveservices.azure.us",
      sku_name      = "S0", location = "usgovvirginia", deployment_name = "sample-model", model_name = "",
      model_version = "", deployment_sku = "", deployment_capacity = 0, api_version = "2024-10-21", price_version = "v1"
    }
  }
}
run "government_private_openai_only" {
  command = plan
  assert {
    condition = (
      module.apim.usage_telemetry_contract.logger.hub_id == module.event_hubs.id &&
      module.apim.usage_telemetry_contract.logger.identity_client_id == module.identity.gateway.client_id &&
      endswith(module.apim.usage_telemetry_contract.logger.endpoint_address, ".servicebus.usgovcloudapi.net") &&
      module.apim.usage_telemetry_contract.callback.subscription_required == false &&
      strcontains(module.apim.usage_telemetry_contract.callback.policy, module.identity.function.principal_id) &&
      strcontains(module.apim.usage_telemetry_contract.callback.policy, module.identity.function.client_id)
    )
    error_message = "Use native managed-identity logging, sovereign EH DNS and a Function-specific callback, never user claims or secrets."
  }
  assert {
    condition = (
      keys(output.LLM_GATEWAY_ROUTES) == ["foundry"] &&
      output.LLM_GATEWAY_ROUTES.foundry.path == "/foundry/chat/completions" &&
      keys(module.apim.ai_backends) == ["ai-foundry", "ai-model-${substr(sha256("openai-chat:sample-model"), 0, 12)}"] &&
      local.authority == "https://login.microsoftonline.us"
    )
    error_message = "Keep the Chat route, deterministic backend entities and sovereign auth; no removed APIs."
  }
  assert {
    condition = (
      module.apim.subscription_contract.portal_api.subscription_required &&
      alltrue([for api in values(module.apim.subscription_contract.inference_apis) : api.subscription_required]) &&
      keys(local.ai_diagnostic_targets) == ["ai-foundry"] &&
      keys(module.stream_private_endpoints.ids) == ["stream"]
    )
    error_message = "Native product keys, OpenAI diagnostics, and private stream relay must be preserved."
  }
}
run "responses_uses_preserved_foundry_path" {
  command = plan
  variables {
    llm_protocols = {
      responses = merge(var.llm_protocols.responses, {
        enabled                   = true, capability_verified = true, government_verified = true, byte_tokenizer_verified = true,
        private_endpoint_verified = true, resource_id = var.ai.foundry.resource_id,
        endpoint                  = var.ai.foundry.endpoint, audience = var.ai.foundry.audience, location = var.ai.foundry.location,
        deployment_name           = "sample-model", price_version = "v1"
      })
    }
  }
  assert {
    condition = (
      keys(output.LLM_GATEWAY_ROUTES) == ["foundry", "responses"] &&
      output.LLM_GATEWAY_ROUTES.responses.path == "/foundry/responses" &&
      keys(local.registry_protocol_keys) == ["openai-chat", "openai-responses"] &&
      length(module.ai.protocol_role_assignment_ids) == 0 &&
      keys(local.ai_diagnostic_targets) == ["ai-foundry"]
    )
    error_message = "Both OpenAI protocols share existing RBAC/diagnostics without duplicating resource bindings."
  }
}
run "created_openai_and_managed_deployments_preserve_baseline" {
  command = plan
  variables {
    ai = { foundry = merge(var.ai.foundry, {
      create         = true, resource_id = "", model_name = "gpt-4.1", model_version = "2025-04-14",
      deployment_sku = "Standard", deployment_capacity = 10
    }) }
    managed_models = {
      fast = {
        model_name = "gpt-4.1-mini", model_version = "2025-04-14", deployment_sku = "Standard", deployment_capacity = 10,
        protocols = {
          openai-chat = {
            api_version         = "2024-10-21", price_version = "fast-v1", max_input_tokens = 64000, max_output_tokens = 2048,
            capability_verified = true, government_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true
          }
        }
      }
    }
  }
  assert {
    condition = (
      module.ai.backends.foundry.endpoint == "https://sample-resource.openai.azure.us" &&
      module.ai.managed_deployments.fast.name == "fast" &&
      keys(local.model_registry) == ["openai-chat:fast"] &&
      output.LLM_GATEWAY_ROUTES.foundry.model == "" &&
      module.ai.backends.foundry.model == "sample-model"
    )
    error_message = "Keep the direct OpenAI account and preserved legacy deployment; explicit managed aliases remain real deployments."
  }
}
run "additional_openai_models_keep_alias_based_backend_entities" {
  command = plan
  variables {
    llm_models = {
      "openai-chat:fast" = {
        api_protocol            = "openai-chat", resource_id = "${var.ai.foundry.resource_id}-fast",
        endpoint                = "https://fast.openai.azure.us", audience = var.ai.foundry.audience, location = var.ai.foundry.location,
        deployment_name         = "provider-fast", price_version = "fast-v1", max_input_tokens = 64000, max_output_tokens = 2048,
        role_definition_name    = "Cognitive Services OpenAI User", capability_verified = true, government_verified = false,
        byte_tokenizer_verified = true, private_endpoint_verified = true, api_version = "2024-10-21"
      }
    }
  }
  assert {
    condition = (
      local.model_registry["openai-chat:fast"].model == "provider-fast" &&
      contains(keys(module.apim.ai_backends), "ai-model-${substr(sha256("openai-chat:fast"), 0, 12)}") &&
      length(module.ai.stream_role_assignments) == 2
    )
    error_message = "Additional aliases must route to registered deployment entities and grant the relay only scoped OpenAI access."
  }
}
