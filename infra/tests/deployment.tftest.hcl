mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      name     = "sample-rg"
      location = "usgovvirginia"
      id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg"
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
      hostname = "sample-redis.example.net"
      default_database = [{
        port = 10000
      }]
    }
  }
  mock_resource "azurerm_redis_cache" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Cache/Redis/sample-redis"
      hostname = "sample-redis.redis.cache.usgovcloudapi.net"
      ssl_port = 6380
    }
  }
}
mock_provider "azuread" {}
mock_provider "azapi" {
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
  streaming = { enabled = true, max_event_bytes = 65536, timeout_seconds = 180 }
  azure = {
    subscription_id     = "00000000-0000-0000-0000-000000000001"
    tenant_id           = "00000000-0000-0000-0000-000000000002"
    location            = "usgovvirginia"
    environment_name    = "sample"
    resource_group_name = "sample-rg"
    principal_id        = "00000000-0000-0000-0000-000000000003"
  }
  naming                        = { project_name = "sample" }
  public_network_access_enabled = false
  network = {
    private_endpoint_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/endpoints"
    functions_subnet_id        = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/functions"
    web_subnet_id              = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/web"
    apim_subnet_id             = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/apim"
  }
  monitoring = { sku = "PerGB2018", retention_in_days = 30 }
  hosting = {
    functions_sku               = "P1v3"
    web_sku                     = "P1v3"
    python_version              = "3.12"
    node_version                = "24-lts"
    function_always_on          = false
    web_always_on               = false
    stream_always_on            = true
    function_workers            = 1
    web_workers                 = 1
    minimum_tls_version         = "1.2"
    cors_origins                = []
    max_input_tokens            = 200000
    allowed_client_applications = []
    telemetry_sampling_ratio    = 1
    log_retention_days          = 7
    log_disk_quota_mb           = 100
  }
  storage = { account_tier = "Standard", account_replication_type = "ZRS", table_name = "RateLimiter" }
  redis = {
    managed_sku         = "Balanced_B1"
    high_availability   = true
    government_capacity = 1
    inspection_enabled  = false
    minimum_tls_version = "1.2"
    token_scope         = "https://redis.azure.com/.default"
  }
  identity = {
    admin_object_ids          = []
    reader_object_ids         = []
    propagation_wait_duration = "60s"
  }
  gateway = {
    sku_name                       = "Developer_1"
    publisher_name                 = "Sample"
    publisher_email                = "sample@example.com"
    client_audiences               = ["api://client"]
    burst_calls                    = 60
    burst_seconds                  = 60
    max_body_bytes                 = 1048576
    max_output_tokens              = 4096
    max_document_pages             = 20
    max_language_characters        = 5120
    send_request_timeout           = 10
    enable_optional_llm_policy     = false
    llm_policy_verified            = false
    llm_tokens_per_minute          = 100000
    diagnostic_sampling_percentage = 100
    openai_byte_tokenizer_verified = true
  }
  llm_protocols = {
    responses = {
      enabled                   = false
      capability_verified       = false
      government_verified       = false
      byte_tokenizer_verified   = false
      private_endpoint_verified = false
      resource_id               = ""
      endpoint                  = ""
      audience                  = ""
      location                  = ""
      deployment_name           = ""
      price_version             = ""
      role_definition_name      = "Cognitive Services OpenAI User"
      api_version               = "v1"
    }
    anthropic = {
      enabled                   = false
      capability_verified       = false
      private_endpoint_verified = false
      hard_input_cap_verified   = false
      input_cap_evidence        = ""
      context_input_tokens      = 200000
      resource_id               = ""
      endpoint                  = ""
      audience                  = ""
      location                  = ""
      deployment_name           = ""
      price_version             = ""
      anthropic_version         = "2023-06-01"
      role_definition_name      = "Cognitive Services User"
    }
  }
  llm_models     = {}
  managed_models = {}
  applications = {
    inference = {
      demo-app-a = { tenant_id = "00000000-0000-0000-0000-000000000002", display_name = "Demo application A" }
      demo-app-b = { tenant_id = "00000000-0000-0000-0000-000000000002", display_name = "Demo application B" }
    }
    portal = { subscription_id = "portal-server", display_name = "Portal server" }
  }
  portal_key_vault = {
    sku_name = "standard", soft_delete_retention_days = 90, purge_protection_enabled = true, propagation_wait_duration = "60s"
  }
  ai = {
    for service in ["foundry", "document-intelligence", "language"] : service => {
      enabled             = true
      create              = false
      resource_id         = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/${service}"
      endpoint            = "https://${service}.cognitiveservices.azure.us"
      audience            = "https://cognitiveservices.azure.us"
      sku_name            = "S0"
      location            = "usgovvirginia"
      deployment_name     = service == "foundry" ? "sample-model" : (service == "language" ? "sentiment" : "prebuilt-read")
      model_name          = ""
      model_version       = ""
      deployment_sku      = ""
      deployment_capacity = 0
      api_version         = service == "foundry" ? "2024-10-21" : "2024-11-30"
      price_version       = "sample-v1"
    }
  }
}
run "government_private_plan" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
  }
  assert {
    condition     = local.cloud == "government" && local.authority == "https://login.microsoftonline.us"
    error_message = "Government must select the sovereign authority and runtime enum."
  }
  assert {
    condition     = strcontains(output.WEB_URL, ".azurewebsites.us")
    error_message = "Government portal redirect must use the sovereign host."
  }
  assert {
    condition     = keys(output.LLM_GATEWAY_ROUTES) == ["foundry"]
    error_message = "Optional protocols must not publish routes in Government by default."
  }
  assert {
    condition     = keys(module.stream_diagnostics.ids) == ["stream"] && keys(module.stream_private_endpoints.ids) == ["stream"]
    error_message = "Stream-only telemetry and private connectivity must have independent target maps."
  }
}
run "commercial_public_plan" {
  command = plan
  variables {
    azure_cloud                   = "AzureCloud"
    public_network_access_enabled = true
    azure = {
      subscription_id     = "00000000-0000-0000-0000-000000000001"
      tenant_id           = "00000000-0000-0000-0000-000000000002"
      location            = "eastus2"
      environment_name    = "sample"
      resource_group_name = "sample-rg"
      principal_id        = "00000000-0000-0000-0000-000000000003"
    }
    ai = {
      for service in ["foundry", "document-intelligence", "language"] : service => {
        enabled             = true
        create              = false
        resource_id         = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/${service}"
        endpoint            = service == "foundry" ? "https://${service}.services.ai.azure.com" : "https://${service}.cognitiveservices.azure.com"
        audience            = "https://cognitiveservices.azure.com"
        sku_name            = service == "language" ? "S" : "S0"
        location            = "eastus2"
        deployment_name     = service == "foundry" ? "sample-model" : (service == "language" ? "sentiment" : "prebuilt-read")
        model_name          = ""
        model_version       = ""
        deployment_sku      = ""
        deployment_capacity = 0
        api_version         = service == "foundry" ? "2024-10-21" : "2024-11-30"
        price_version       = "sample-v1"
      }
    }
  }
  assert {
    condition     = local.cloud == "commercial" && local.authority == "https://login.microsoftonline.com"
    error_message = "Commercial must select the public authority."
  }
  assert {
    condition     = strcontains(output.WEB_URL, ".azurewebsites.net")
    error_message = "Commercial portal redirect must use the public host."
  }
  assert {
    condition = (
      alltrue([for product in values(module.apim.subscription_contract.products) : product.subscription_required]) &&
      alltrue([for api in values(module.apim.subscription_contract.inference_apis) :
        api.subscription_required && api.product_id == "inference"
      ]) &&
      module.apim.subscription_contract.portal_api.subscription_required &&
      module.apim.subscription_contract.portal_api.product_id == "portal" &&
      toset(module.apim.subscription_contract.application_ids) == toset(["demo-app-a", "demo-app-b"]) &&
      module.apim.subscription_contract.portal_subscription_id == "portal-server"
    )
    error_message = "All APIs require native keys and separate products; inference apps and the server-side portal must have distinct stable subscriptions."
  }
  assert {
    condition = (
      jsondecode(output.APPLICATION_SUBSCRIPTIONS) == local.application_registry &&
      keys(jsondecode(output.APPLICATION_SUBSCRIPTIONS)) == ["demo-app-a", "demo-app-b"] &&
      alltrue([for app in values(jsondecode(output.APPLICATION_SUBSCRIPTIONS)) :
        keys(app) == ["display_name", "tenant_id"] && app.tenant_id == var.azure.tenant_id
      ])
    )
    error_message = "Application metadata must contain only validated inference subscription tenants/labels, never keys or the portal."
  }
}
run "managed_models_publish_real_aliases_and_protocol_caps" {
  command = plan
  variables {
    azure_cloud                   = "AzureCloud"
    azure                         = merge(var.azure, { location = "eastus2" })
    public_network_access_enabled = true
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.openai.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    managed_models = jsondecode(file("managed-models.example.json"))
    llm_models = {
      "openai-chat:referenced-model" = {
        api_protocol              = "openai-chat", resource_id = var.ai.foundry.resource_id,
        endpoint                  = "https://foundry.openai.azure.com", audience = "https://cognitiveservices.azure.com",
        location                  = "eastus2", deployment_name = "existing-reference", price_version = "reference-v1",
        max_input_tokens          = 16000, max_output_tokens = 1024, role_definition_name = "Cognitive Services OpenAI User",
        capability_verified       = true, government_verified = false, byte_tokenizer_verified = true,
        private_endpoint_verified = false, api_version = "2024-10-21", anthropic_version = "",
        hard_input_cap_verified   = false, input_cap_evidence = ""
      }
    }
  }
  assert {
    condition = (
      length(local.model_registry) == 7 &&
      length(module.ai.managed_deployments) == 3 &&
      module.ai.managed_deployments["gpt-5.4"].model_version == "2026-03-05" &&
      module.ai.managed_deployments["gpt-5.4-mini"].model_version == "2026-03-17" &&
      module.ai.managed_deployments["gpt-5.4-nano"].capacity == 10 &&
      !contains(keys(local.model_registry), "openai-chat:sample-model") &&
      module.ai.backends["foundry"].model == "sample-model" &&
      local.model_registry["openai-chat:gpt-5.4"].max_input_tokens == 128000 &&
      local.model_registry["openai-responses:gpt-5.4-nano"].max_output_tokens == 2048 &&
      local.model_registry["openai-chat:gpt-5.4-mini"].price_version == "azure-global-text-2026-11-06" &&
      local.model_registry["openai-responses:gpt-5.4-mini"].api_protocol == "openai-responses" &&
      local.model_registry["openai-chat:referenced-model"].model == "existing-reference" &&
      module.apim.llm_routes["foundry"].model == "" &&
      length(module.apim.llm_routes["responses"].models) == 3
    )
    error_message = "Create three actual deployments with six bounded priced protocol aliases, preserving but hiding the legacy sample and disabling implicit defaults."
  }
}
run "managed_models_require_private_path_verification" {
  command = plan
  variables {
    azure_cloud    = "AzureCloud"
    azure          = merge(var.azure, { location = "eastus2" })
    managed_models = jsondecode(file("managed-models.example.json"))
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.openai.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
  }
  expect_failures = [var.managed_models]
}
run "managed_models_require_government_verification" {
  command = plan
  variables {
    azure_cloud                   = "AzureUSGovernment"
    public_network_access_enabled = true
    managed_models                = jsondecode(file("managed-models.example.json"))
  }
  expect_failures = [var.managed_models]
}
run "applications_cannot_claim_another_tenant" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    applications = {
      inference = {
        untrusted = { tenant_id = "00000000-0000-0000-0000-000000000099", display_name = "Other tenant" }
      }
      portal = { subscription_id = "portal-server", display_name = "Portal server" }
    }
  }
  expect_failures = [var.applications]
}
run "six_additional_models_build_one_registry" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      enabled  = false, location = "eastus2",
      endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_models = merge(
      { for alias in ["chat-fast", "chat-safe"] : "openai-chat:${alias}" => {
        api_protocol              = "openai-chat", resource_id = "${var.ai["foundry"].resource_id}-chat",
        endpoint                  = "https://chat.services.ai.azure.com", audience = "https://cognitiveservices.azure.com",
        location                  = "eastus2", deployment_name = "provider-${alias}", price_version = "chat-v1",
        max_input_tokens          = 64000, max_output_tokens = 2048, role_definition_name = "Cognitive Services OpenAI User",
        capability_verified       = true, government_verified = false, byte_tokenizer_verified = true,
        private_endpoint_verified = true, api_version = alias == "chat-fast" ? "2025-04-01-preview" : "2024-10-21", anthropic_version = "",
        hard_input_cap_verified   = false, input_cap_evidence = ""
      } },
      { for alias in ["responses-fast", "responses-safe"] : "openai-responses:${alias}" => {
        api_protocol              = "openai-responses", resource_id = "${var.ai["foundry"].resource_id}-responses",
        endpoint                  = "https://responses.openai.azure.com", audience = "https://ai.azure.com",
        location                  = "eastus2", deployment_name = "provider-${alias}", price_version = "responses-v1",
        max_input_tokens          = 64000, max_output_tokens = 1024, role_definition_name = "Cognitive Services OpenAI User",
        capability_verified       = true, government_verified = false, byte_tokenizer_verified = true,
        private_endpoint_verified = true, api_version = "v1", anthropic_version = "",
        hard_input_cap_verified   = false, input_cap_evidence = ""
      } },
      { for alias in ["messages-fast", "messages-safe"] : "anthropic-messages:${alias}" => {
        api_protocol              = "anthropic-messages", resource_id = "${var.ai["foundry"].resource_id}-messages",
        endpoint                  = "https://messages.services.ai.azure.com", audience = "https://ai.azure.com",
        location                  = "eastus2", deployment_name = "provider-${alias}", price_version = "messages-v1",
        max_input_tokens          = 128000, max_output_tokens = 1024, role_definition_name = "Azure AI User",
        capability_verified       = true, government_verified = false, byte_tokenizer_verified = false,
        private_endpoint_verified = true, api_version = "", anthropic_version = "2023-06-01",
        hard_input_cap_verified   = true, input_cap_evidence = "Verified hard ceiling TEST-1001"
      } }
    )
  }
  assert {
    condition = (
      length(local.model_registry) == 6 &&
      keys(local.registry_protocol_keys) == ["anthropic-messages", "openai-chat", "openai-responses"] &&
      local.model_registry["openai-chat:chat-fast"].model == "provider-chat-fast" &&
      local.model_registry["openai-chat:chat-fast"].path == "/openai/deployments/provider-chat-fast/chat/completions" &&
      local.model_registry["openai-chat:chat-fast"].api_version == "2025-04-01-preview" &&
      local.model_registry["openai-responses:responses-fast"].path == "/openai/v1/responses" &&
      local.model_registry["anthropic-messages:messages-fast"].path == "/anthropic/v1/messages" &&
      length(local.apim_model_backends) == 3 &&
      length(module.ai.stream_role_assignments) == 3
    )
    error_message = "Two aliases per protocol must feed one effective registry and deduplicated stream roles."
  }
  assert {
    condition = (
      keys(output.LLM_GATEWAY_ROUTES) == ["anthropic", "foundry", "responses"] &&
      output.LLM_GATEWAY_ROUTES["foundry"].model == "" &&
      keys(output.LLM_GATEWAY_ROUTES["foundry"].models) == ["chat-fast", "chat-safe"] &&
      output.LLM_GATEWAY_ROUTES["foundry"].models["chat-fast"].deployment_name == "provider-chat-fast"
    )
    error_message = "Route outputs must advertise every alias without inventing a default."
  }
}
run "additional_model_duplicate_legacy_key_is_rejected" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_models = {
      "openai-chat:sample-model" = {
        api_protocol              = "openai-chat", resource_id = "${var.ai["foundry"].resource_id}-additional",
        endpoint                  = "https://additional.openai.azure.com", audience = "https://cognitiveservices.azure.com",
        location                  = "eastus2", deployment_name = "provider-additional", price_version = "sample-v1",
        max_input_tokens          = 64000, max_output_tokens = 2048, role_definition_name = "Cognitive Services OpenAI User",
        capability_verified       = true, government_verified = false, byte_tokenizer_verified = true,
        private_endpoint_verified = true, api_version = "2024-10-21", anthropic_version = "",
        hard_input_cap_verified   = false, input_cap_evidence = ""
      }
    }
  }
  expect_failures = [var.llm_models]
}
run "government_additional_models_share_aliases_across_protocols" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    ai          = { for key, backend in var.ai : key => merge(backend, { enabled = false }) }
    llm_models = merge([
      for protocol in ["openai-chat", "openai-responses"] : {
        for alias in ["shared-fast", "shared-safe"] : "${protocol}:${alias}" => {
          api_protocol              = protocol
          resource_id               = var.ai["foundry"].resource_id
          endpoint                  = "https://shared.openai.azure.us"
          audience                  = "https://cognitiveservices.azure.us"
          location                  = "usgovvirginia"
          deployment_name           = "provider-${alias}"
          price_version             = "${protocol}-v1"
          max_input_tokens          = 64000
          max_output_tokens         = 2048
          role_definition_name      = "Cognitive Services OpenAI User"
          capability_verified       = true
          government_verified       = protocol == "openai-responses"
          byte_tokenizer_verified   = true
          private_endpoint_verified = true
          api_version               = protocol == "openai-chat" ? "2024-10-21" : "v1"
          anthropic_version         = ""
          hard_input_cap_verified   = false
          input_cap_evidence        = ""
        }
      }
    ]...)
  }
  assert {
    condition = (
      length(local.model_registry) == 4 &&
      keys(output.LLM_GATEWAY_ROUTES) == ["foundry", "responses"] &&
      output.LLM_GATEWAY_ROUTES["responses"].models["shared-fast"].price_version == "openai-responses-v1" &&
      output.LLM_GATEWAY_ROUTES["foundry"].models["shared-fast"].price_version == "openai-chat-v1" &&
      length(module.ai.stream_role_assignments) == 1
    )
    error_message = "Government must support independently priced protocol aliases without duplicate account roles."
  }
}
run "commercial_create_backends_plan" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure = {
      subscription_id     = "00000000-0000-0000-0000-000000000001"
      tenant_id           = "00000000-0000-0000-0000-000000000002"
      location            = "eastus2"
      environment_name    = "sample"
      resource_group_name = "sample-rg"
      principal_id        = "00000000-0000-0000-0000-000000000003"
    }
    ai = {
      for service in ["foundry", "document-intelligence", "language"] : service => {
        enabled             = true
        create              = true
        resource_id         = ""
        endpoint            = ""
        audience            = "https://cognitiveservices.azure.com"
        sku_name            = service == "language" ? "S" : "S0"
        location            = "eastus2"
        deployment_name     = service == "foundry" ? "sample-model" : (service == "language" ? "sentiment" : "prebuilt-read")
        model_name          = service == "foundry" ? "gpt-4o-mini" : ""
        model_version       = service == "foundry" ? "2024-07-18" : ""
        deployment_sku      = service == "foundry" ? "Standard" : ""
        deployment_capacity = service == "foundry" ? 10 : 0
        api_version         = service == "foundry" ? "2024-10-21" : "2024-11-30"
        price_version       = "sample-v1"
      }
    }
  }
  assert {
    condition     = length(module.private_endpoints.ids) == 10 && length(module.stream_private_endpoints.ids) == 1
    error_message = "Private create mode must cover apps, all storage subservices, Redis and every created AI backend."
  }
  assert {
    condition = (
      local.model_registry["openai-chat:sample-model"].endpoint == "https://sample-resource.openai.azure.com" &&
      local.model_registry["openai-chat:sample-model"].path == "/openai/deployments/sample-model/chat/completions" &&
      module.ai.backends["foundry"].audience == "https://cognitiveservices.azure.com"
    )
    error_message = "Created Foundry must select its OpenAI inference origin, not its general AIServices endpoint."
  }
}

