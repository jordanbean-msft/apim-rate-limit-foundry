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
    web      = "azurerm_app_service"
    apim     = "azurerm_api_management"
    storage  = "azurerm_storage_account"
    redis    = "azurerm_redis_cache"
    plan     = "azurerm_app_service_plan"
  }
  names        = { for key, name in azurecaf_name.resource : key => name.result }
  function_url = "https://${local.names.function}.${local.web_suffix}"
  web_url      = "https://${local.names.web}.${local.web_suffix}"
  ai_reference_groups = {
    for key, backend in var.ai : backend.resource_id => key... if backend.enabled && !backend.create
  }
  ai_reference_diagnostic_keys = toset([for keys in values(local.ai_reference_groups) : sort(keys)[0]])
}
resource "azurecaf_name" "resource" {
  for_each      = local.resource_types
  name          = local.resource_token
  resource_type = each.value
  prefixes      = [var.naming.project_name]
  random_length = 0
  clean_input   = true
}
module "monitoring" {
  source              = "./modules/monitoring"
  resource_token      = local.resource_token
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  tags                = local.default_tags
  config              = var.monitoring
}
module "identity" {
  source              = "./modules/identity"
  resource_token      = local.resource_token
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  tags                = local.default_tags
  tenant_id           = var.azure.tenant_id
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
  resource_token                = local.resource_token
  resource_group_name           = data.azurerm_resource_group.rg.name
  tags                          = local.default_tags
  public_network_access_enabled = var.public_network_access_enabled
  config                        = var.ai
  gateway_principal_id          = module.identity.gateway.principal_id
  protocols                     = var.llm_protocols
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
  function_identity                      = module.identity.function
  web_identity                           = module.identity.web
  storage_account_name                   = module.storage.name
  application_insights_connection_string = module.monitoring.app_insights_connection_string
  api_client_id                          = module.identity.api_client_id
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
  identity                      = module.identity.gateway
  authority                     = local.authority
  tenant_id                     = var.azure.tenant_id
  function_url                  = local.function_url
  api_audience                  = module.identity.api_audience
  web_url                       = local.web_url
  ai                            = module.ai.backends
  application_insights_id       = module.monitoring.app_insights_id
  instrumentation_key           = module.monitoring.app_insights_instrumentation_key
  max_input_tokens              = var.hosting.max_input_tokens
  depends_on                    = [module.identity]
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
    { for key, backend in module.ai.backends : "ai-${key}" => backend.id if(
      (!contains(["responses", "anthropic"], key) && (try(var.ai[key].create, false) || contains(local.ai_reference_diagnostic_keys, key))) ||
      (!contains([for item in values(var.ai) : item.resource_id if item.enabled && item.resource_id != ""], backend.id) &&
      (key != "anthropic" || !var.llm_protocols.responses.enabled || var.llm_protocols.anthropic.resource_id != var.llm_protocols.responses.resource_id))
    ) }
  )
}
