resource "azurerm_service_plan" "function" {
  name                = "${var.names.plan}-function"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.config.functions_sku
  worker_count        = var.config.function_workers
  tags                = var.tags
}
resource "azurerm_service_plan" "web" {
  name                = "${var.names.plan}-web"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.config.web_sku
  worker_count        = var.config.web_workers
  tags                = var.tags
}
resource "azurerm_linux_function_app" "this" {
  name                                           = var.names.function
  resource_group_name                            = var.resource_group_name
  location                                       = var.location
  service_plan_id                                = azurerm_service_plan.function.id
  storage_account_name                           = var.storage_account_name
  storage_uses_managed_identity                  = true
  content_share_force_disabled                   = true
  functions_extension_version                    = "~4"
  https_only                                     = true
  public_network_access_enabled                  = var.public_network_access_enabled
  virtual_network_subnet_id                      = var.public_network_access_enabled ? null : var.network.functions_subnet_id
  builtin_logging_enabled                        = false
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  app_settings = merge(var.function_settings, {
    FUNCTIONS_WORKER_RUNTIME        = "python"
    AzureWebJobsStorage__credential = "managedidentity"
    AzureWebJobsStorage__clientId   = var.function_identity.client_id
  })
  identity {
    type         = "UserAssigned"
    identity_ids = [var.function_identity.id]
  }
  site_config {
    always_on                              = var.config.function_always_on
    minimum_tls_version                    = var.config.minimum_tls_version
    scm_minimum_tls_version                = var.config.minimum_tls_version
    ftps_state                             = "Disabled"
    vnet_route_all_enabled                 = !var.public_network_access_enabled
    application_insights_connection_string = var.application_insights_connection_string
    app_service_logs {
      disk_quota_mb         = var.config.log_disk_quota_mb
      retention_period_days = var.config.log_retention_days
    }
    application_stack {
      python_version = var.config.python_version
    }
    dynamic "cors" {
      for_each = length(var.config.cors_origins) > 0 ? [var.config.cors_origins] : []
      content {
        allowed_origins     = cors.value
        support_credentials = false
      }
    }
  }
  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = true
    require_https          = true
    unauthenticated_action = "Return401"
    default_provider       = "azureactivedirectory"
    active_directory_v2 {
      client_id            = var.api_client_id
      tenant_auth_endpoint = "${var.authority}/${var.tenant_id}/v2.0"
      allowed_audiences    = [var.api_audience, var.api_client_id]
      allowed_applications = var.config.allowed_client_applications
    }
    login {
      token_store_enabled = false
    }
  }
  tags = merge(var.tags, { "azd-service-name" = "api" })
}
resource "azurerm_linux_function_app" "stream" {
  count                                          = var.streaming_enabled ? 1 : 0
  name                                           = var.names.stream
  resource_group_name                            = var.resource_group_name
  location                                       = var.location
  service_plan_id                                = azurerm_service_plan.function.id
  storage_account_name                           = var.storage_account_name
  storage_uses_managed_identity                  = true
  content_share_force_disabled                   = true
  functions_extension_version                    = "~4"
  https_only                                     = true
  public_network_access_enabled                  = var.public_network_access_enabled
  virtual_network_subnet_id                      = var.public_network_access_enabled ? null : var.network.functions_subnet_id
  builtin_logging_enabled                        = false
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  app_settings = merge(var.function_settings, var.stream_settings, {
    FUNCTIONS_WORKER_RUNTIME        = "python"
    AzureWebJobsStorage__credential = "managedidentity"
    AzureWebJobsStorage__clientId   = var.function_identity.client_id
  })
  identity {
    type         = "UserAssigned"
    identity_ids = [var.function_identity.id]
  }
  site_config {
    always_on                              = var.config.stream_always_on
    minimum_tls_version                    = var.config.minimum_tls_version
    scm_minimum_tls_version                = var.config.minimum_tls_version
    ftps_state                             = "Disabled"
    vnet_route_all_enabled                 = !var.public_network_access_enabled
    application_insights_connection_string = var.application_insights_connection_string
    app_service_logs {
      disk_quota_mb         = var.config.log_disk_quota_mb
      retention_period_days = var.config.log_retention_days
    }
    application_stack {
      python_version = var.config.python_version
    }
  }
  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = true
    require_https          = true
    unauthenticated_action = "Return401"
    default_provider       = "azureactivedirectory"
    active_directory_v2 {
      client_id            = var.api_client_id
      tenant_auth_endpoint = "${var.authority}/${var.tenant_id}/v2.0"
      allowed_audiences    = [var.api_audience, var.api_client_id]
      allowed_applications = var.config.allowed_client_applications
    }
    login {
      token_store_enabled = false
    }
  }
  tags = merge(var.tags, { "azd-service-name" = "stream" })
}
resource "azurerm_linux_web_app" "this" {
  key_vault_reference_identity_id                = var.web_identity.id
  name                                           = var.names.web
  resource_group_name                            = var.resource_group_name
  location                                       = var.location
  service_plan_id                                = azurerm_service_plan.web.id
  https_only                                     = true
  public_network_access_enabled                  = var.public_network_access_enabled
  virtual_network_subnet_id                      = var.public_network_access_enabled ? null : var.network.web_subnet_id
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false
  app_settings = merge(var.web_settings, {
    WEB_PLATFORM_AUTH_ENABLED              = "true"
    OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID = var.web_identity.client_id
  })
  identity {
    type         = "UserAssigned"
    identity_ids = [var.web_identity.id]
  }
  site_config {
    always_on               = var.config.web_always_on
    minimum_tls_version     = var.config.minimum_tls_version
    scm_minimum_tls_version = var.config.minimum_tls_version
    ftps_state              = "Disabled"
    vnet_route_all_enabled  = !var.public_network_access_enabled
    app_command_line        = "node server/index.mjs"
    application_stack {
      node_version = var.config.node_version
    }
  }
  auth_settings_v2 {
    auth_enabled           = true
    require_authentication = true
    require_https          = true
    unauthenticated_action = "RedirectToLoginPage"
    default_provider       = "azureactivedirectory"
    active_directory_v2 {
      client_id                  = var.web_client_id
      tenant_auth_endpoint       = "${var.authority}/${var.tenant_id}/v2.0"
      client_secret_setting_name = "OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"
      allowed_audiences          = [var.web_client_id]
    }
    login {
      token_store_enabled = false
    }
  }
  sticky_settings {
    app_setting_names = ["OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID"]
  }
  tags = merge(var.tags, { "azd-service-name" = "web" })
  logs {
    application_logs {
      file_system_level = "Information"
    }
    http_logs {
      file_system {
        retention_in_days = var.config.log_retention_days
        retention_in_mb   = var.config.log_disk_quota_mb
      }
    }
    detailed_error_messages = false
    failed_request_tracing  = false
  }
}