run "government_created_foundry_inference_origin" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    ai = { for key, backend in var.ai : key => merge(backend, {
      create              = key == "foundry",
      resource_id         = key == "foundry" ? "" : backend.resource_id,
      endpoint            = key == "foundry" ? "" : backend.endpoint,
      model_name          = key == "foundry" ? "gpt-4o-mini" : "",
      model_version       = key == "foundry" ? "2024-07-18" : "",
      deployment_sku      = key == "foundry" ? "Standard" : "",
      deployment_capacity = key == "foundry" ? 10 : 0
    }) }
  }
  assert {
    condition = (
      local.model_registry["openai-chat:sample-model"].endpoint == "https://sample-resource.openai.azure.us" &&
      local.model_registry["openai-chat:sample-model"].audience == "https://cognitiveservices.azure.us"
    )
    error_message = "Created Government Foundry must retain the sovereign inference endpoint and token audience."
  }
}

run "all_three_protocols_verified_commercial" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_protocols = {
      responses = merge(var.llm_protocols.responses, {
        enabled     = true, capability_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true,
        resource_id = var.ai["foundry"].resource_id, endpoint = "https://sample.openai.azure.com",
        audience    = "https://ai.azure.com", location = "eastus2", deployment_name = "sample-model", price_version = "sample-v1"
      })
      anthropic = merge(var.llm_protocols.anthropic, {
        enabled            = true, capability_verified = true, private_endpoint_verified = true, hard_input_cap_verified = true,
        input_cap_evidence = "Verified deployed model hard input limit; operator acceptance TEST-123",
        resource_id        = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.CognitiveServices/accounts/claude",
        endpoint           = "https://sample.services.ai.azure.com", audience = "https://ai.azure.com", location = "eastus2",
        deployment_name    = "sample-claude", price_version = "sample-v1"
      })
    }
  }
  assert {
    condition = (
      output.LLM_GATEWAY_ROUTES.responses.path == "/foundry/responses" &&
      output.LLM_GATEWAY_ROUTES.anthropic.path == "/anthropic/v1/messages" &&
      output.LLM_GATEWAY_ROUTES.anthropic.api_protocol == "anthropic-messages" &&
      output.LLM_GATEWAY_ROUTES.responses.backend_path == "/openai/v1/responses" &&
      output.LLM_GATEWAY_ROUTES.responses.api_version == "v1" &&
      output.LLM_GATEWAY_ROUTES.anthropic.backend_path == "/anthropic/v1/messages" &&
      output.LLM_GATEWAY_ROUTES.anthropic.anthropic_version == "2023-06-01" &&
      output.LLM_GATEWAY_ROUTES.foundry.path == "/foundry/chat/completions"
    )
    error_message = "All three enabled protocol routes must preserve the stable Chat path and distinct provider contracts."
  }
  assert {
    condition     = length(module.ai.protocol_role_assignment_ids) == 1
    error_message = "Responses must reuse the existing Chat role binding on the same account."
  }
  assert {
    condition = (
      keys(local.stream_backends) == ["anthropic-messages", "openai-chat", "openai-responses"] &&
      local.stream_backends["openai-chat"].path == "/openai/deployments/sample-model/chat/completions" &&
      local.stream_backends["openai-responses"].path == "/openai/v1/responses" &&
      local.stream_backends["anthropic-messages"].path == "/anthropic/v1/messages" &&
      local.stream_backends["openai-responses"].audience == "https://ai.azure.com" &&
      local.stream_backends["anthropic-messages"].anthropic_version == "2023-06-01"
    )
    error_message = "The stream host must receive only enabled pinned protocol endpoints, routes and audiences."
  }
  assert {
    condition = (
      length(module.ai.stream_role_assignments) == 2 &&
      alltrue([for binding in values(module.ai.stream_role_assignments) : binding.principal_id == module.identity.function.principal_id])
    )
    error_message = "Streaming AI grants must deduplicate Chat/Responses and target only the shared Function identity."
  }
}

