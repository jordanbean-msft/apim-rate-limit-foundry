data "azurerm_resource_group" "rg" {
  name = var.azure.resource_group_name
}
data "azurerm_client_config" "current" {}

locals {
  cloud              = var.azure_cloud == "AzureUSGovernment" ? "government" : "commercial"
  resource_token_sha = base64encode(sha256("${var.azure.location}${data.azurerm_client_config.current.subscription_id}${var.azure.resource_group_name}"))
  resource_token     = substr(join("", regexall("[a-z0-9]", lower(local.resource_token_sha))), 0, 13)
  authority          = local.cloud == "government" ? "https://login.microsoftonline.us" : "https://login.microsoftonline.com"
  web_suffix         = local.cloud == "government" ? "azurewebsites.us" : "azurewebsites.net"
  default_tags = merge({
    project        = var.naming.project_name
    environment    = var.azure.environment_name
    managed_by     = "terraform"
    "azd-env-name" = var.azure.environment_name
  }, var.tags)
  resource_types = {
    function = "azurerm_function_app"
    stream   = "azurerm_function_app"
    web      = "azurerm_app_service"
    apim     = "azurerm_api_management"
    storage  = "azurerm_storage_account"
    redis    = "azurerm_redis_cache"
    plan     = "azurerm_app_service_plan"
  }
  names        = { for key, name in azurecaf_name.resource : key => name.result }
  function_url = "https://${local.names.function}.${local.web_suffix}"
  stream_url   = "https://${local.names.stream}.${local.web_suffix}"
  stream_paths = {
    foundry   = "/openai/deployments/${try(module.ai.backends["foundry"].model, "")}/chat/completions"
    responses = "/openai/v1/responses"
    anthropic = "/anthropic/v1/messages"
  }
  stream_backends = {
    for key, backend in module.ai.backends : backend.api_protocol => {
      endpoint = backend.endpoint, path = local.stream_paths[key], model = backend.model,
      audience = backend.audience, api_version = backend.api_version, anthropic_version = backend.anthropic_version
    } if contains(keys(local.stream_paths), key)
  }
  legacy_model_registry = {
    for key, backend in module.ai.backends : "${backend.api_protocol}:${backend.model}" => {
      api_protocol      = backend.api_protocol
      endpoint          = backend.endpoint
      path              = backend.api_protocol == "openai-chat" ? "/openai/deployments/${backend.model}/chat/completions" : (backend.api_protocol == "openai-responses" ? "/openai/v1/responses" : "/anthropic/v1/messages")
      model             = backend.model
      audience          = backend.audience
      api_version       = backend.api_version
      anthropic_version = backend.anthropic_version
      price_version     = backend.price_version
      max_input_tokens  = backend.api_protocol == "anthropic-messages" ? backend.context_input_tokens : var.hosting.max_input_tokens
      max_output_tokens = var.gateway.max_output_tokens
      } if backend.api_protocol != "" && !(
      length(var.managed_models) > 0 &&
      contains(["openai-chat", "openai-responses"], backend.api_protocol) &&
      backend.model == var.ai.foundry.deployment_name
    )
  }
  additional_model_registry = {
    for key, model in var.llm_models : key => {
      api_protocol      = model.api_protocol
      endpoint          = trimsuffix(model.endpoint, "/")
      path              = model.api_protocol == "openai-chat" ? "/openai/deployments/${model.deployment_name}/chat/completions" : (model.api_protocol == "openai-responses" ? "/openai/v1/responses" : "/anthropic/v1/messages")
      model             = model.deployment_name
      audience          = model.audience
      api_version       = model.api_version
      anthropic_version = model.anthropic_version
      price_version     = model.price_version
      max_input_tokens  = model.max_input_tokens
      max_output_tokens = model.max_output_tokens
    }
  }
  managed_model_registry = merge({}, [
    for alias, model in var.managed_models : {
      for protocol, config in model.protocols : "${protocol}:${alias}" => {
        api_protocol      = protocol
        endpoint          = module.ai.backends["foundry"].endpoint
        path              = protocol == "openai-chat" ? "/openai/deployments/${alias}/chat/completions" : "/openai/v1/responses"
        model             = alias
        audience          = var.ai.foundry.audience
        api_version       = config.api_version
        anthropic_version = ""
        price_version     = config.price_version
        max_input_tokens  = config.max_input_tokens
        max_output_tokens = config.max_output_tokens
      }
    }
  ]...)
  application_registry = { for id, app in var.applications.inference : id => {
    tenant_id = app.tenant_id, display_name = app.display_name
  } }
  model_registry = merge(local.legacy_model_registry, local.additional_model_registry, local.managed_model_registry)
  registry_protocol_keys = {
    for protocol in distinct([for model in values(local.model_registry) : model.api_protocol]) :
    protocol => [for key, model in local.model_registry : key if model.api_protocol == protocol]
  }
  # APIM needs one service URL per API; dispatch always resolves the requested alias.
  first_registry_models = {
    for protocol, keys in local.registry_protocol_keys : protocol => local.model_registry[keys[0]]
  }
  apim_model_backends = {
    for route, protocol in {
      foundry   = "openai-chat"
      responses = "openai-responses"
      anthropic = "anthropic-messages"
      } : route => {
      id                   = ""
      endpoint             = local.first_registry_models[protocol].endpoint
      audience             = local.first_registry_models[protocol].audience
      model                = local.first_registry_models[protocol].model
      api_version          = local.first_registry_models[protocol].api_version
      price_version        = local.first_registry_models[protocol].price_version
      created              = false
      api_protocol         = protocol
      context_input_tokens = local.first_registry_models[protocol].max_input_tokens
      anthropic_version    = local.first_registry_models[protocol].anthropic_version
    } if contains(keys(local.first_registry_models), protocol) && !contains(keys(module.ai.backends), route)
  }
  ai_diagnostic_backends = merge(
    { for key, backend in module.ai.backends : "legacy:${key}" => {
      id           = backend.id
      resource_key = (backend.created ? (try(var.ai[key].resource_id, "") != "" ? lower(var.ai[key].resource_id) : "created:${key}") : lower(backend.id))
    } },
    { for key, model in var.llm_models : "additional:${key}" => {
      id = model.resource_id, resource_key = lower(model.resource_id)
    } }
  )
  ai_diagnostic_groups = {
    for key, backend in local.ai_diagnostic_backends : backend.resource_key => key...
  }
  ai_diagnostic_representatives = {
    for resource_key, keys in local.ai_diagnostic_groups :
    resource_key => coalescelist(
      sort([for key in keys : key if startswith(key, "legacy:") && !contains(["legacy:responses", "legacy:anthropic"], key)]),
      [for key in ["legacy:responses", "legacy:anthropic"] : key if contains(keys, key)],
      sort(keys)
    )[0]
  }
  ai_diagnostic_targets = {
    for resource_key, key in local.ai_diagnostic_representatives :
    (startswith(key, "legacy:") ? "ai-${trimprefix(key, "legacy:")}" : "ai-model-${substr(sha256(resource_key), 0, 12)}") =>
    local.ai_diagnostic_backends[key].id
  }
  web_url = "https://${local.names.web}.${local.web_suffix}"
}
resource "azurecaf_name" "resource" {
  for_each      = local.resource_types
  name          = local.resource_token
  resource_type = each.value
  prefixes      = [var.naming.project_name]
  suffixes      = each.key == "stream" ? ["stream"] : []
  random_length = 0
  clean_input   = true
}
module "monitoring" {
  source                        = "./modules/monitoring"
  resource_token                = local.resource_token
  resource_group_name           = data.azurerm_resource_group.rg.name
  location                      = data.azurerm_resource_group.rg.location
  tags                          = local.default_tags
  config                        = var.monitoring
  azure_cloud                   = local.cloud
  dashboard_reader_principal_id = module.identity.function.principal_id
}
module "identity" {
  source              = "./modules/identity"
  resource_token      = local.resource_token
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  tags                = local.default_tags
  tenant_id           = var.azure.tenant_id
  authority           = local.authority
  deployer_object_id  = var.azure.principal_id
  portal_redirect_uri = local.web_url
  config              = var.identity
}
module "storage" {
  source                        = "./modules/storage"
  name                          = local.names.storage
  resource_group_name           = data.azurerm_resource_group.rg.name
  location                      = data.azurerm_resource_group.rg.location
  tags                          = local.default_tags
  public_network_access_enabled = var.public_network_access_enabled
  config                        = var.storage
  principal_id                  = module.identity.function.principal_id
  deployer_principal_id         = var.azure.principal_id
  depends_on                    = [module.identity]
}
module "redis" {
  source                        = "./modules/redis"
  name                          = local.names.redis
  resource_group_name           = data.azurerm_resource_group.rg.name
  location                      = data.azurerm_resource_group.rg.location
  tags                          = local.default_tags
  public_network_access_enabled = var.public_network_access_enabled
  azure_cloud                   = local.cloud
  config                        = var.redis
  principal_id                  = module.identity.function.principal_id
  inspection_principal_id       = var.azure.principal_id
  depends_on                    = [module.identity]
}
module "ai" {
  source                        = "./modules/ai"
  azure_cloud                   = local.cloud
  resource_token                = local.resource_token
  resource_group_name           = data.azurerm_resource_group.rg.name
  tags                          = local.default_tags
  public_network_access_enabled = var.public_network_access_enabled
  config                        = var.ai
  gateway_principal_id          = module.identity.gateway.principal_id
  streaming_enabled             = var.streaming.enabled
  function_principal_id         = module.identity.function.principal_id
  protocols                     = var.llm_protocols
  llm_models                    = var.llm_models
  managed_deployments           = var.managed_models
  depends_on                    = [module.identity]
}
module "hosting" {
  source                        = "./modules/hosting"
  names                         = local.names
  resource_group_name           = data.azurerm_resource_group.rg.name
  location                      = data.azurerm_resource_group.rg.location
  tags                          = local.default_tags
  public_network_access_enabled = var.public_network_access_enabled
  network                       = var.network
  config = merge(var.hosting, {
    allowed_client_applications = distinct(concat(
      var.hosting.allowed_client_applications,
      [module.identity.web_client_id, module.identity.gateway.client_id]
    ))
  })
  function_identity = module.identity.function
  streaming_enabled = var.streaming.enabled
  stream_settings = {
    PYTHON_ENABLE_INIT_INDEXING = "1"
    STREAM_BACKENDS             = jsonencode(local.stream_backends)
    MODEL_REGISTRY              = jsonencode(local.model_registry)
    STREAM_MAX_EVENT_BYTES      = tostring(var.streaming.max_event_bytes)
    STREAM_MAX_BODY_BYTES       = tostring(var.gateway.max_body_bytes)
    STREAM_TIMEOUT_SECONDS      = tostring(var.streaming.timeout_seconds)
    OTEL_SERVICE_NAME           = "rate-limiter-stream"
  }
  web_identity                           = module.identity.web
  storage_account_name                   = module.storage.name
  application_insights_connection_string = module.monitoring.app_insights_connection_string
  api_client_id                          = module.identity.api_client_id
  web_client_id                          = module.identity.web_client_id
  api_audience                           = module.identity.api_audience
  tenant_id                              = var.azure.tenant_id
  authority                              = local.authority
  function_settings = {
    AZURE_CLOUD                           = local.cloud
    AZURE_TENANT_ID                       = var.azure.tenant_id
    AZURE_CLIENT_ID                       = module.identity.function.client_id
    TABLE_ENDPOINT                        = module.storage.table_endpoint
    TABLE_NAME                            = var.storage.table_name
    AzureWebJobsStorage__blobServiceUri   = module.storage.blob_endpoint
    AzureWebJobsStorage__queueServiceUri  = module.storage.queue_endpoint
    AzureWebJobsStorage__tableServiceUri  = module.storage.table_endpoint
    REDIS_HOST                            = module.redis.hostname
    REDIS_PORT                            = tostring(module.redis.port)
    REDIS_USERNAME                        = module.identity.function.principal_id
    REDIS_TOKEN_SCOPE                     = var.redis.token_scope
    LOCAL_AUTH_ENABLED                    = "false"
    LOCAL_STORE_ENABLED                   = "false"
    MAX_INPUT_TOKENS                      = tostring(var.hosting.max_input_tokens)
    MAX_OUTPUT_TOKENS                     = tostring(var.gateway.max_output_tokens)
    MODEL_REGISTRY                        = jsonencode(local.model_registry)
    APPLICATION_REGISTRY                  = jsonencode(local.application_registry)
    AZURE_DASHBOARD_ID                    = module.monitoring.dashboard_id
    LOG_ANALYTICS_WORKSPACE_ID            = module.monitoring.workspace_customer_id
    LOG_ANALYTICS_WORKSPACE_RESOURCE_ID   = module.monitoring.workspace_id
    SCM_DO_BUILD_DURING_DEPLOYMENT        = "true"
    ENABLE_ORYX_BUILD                     = "true"
    APPLICATIONINSIGHTS_CONNECTION_STRING = module.monitoring.app_insights_connection_string
    OTEL_SERVICE_NAME                     = "rate-limiter"
    OTEL_TRACES_SAMPLER_ARG               = tostring(var.hosting.telemetry_sampling_ratio)
    TELEMETRY_ENABLED                     = "true"
  }
  web_settings = {
    AZURE_CLOUD                                = local.cloud
    AZURE_TENANT_ID                            = var.azure.tenant_id
    WEB_CLIENT_ID                              = module.identity.web_client_id
    API_AUDIENCE                               = module.identity.api_audience
    API_SCOPE                                  = "${module.identity.api_audience}/access_as_user"
    API_BASE_URL                               = "${module.apim.gateway_url}/portal"
    WEB_API_PROXY_ENABLED                      = "true"
    PORTAL_APIM_SUBSCRIPTION_KEY               = "@Microsoft.KeyVault(SecretUri=${module.portal_key_vault.secret_uri})"
    GRAPH_BASE_URL                             = local.cloud == "government" ? "https://graph.microsoft.us" : "https://graph.microsoft.com"
    APPLICATIONINSIGHTS_CONNECTION_STRING      = module.monitoring.app_insights_connection_string
    ApplicationInsightsAgent_EXTENSION_VERSION = "~3"
    SCM_DO_BUILD_DURING_DEPLOYMENT             = "false"
  }
  depends_on = [module.storage, module.redis]
}
module "apim" {
  source                        = "./modules/apim"
  name                          = local.names.apim
  resource_group_name           = data.azurerm_resource_group.rg.name
  resource_group_id             = data.azurerm_resource_group.rg.id
  location                      = data.azurerm_resource_group.rg.location
  tags                          = local.default_tags
  public_network_access_enabled = var.public_network_access_enabled
  subnet_id                     = var.network.apim_subnet_id
  config                        = var.gateway
  applications                  = var.applications
  identity                      = module.identity.gateway
  authority                     = local.authority
  tenant_id                     = var.azure.tenant_id
  function_url                  = local.function_url
  stream_url                    = local.stream_url
  streaming_enabled             = var.streaming.enabled
  api_audience                  = module.identity.api_audience
  web_url                       = local.web_url
  ai                            = module.ai.backends
  route_backends                = local.apim_model_backends
  model_registry                = local.model_registry
  legacy_defaults = {
    foundry   = length(var.managed_models) == 0 ? try(module.ai.backends["foundry"].model, "") : ""
    responses = length(var.managed_models) > 0 && try(module.ai.backends["responses"].model, "") == var.ai.foundry.deployment_name ? "" : try(module.ai.backends["responses"].model, "")
    anthropic = try(module.ai.backends["anthropic"].model, "")
  }
  application_insights_id = module.monitoring.app_insights_id
  instrumentation_key     = module.monitoring.app_insights_instrumentation_key
  max_input_tokens        = var.hosting.max_input_tokens
  depends_on              = [module.identity]
}
module "portal_key_vault" {
  source                        = "./modules/portal_key_vault"
  resource_token                = local.resource_token
  resource_group_name           = data.azurerm_resource_group.rg.name
  location                      = data.azurerm_resource_group.rg.location
  tags                          = local.default_tags
  tenant_id                     = var.azure.tenant_id
  deployer_principal_id         = var.azure.principal_id
  web_principal_id              = module.identity.web.principal_id
  public_network_access_enabled = var.public_network_access_enabled
  private_endpoint_subnet_id    = var.network.private_endpoint_subnet_id
  workspace_id                  = module.monitoring.workspace_id
  config                        = var.portal_key_vault
  portal_subscription_key       = module.apim.portal_subscription_key
}
module "private_endpoints" {
  source              = "./modules/private_endpoints"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  tags                = local.default_tags
  subnet_id           = var.network.private_endpoint_subnet_id
  targets = var.public_network_access_enabled ? {} : merge(
    {
      function = { id = module.hosting.function_id, group = "sites" }
      web      = { id = module.hosting.web_id, group = "sites" }
      redis    = { id = module.redis.id, group = local.cloud == "government" ? "redisCache" : "redisEnterprise" }
    },
    { for service in ["blob", "queue", "table", "file"] : "storage-${service}" => { id = module.storage.id, group = service } },
    { for key, backend in module.ai.backends : "ai-${key}" => { id = backend.id, group = "account" } if backend.created }
  )
}
module "stream_private_endpoints" {
  source              = "./modules/private_endpoints"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  tags                = local.default_tags
  subnet_id           = var.network.private_endpoint_subnet_id
  targets             = var.streaming.enabled && !var.public_network_access_enabled ? { stream = { id = module.hosting.stream_id, group = "sites" } } : {}
}
module "stream_diagnostics" {
  source       = "./modules/diagnostics"
  workspace_id = module.monitoring.workspace_id
  targets      = var.streaming.enabled ? { stream = module.hosting.stream_id } : {}
}
module "diagnostics" {
  source       = "./modules/diagnostics"
  workspace_id = module.monitoring.workspace_id
  targets = merge(
    {
      apim          = module.apim.id
      function      = module.hosting.function_id
      web           = module.hosting.web_id
      function-plan = module.hosting.function_plan_id
      web-plan      = module.hosting.web_plan_id
      workspace     = module.monitoring.workspace_id
      storage       = module.storage.id
      storage-blob  = "${module.storage.id}/blobServices/default"
      storage-queue = "${module.storage.id}/queueServices/default"
      storage-table = "${module.storage.id}/tableServices/default"
      storage-file  = "${module.storage.id}/fileServices/default"
      redis         = module.redis.id
    },
    local.cloud == "commercial" ? { redis-database = "${module.redis.id}/databases/default" } : {},
    local.ai_diagnostic_targets
  )
}
