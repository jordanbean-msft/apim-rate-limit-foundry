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
    node_version                = "22-lts"
    function_workers            = 1
    web_workers                 = 1
    minimum_tls_version         = "1.2"
    cors_origins                = []
    max_input_tokens            = 200000
    allowed_client_applications = []
  }
  storage = { account_tier = "Standard", account_replication_type = "ZRS", table_name = "RateLimiter" }
  redis = {
    managed_sku         = "Balanced_B1"
    high_availability   = true
    government_capacity = 1
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
    subscription_tenant_mapping    = {}
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
        endpoint            = "https://${service}.cognitiveservices.azure.com"
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
    condition     = length(module.private_endpoints.ids) == 10
    error_message = "Private create mode must cover apps, all storage subservices, Redis and every created AI backend."
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