run "responses_reuses_terraform_managed_chat_role" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
      }, key == "foundry" ? {
      create         = true, model_name = "gpt-4o-mini", model_version = "2024-07-18",
      deployment_sku = "Standard", deployment_capacity = 10
    } : {}) }
    llm_protocols = merge(var.llm_protocols, {
      responses = merge(var.llm_protocols.responses, {
        enabled         = true, capability_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true,
        resource_id     = var.ai["foundry"].resource_id, endpoint = "https://sample.openai.azure.com",
        audience        = "https://ai.azure.com", location = "eastus2",
        deployment_name = "sample-model", price_version = "sample-v1"
      })
    })
  }
  assert {
    condition     = length(module.ai.protocol_role_assignment_ids) == 0
    error_message = "Enabling Responses after creating Chat must not duplicate the managed account's gateway role."
  }
  assert {
    condition     = length(module.ai.stream_role_assignments) == 1
    error_message = "A created Chat account and Responses reference must share one streaming Function role."
  }
}

run "duplicate_protocol_references_reuse_existing_role" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_protocols = {
      responses = merge(var.llm_protocols.responses, {
        enabled         = true, capability_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true,
        resource_id     = var.ai["language"].resource_id, role_definition_name = "Cognitive Services User",
        endpoint        = "https://sample.openai.azure.com", audience = "https://ai.azure.com", location = "eastus2",
        deployment_name = "sample-model", price_version = "sample-v1"
      })
      anthropic = merge(var.llm_protocols.anthropic, {
        enabled            = true, capability_verified = true, private_endpoint_verified = true, hard_input_cap_verified = true,
        input_cap_evidence = "Verified deployed hard ceiling TEST-456", resource_id = var.ai["language"].resource_id,
        endpoint           = "https://sample.services.ai.azure.com", audience = "https://ai.azure.com", location = "eastus2",
        deployment_name    = "sample-claude", price_version = "sample-v1"
      })
    }
  }
  assert {
    condition     = length(module.ai.protocol_role_assignment_ids) == 0
    error_message = "Additional protocols must not recreate an existing principal/scope/role tuple."
  }
  assert {
    condition = (
      contains(keys(local.ai_diagnostic_targets), "ai-language") &&
      !contains(keys(local.ai_diagnostic_targets), "ai-anthropic") &&
      !contains(keys(local.ai_diagnostic_targets), "ai-responses")
    )
    error_message = "Sharing a legacy account must preserve its diagnostic address, not rename it to a protocol alias."
  }
  assert {
    condition     = length(module.ai.stream_role_assignments) == 2
    error_message = "Stream roles include Chat plus one shared Responses/Messages grant, not unrelated AI roles."
  }
}

