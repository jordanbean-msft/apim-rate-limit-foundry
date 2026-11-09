resource "azapi_resource" "this" {
  type      = "Microsoft.ApiManagement/service@2024-05-01"
  name      = var.name
  parent_id = var.resource_group_id
  location  = var.location
  body = {
    sku = {
      name     = split("_", var.config.sku_name)[0]
      capacity = tonumber(split("_", var.config.sku_name)[1])
    }
    identity = {
      type                   = "UserAssigned"
      userAssignedIdentities = { (var.identity.id) = {} }
    }
    properties = {
      publisherName       = var.config.publisher_name
      publisherEmail      = var.config.publisher_email
      virtualNetworkType  = var.public_network_access_enabled ? "None" : "Internal"
      publicNetworkAccess = "Enabled"
      virtualNetworkConfiguration = var.public_network_access_enabled ? null : {
        subnetResourceId = var.subnet_id
      }
      customProperties = {
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Protocols.Server.Http2"                                = "False"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA" = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA" = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA"   = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA"   = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_128_CBC_SHA"         = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_128_CBC_SHA256"      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_128_GCM_SHA256"      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_256_CBC_SHA"         = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_256_CBC_SHA256"      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TLS_RSA_WITH_AES_256_GCM_SHA384"      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Ssl30"                      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10"                      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11"                      = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30"                              = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10"                              = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11"                              = "false"
        "Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Ciphers.TripleDes168"                         = "false"
      }
    }
  }
  response_export_values = ["properties.gatewayUrl"]
  timeouts {
    create = "3h"
    update = "3h"
    delete = "3h"
  }
  tags = var.tags
}
resource "azurerm_api_management_logger" "this" {
  name                = "application-insights"
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  resource_id         = var.application_insights_id
  application_insights {
    instrumentation_key = var.instrumentation_key
  }
}
resource "azurerm_api_management_logger" "usage" {
  name                = "usage-events"
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  resource_id         = var.event_hub.id
  buffered            = true
  description         = "Best-effort finalized usage v2; APIM is the only producer."
  eventhub {
    name                             = var.event_hub.name
    endpoint_uri                     = var.event_hub.endpoint_address
    user_assigned_identity_client_id = var.identity.client_id
  }
}
locals {
  policy_root = "${path.module}/../../../apim"
  shared = {
    authority             = var.authority
    tenant_id             = var.tenant_id
    api_audience          = var.api_audience
    api_client_id         = trimprefix(var.api_audience, "api://")
    gateway_client_id     = var.identity.client_id
    function_client_id    = var.function_identity.client_id
    function_principal_id = var.function_identity.principal_id
    function_url          = var.function_url
    stream_url            = var.stream_url
    streaming_enabled     = var.streaming_enabled
    web_url               = var.web_url
    burst_calls           = var.config.burst_calls
    burst_seconds         = var.config.burst_seconds
    send_request_timeout  = var.config.send_request_timeout
    audiences             = join("", [for audience in var.config.client_audiences : "<audience>${audience}</audience>"])
    max_body_bytes        = var.config.max_body_bytes
    max_output_tokens     = var.config.max_output_tokens
    llm_tokens_per_minute = var.config.llm_tokens_per_minute
    max_input_tokens      = var.max_input_tokens
    model_registry        = replace(jsonencode(var.model_registry), "\"", "\\\"")
  }
  route_backends = merge(var.ai, var.route_backends)
  api_backends = merge(
    { for key, backend in local.route_backends : key => backend if key != "responses" },
    contains(keys(local.route_backends), "responses") && !contains(keys(local.route_backends), "foundry") ? { foundry = local.route_backends["responses"] } : {}
  )
  ai_backends = merge(
    {
      for key, backend in local.route_backends :
      "ai-${key}" => trimsuffix(backend.endpoint, "/")
    },
    {
      for key, model in var.model_registry :
      "ai-model-${substr(sha256(key), 0, 12)}" => trimsuffix(model.endpoint, "/")
    }
  )
  fragments = toset(["identity", "model-lookup", "budget-check", "usage-record"])
  ai_paths = {
    foundry   = "/chat/completions"
    responses = "/responses"
  }
  backend_paths = {
    foundry   = "/openai/deployments/${try(local.route_backends["foundry"].model, "")}/chat/completions"
    responses = "/openai/v1/responses"
  }
  admission = {
    foundry   = templatefile("${local.policy_root}/policies/foundry-admission.xml.tftpl", local.shared)
    responses = templatefile("${local.policy_root}/policies/responses-admission.xml.tftpl", local.shared)
  }
  portal_reads = { for collection in ["health", "dashboard", "models", "budgets", "organizations", "prices", "assignments", "usage", "audit", "chargeback"] :
    "get-${collection}" => { method = "GET", path = "/${collection}", parameter = false }
  }
  portal_writes = merge([
    for collection in ["budgets", "organizations", "prices", "assignments"] : {
      "put-${collection}"    = { method = "PUT", path = "/${collection}/{id}", parameter = true }
      "delete-${collection}" = { method = "DELETE", path = "/${collection}/{id}", parameter = true }
    }
  ]...)
  portal_operations = merge(local.portal_reads, local.portal_writes, {
    rebuild       = { method = "POST", path = "/counters/rebuild", parameter = false }
    budget-status = { method = "GET", path = "/budgets/status", parameter = false }
  })
}
resource "azurerm_api_management_policy_fragment" "this" {
  for_each          = local.fragments
  name              = "limiter-${each.key}"
  api_management_id = azapi_resource.this.id
  format            = "rawxml"
  value             = templatefile("${local.policy_root}/fragments/${each.key}.xml.tftpl", local.shared)
}
resource "azurerm_api_management_backend" "ai" {
  for_each            = local.ai_backends
  name                = each.key
  resource_group_name = var.resource_group_name
  api_management_name = azapi_resource.this.name
  protocol            = "http"
  url                 = each.value
  description         = "Managed-identity AI gateway backend"
  tls {
    validate_certificate_chain = true
    validate_certificate_name  = true
  }
  depends_on = [azapi_resource.this]
}
resource "azurerm_api_management_api" "ai" {
  for_each              = local.api_backends
  name                  = each.key
  resource_group_name   = var.resource_group_name
  api_management_name   = azapi_resource.this.name
  revision              = "1"
  display_name          = each.key
  path                  = each.key
  protocols             = ["https"]
  subscription_required = true
  service_url           = each.value.endpoint
}
resource "azurerm_api_management_api_operation" "submit" {
  for_each            = local.route_backends
  operation_id        = "${each.key}-submit"
  api_name            = azurerm_api_management_api.ai[each.key == "responses" ? "foundry" : each.key].name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  display_name        = "Bounded ${each.key} request"
  method              = "POST"
  url_template        = local.ai_paths[each.key]
}
resource "azurerm_api_management_api_operation_policy" "submit" {
  for_each            = local.route_backends
  api_name            = azurerm_api_management_api.ai[each.key == "responses" ? "foundry" : each.key].name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  operation_id        = azurerm_api_management_api_operation.submit[each.key].operation_id
  xml_content = templatefile("${local.policy_root}/policies/ai.xml.tftpl", merge(local.shared, {
    api_protocol         = each.value.api_protocol
    model                = each.value.model
    model_lookup         = each.value.api_protocol == "" ? "" : "<include-fragment fragment-id=\"limiter-model-lookup\" />"
    legacy_default_alias = try(var.legacy_defaults[each.key], "")
    endpoint             = each.value.endpoint
    backend_id           = "ai-${each.key}"
    ai_audience          = each.value.audience
    api_version          = each.value.api_version
    price_version        = each.value.price_version
    backend_path         = local.backend_paths[each.key]
    admission            = local.admission[each.key]
    llm_policy           = var.config.enable_optional_llm_policy ? templatefile("${local.policy_root}/policies/llm-limit.xml.tftpl", local.shared) : ""
  }))
  depends_on = [azurerm_api_management_policy_fragment.this, azurerm_api_management_logger.usage]
}
resource "azurerm_api_management_api" "internal" {
  name                  = "internal-usage"
  resource_group_name   = var.resource_group_name
  api_management_name   = azapi_resource.this.name
  revision              = "1"
  display_name          = "Function-only finalized usage callback"
  path                  = "internal"
  protocols             = ["https"]
  subscription_required = false
}
resource "azurerm_api_management_api_operation" "usage_events" {
  operation_id        = "usage-events"
  api_name            = azurerm_api_management_api.internal.name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  display_name        = "Publish recorded usage"
  method              = "POST"
  url_template        = "/usage-events"
}
resource "azurerm_api_management_api_operation_policy" "usage_events" {
  api_name            = azurerm_api_management_api.internal.name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  operation_id        = azurerm_api_management_api_operation.usage_events.operation_id
  xml_content         = templatefile("${local.policy_root}/policies/usage-events.xml.tftpl", local.shared)
  depends_on          = [azurerm_api_management_logger.usage]
}
resource "azurerm_api_management_api" "portal" {
  name                  = "portal"
  resource_group_name   = var.resource_group_name
  api_management_name   = azapi_resource.this.name
  revision              = "1"
  display_name          = "Limiter control plane"
  path                  = "portal"
  protocols             = ["https"]
  subscription_required = true
  service_url           = "${var.function_url}/api"
}
resource "azurerm_api_management_product" "this" {
  for_each              = toset(["inference", "portal"])
  product_id            = each.key
  api_management_name   = azapi_resource.this.name
  resource_group_name   = var.resource_group_name
  display_name          = each.key == "inference" ? "AI inference applications" : "Server-side portal"
  subscription_required = true
  approval_required     = false
  published             = true
}
resource "azurerm_api_management_product_api" "inference" {
  for_each            = local.api_backends
  api_name            = azurerm_api_management_api.ai[each.key].name
  product_id          = azurerm_api_management_product.this["inference"].product_id
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
}
resource "azurerm_api_management_product_api" "portal" {
  api_name            = azurerm_api_management_api.portal.name
  product_id          = azurerm_api_management_product.this["portal"].product_id
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
}
resource "azurerm_api_management_subscription" "application" {
  for_each            = var.applications.inference
  subscription_id     = each.key
  display_name        = each.value.display_name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  product_id          = azurerm_api_management_product.this["inference"].id
  state               = "active"
  allow_tracing       = false
}
resource "azurerm_api_management_subscription" "portal" {
  subscription_id     = var.applications.portal.subscription_id
  display_name        = var.applications.portal.display_name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  product_id          = azurerm_api_management_product.this["portal"].id
  state               = "active"
  allow_tracing       = false
}
resource "azurerm_api_management_api_operation" "portal" {
  for_each            = local.portal_operations
  operation_id        = each.key
  api_name            = azurerm_api_management_api.portal.name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  display_name        = each.key
  method              = each.value.method
  url_template        = each.value.path
  dynamic "template_parameter" {
    for_each = each.value.parameter ? [1] : []
    content {
      name     = "id"
      required = true
      type     = "string"
    }
  }
}
resource "azurerm_api_management_api_policy" "portal" {
  api_name            = azurerm_api_management_api.portal.name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  xml_content         = templatefile("${local.policy_root}/policies/portal.xml.tftpl", local.shared)
}
resource "azurerm_api_management_api_diagnostic" "this" {
  for_each                  = setunion(toset(keys(local.api_backends)), toset(["portal", "internal"]))
  identifier                = "applicationinsights"
  resource_group_name       = var.resource_group_name
  api_management_name       = azapi_resource.this.name
  api_name                  = each.key == "portal" ? azurerm_api_management_api.portal.name : (each.key == "internal" ? azurerm_api_management_api.internal.name : azurerm_api_management_api.ai[each.key].name)
  api_management_logger_id  = azurerm_api_management_logger.this.id
  always_log_errors         = true
  sampling_percentage       = var.config.diagnostic_sampling_percentage
  verbosity                 = "information"
  log_client_ip             = false
  http_correlation_protocol = "W3C"
  frontend_request {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }
  frontend_response {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }
  backend_request {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }
  backend_response {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }
}
