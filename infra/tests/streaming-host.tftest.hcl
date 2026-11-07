mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_service_plan" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Web/serverFarms/sample-plan"
    }
  }
}

variables {
  names = {
    function = "sample-function", stream = "sample-function-stream", web = "sample-web", plan = "sample-plan"
  }
  resource_group_name           = "sample-rg"
  location                      = "eastus2"
  tags                          = { "azd-env-name" = "sample" }
  public_network_access_enabled = false
  network = {
    functions_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/functions"
    web_subnet_id       = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/web"
  }
  config = {
    functions_sku            = "P1v3", web_sku = "P1v3", python_version = "3.12", node_version = "24-lts",
    function_always_on       = false, web_always_on = false, stream_always_on = true,
    function_workers         = 1, web_workers = 1, minimum_tls_version = "1.2", cors_origins = [],
    max_input_tokens         = 200000, allowed_client_applications = ["00000000-0000-0000-0000-000000000006"],
    telemetry_sampling_ratio = 1, log_retention_days = 7, log_disk_quota_mb = 100
  }
  function_identity = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/function"
    client_id    = "00000000-0000-0000-0000-000000000004"
    principal_id = "00000000-0000-0000-0000-000000000005"
  }
  web_identity = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/web"
    client_id    = "00000000-0000-0000-0000-000000000008"
    principal_id = "00000000-0000-0000-0000-000000000009"
  }
  storage_account_name                   = "samplestorage"
  application_insights_connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000012"
  function_settings = {
    TABLE_NAME = "RateLimiter", REDIS_HOST = "sample.redis.example.net", OTEL_SERVICE_NAME = "rate-limiter"
  }
  stream_settings = {
    PYTHON_ENABLE_INIT_INDEXING = "1", STREAM_MAX_EVENT_BYTES = "65536", STREAM_MAX_BODY_BYTES = "1048576",
    STREAM_TIMEOUT_SECONDS      = "180", OTEL_SERVICE_NAME = "rate-limiter-stream", STREAM_BACKENDS = "{}"
  }
  web_settings = {
    WEB_API_PROXY_ENABLED        = "true"
    PORTAL_APIM_SUBSCRIPTION_KEY = "@Microsoft.KeyVault(SecretUri=https://portal.vault.azure.net/secrets/portal-apim-subscription-key)"
  }
  api_client_id     = "00000000-0000-0000-0000-000000000010"
  web_client_id     = "00000000-0000-0000-0000-000000000011"
  api_audience      = "api://00000000-0000-0000-0000-000000000010"
  authority         = "https://login.microsoftonline.com"
  tenant_id         = "00000000-0000-0000-0000-000000000002"
  streaming_enabled = true
}

run "dedicated_stream_host" {
  command = plan
  module {
    source = "./modules/hosting"
  }
  assert {
    condition = (
      azurerm_linux_web_app.this.key_vault_reference_identity_id == var.web_identity.id &&
      azurerm_linux_web_app.this.site_config[0].application_stack[0].node_version == "24-lts" &&
      !azurerm_linux_web_app.this.site_config[0].always_on &&
      !azurerm_linux_function_app.this.site_config[0].always_on &&
      azurerm_linux_function_app.stream[0].site_config[0].always_on &&
      azurerm_linux_web_app.this.app_settings["WEB_API_PROXY_ENABLED"] == "true" &&
      startswith(azurerm_linux_web_app.this.app_settings["PORTAL_APIM_SUBSCRIPTION_KEY"], "@Microsoft.KeyVault(SecretUri=") &&
      !contains(keys(azurerm_linux_function_app.this.app_settings), "PORTAL_APIM_SUBSCRIPTION_KEY") &&
      !contains(keys(azurerm_linux_function_app.stream[0].app_settings), "PORTAL_APIM_SUBSCRIPTION_KEY") &&
      !contains(keys(azurerm_linux_web_app.this.app_settings), "VITE_PORTAL_APIM_SUBSCRIPTION_KEY")
    )
    error_message = "Only the Node 24 portal proxy resolves its server-only subscription key with its dedicated identity."
  }
  assert {
    condition = (
      azurerm_linux_web_app.this.auth_settings_v2[0].require_authentication &&
      azurerm_linux_web_app.this.auth_settings_v2[0].unauthenticated_action == "RedirectToLoginPage" &&
      azurerm_linux_web_app.this.auth_settings_v2[0].active_directory_v2[0].client_id == var.web_client_id &&
      azurerm_linux_web_app.this.auth_settings_v2[0].active_directory_v2[0].client_secret_setting_name == "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID" &&
      azurerm_linux_web_app.this.app_settings["OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"] == var.web_identity.client_id &&
      azurerm_linux_web_app.this.app_settings["WEB_PLATFORM_AUTH_ENABLED"] == "true" &&
      contains(azurerm_linux_web_app.this.sticky_settings[0].app_setting_names, "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID") &&
      !azurerm_linux_web_app.this.auth_settings_v2[0].login[0].token_store_enabled
    )
    error_message = "Portal sign-in must protect all content using only its dedicated identity, without stored tokens or secrets."
  }
  assert {
    condition = (
      azurerm_linux_function_app.stream[0].name != azurerm_linux_function_app.this.name &&
      azurerm_linux_function_app.stream[0].service_plan_id == azurerm_service_plan.function.id &&
      azurerm_linux_function_app.stream[0].identity[0].identity_ids == azurerm_linux_function_app.this.identity[0].identity_ids
    )
    error_message = "Streaming needs a distinct host on the existing plan with the same workload identity."
  }
  assert {
    condition = (
      azurerm_linux_function_app.stream[0].app_settings["PYTHON_ENABLE_INIT_INDEXING"] == "1" &&
      !contains(keys(azurerm_linux_function_app.this.app_settings), "PYTHON_ENABLE_INIT_INDEXING") &&
      !contains(keys(azurerm_linux_function_app.this.app_settings), "STREAM_BACKENDS") &&
      azurerm_linux_function_app.stream[0].app_settings["OTEL_SERVICE_NAME"] == "rate-limiter-stream" &&
      azurerm_linux_function_app.stream[0].app_settings["TABLE_NAME"] == "RateLimiter" &&
      azurerm_linux_function_app.stream[0].app_settings["REDIS_HOST"] == "sample.redis.example.net"
    )
    error_message = "HTTP streams indexing and fixed backends belong only to the stream host; limiter stores are shared."
  }
  assert {
    condition = (
      azurerm_linux_function_app.stream[0].auth_settings_v2[0].require_authentication &&
      azurerm_linux_function_app.stream[0].auth_settings_v2[0].active_directory_v2[0].allowed_audiences == azurerm_linux_function_app.this.auth_settings_v2[0].active_directory_v2[0].allowed_audiences &&
      azurerm_linux_function_app.stream[0].site_config[0].application_insights_connection_string == var.application_insights_connection_string &&
      !azurerm_linux_function_app.stream[0].public_network_access_enabled &&
      azurerm_linux_function_app.stream[0].tags["azd-service-name"] == "stream"
    )
    error_message = "The stream host must preserve EasyAuth, native telemetry, private networking and azd mapping."
  }
}

run "disabled_host" {
  command = plan
  module {
    source = "./modules/hosting"
  }
  variables {
    streaming_enabled = false
  }
  assert {
    condition     = length(azurerm_linux_function_app.stream) == 0
    error_message = "The explicit feature gate must omit the stream host."
  }
}