run "disabled_streaming_keeps_direct_routes" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    streaming   = { enabled = false, max_event_bytes = 65536, timeout_seconds = 180 }
  }

  assert {
    condition = (
      output.AZURE_STREAM_FUNCTION_NAME == null &&
      output.AZURE_STREAM_FUNCTION_ID == null &&
      length(module.ai.stream_role_assignments) == 0 &&
      length(module.private_endpoints.ids) == 7 &&
      length(module.stream_private_endpoints.ids) == 0 &&
      length(module.stream_diagnostics.ids) == 0
    )
    error_message = "Disabling streaming must omit the observer host, private endpoint and AI grants."
  }
}

run "stream_event_bound_rejects_small_values" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    streaming   = { enabled = true, max_event_bytes = 8191, timeout_seconds = 180 }
  }
  expect_failures = [var.streaming]
}

run "stream_timeout_rejects_unbounded_values" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    streaming   = { enabled = true, max_event_bytes = 65536, timeout_seconds = 211 }
  }
  expect_failures = [var.streaming]
}

run "responses_only_does_not_publish_chat" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      enabled  = key != "foundry", location = "eastus2",
      endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_protocols = merge(var.llm_protocols, {
      responses = merge(var.llm_protocols.responses, {
        enabled         = true, capability_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true,
        resource_id     = var.ai["foundry"].resource_id, endpoint = "https://sample.openai.azure.com",
        audience        = "https://ai.azure.com", location = "eastus2",
        deployment_name = "sample-model", price_version = "sample-v1"
      })
    })
  }
  assert {
    condition     = keys(output.LLM_GATEWAY_ROUTES) == ["responses"] && output.LLM_GATEWAY_ROUTES.responses.path == "/foundry/responses"
    error_message = "The shared Foundry API must expose Responses without accidentally enabling Chat."
  }
}

run "new_protocols_share_one_new_role" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_protocols = {
      responses = merge(var.llm_protocols.responses, {
        enabled         = true, capability_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true,
        resource_id     = "${var.ai["foundry"].resource_id}-shared-protocols", role_definition_name = "Cognitive Services User",
        endpoint        = "https://shared.openai.azure.com", audience = "https://ai.azure.com", location = "eastus2",
        deployment_name = "sample-model", price_version = "sample-v1"
      })
      anthropic = merge(var.llm_protocols.anthropic, {
        enabled            = true, capability_verified = true, private_endpoint_verified = true, hard_input_cap_verified = true,
        input_cap_evidence = "Verified full deployed context TEST-789",
        resource_id        = "${var.ai["foundry"].resource_id}-shared-protocols",
        endpoint           = "https://shared.services.ai.azure.com", audience = "https://ai.azure.com", location = "eastus2",
        deployment_name    = "sample-claude", price_version = "sample-v1"
      })
    }
  }
  assert {
    condition     = length(module.ai.protocol_role_assignment_ids) == 1
    error_message = "Two optional protocols on a new shared principal/scope/role must create one assignment."
  }
}

run "existing_backends_shared_scope_have_unique_role_names" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      resource_id = var.ai["foundry"].resource_id, location = "eastus2",
      endpoint    = "https://shared.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
  }
  assert {
    condition = (
      length(module.ai.gateway_role_assignments) == 2 &&
      length(distinct([for assignment in values(module.ai.gateway_role_assignments) : assignment.name])) == 2
    )
    error_message = "Existing shared scopes must deduplicate identical roles and use distinct names for different roles."
  }
}

run "anthropic_ceiling_cannot_exceed_function_bound" {
  command = plan
  variables {
    azure_cloud = "AzureCloud"
    azure       = merge(var.azure, { location = "eastus2" })
    ai = { for key, backend in var.ai : key => merge(backend, {
      location = "eastus2", endpoint = "https://${key}.cognitiveservices.azure.com", audience = "https://cognitiveservices.azure.com"
    }) }
    llm_protocols = merge(var.llm_protocols, {
      anthropic = merge(var.llm_protocols.anthropic, {
        enabled            = true, capability_verified = true, private_endpoint_verified = true, hard_input_cap_verified = true,
        input_cap_evidence = "Verified full deployed context TEST-BOUND", context_input_tokens = 200001,
        resource_id        = var.ai["foundry"].resource_id, endpoint = "https://sample.services.ai.azure.com",
        audience           = "https://ai.azure.com", location = "eastus2", deployment_name = "sample-claude", price_version = "sample-v1"
      })
    })
  }
  expect_failures = [var.llm_protocols]
}

run "government_responses_requires_reverification" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    llm_protocols = merge(var.llm_protocols, {
      responses = merge(var.llm_protocols.responses, {
        enabled         = true, capability_verified = true, byte_tokenizer_verified = true, private_endpoint_verified = true,
        resource_id     = var.ai["foundry"].resource_id, endpoint = "https://sample.openai.azure.us",
        audience        = "https://cognitiveservices.azure.us", location = "usgovvirginia",
        deployment_name = "sample-model", price_version = "sample-v1", government_verified = false
      })
    })
  }
  expect_failures = [var.llm_protocols]
}

run "government_claude_is_fail_closed" {
  command = plan
  variables {
    azure_cloud = "AzureUSGovernment"
    llm_protocols = merge(var.llm_protocols, {
      anthropic = merge(var.llm_protocols.anthropic, {
        enabled            = true, capability_verified = true, private_endpoint_verified = true, hard_input_cap_verified = true,
        input_cap_evidence = "Unverified sovereign availability must not be invented", resource_id = var.ai["foundry"].resource_id,
        endpoint           = "https://sample.services.ai.azure.com", audience = "https://ai.azure.com", location = "usgovvirginia",
        deployment_name    = "sample-claude", price_version = "sample-v1"
      })
    })
  }
  expect_failures = [var.llm_protocols]
}
