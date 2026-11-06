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
locals {
  policy_root = "${path.module}/../../../apim"
  shared = {
    authority               = var.authority
    tenant_id               = var.tenant_id
    api_audience            = var.api_audience
    api_client_id           = trimprefix(var.api_audience, "api://")
    gateway_client_id       = var.identity.client_id
    function_url            = var.function_url
    web_url                 = var.web_url
    burst_calls             = var.config.burst_calls
    burst_seconds           = var.config.burst_seconds
    send_request_timeout    = var.config.send_request_timeout
    audiences               = join("", [for audience in var.config.client_audiences : "<audience>${audience}</audience>"])
    subscription_mapping    = replace(jsonencode(var.config.subscription_tenant_mapping), "\"", "\\\"")
    max_body_bytes          = var.config.max_body_bytes
    max_output_tokens       = var.config.max_output_tokens
    max_document_pages      = var.config.max_document_pages
    max_language_characters = var.config.max_language_characters
    llm_tokens_per_minute   = var.config.llm_tokens_per_minute
    max_input_tokens        = var.max_input_tokens
  }
  api_backends = merge(
    { for key, backend in var.ai : key => backend if key != "responses" },
    contains(keys(var.ai), "responses") && !contains(keys(var.ai), "foundry") ? { foundry = var.ai["responses"] } : {}
  )
  fragments = toset(["identity", "reserve", "settle"])
  ai_paths = {
    foundry               = "/chat/completions"
    responses             = "/responses"
    anthropic             = "/v1/messages"
    document-intelligence = "/analyze"
    language              = "/sentiment"
  }
  backend_paths = {
    foundry               = "/openai/deployments/${try(var.ai["foundry"].model, "")}/chat/completions"
    responses             = "/openai/v1/responses"
    anthropic             = "/anthropic/v1/messages"
    document-intelligence = "/documentintelligence/documentModels/${try(var.ai["document-intelligence"].model, "")}:analyze"
    language              = "/text/analytics/v3.1/sentiment"
  }
  admission = {
    foundry               = templatefile("${local.policy_root}/policies/foundry-admission.xml.tftpl", local.shared)
    responses             = templatefile("${local.policy_root}/policies/responses-admission.xml.tftpl", merge(local.shared, { model = try(var.ai["responses"].model, "") }))
    anthropic             = templatefile("${local.policy_root}/policies/anthropic-admission.xml.tftpl", merge(local.shared, { context_input_tokens = try(var.ai["anthropic"].context_input_tokens, 0), model = try(var.ai["anthropic"].model, "") }))
    document-intelligence = templatefile("${local.policy_root}/policies/document-admission.xml.tftpl", local.shared)
    language              = templatefile("${local.policy_root}/policies/language-admission.xml.tftpl", local.shared)
  }
  settlement = {
    foundry               = templatefile("${local.policy_root}/policies/foundry-settlement.xml.tftpl", local.shared)
    responses             = templatefile("${local.policy_root}/policies/foundry-settlement.xml.tftpl", local.shared)
    anthropic             = templatefile("${local.policy_root}/policies/foundry-settlement.xml.tftpl", local.shared)
    document-intelligence = templatefile("${local.policy_root}/policies/document-submit.xml.tftpl", local.shared)
    language              = templatefile("${local.policy_root}/policies/language-settlement.xml.tftpl", local.shared)
  }
  portal_reads = { for collection in ["health", "policies", "prices", "assignments", "usage", "audit", "reconciliation"] :
    "get-${collection}" => { method = "GET", path = "/${collection}", parameter = false }
  }
  portal_writes = merge([
    for collection in ["policies", "prices", "assignments"] : {
      "put-${collection}"    = { method = "PUT", path = "/${collection}/{id}", parameter = true }
      "delete-${collection}" = { method = "DELETE", path = "/${collection}/{id}", parameter = true }
    }
  ]...)
  portal_operations = merge(local.portal_reads, local.portal_writes, {
    recover       = { method = "POST", path = "/reconciliation/recover", parameter = false }
    usage-summary = { method = "GET", path = "/usage/summary", parameter = false }
  })
}
resource "azurerm_api_management_policy_fragment" "this" {
  for_each          = local.fragments
  name              = "limiter-${each.key}"
  api_management_id = azapi_resource.this.id
  format            = "rawxml"
  value             = templatefile("${local.policy_root}/fragments/${each.key}.xml.tftpl", local.shared)
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
  subscription_required = false
  service_url           = each.value.endpoint
}
resource "azurerm_api_management_api_operation" "submit" {
  for_each            = var.ai
  operation_id        = "${each.key}-submit"
  api_name            = azurerm_api_management_api.ai[each.key == "responses" ? "foundry" : each.key].name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  display_name        = "Bounded ${each.key} request"
  method              = "POST"
  url_template        = local.ai_paths[each.key]
}
resource "azurerm_api_management_api_operation_policy" "submit" {
  for_each            = var.ai
  api_name            = azurerm_api_management_api.ai[each.key == "responses" ? "foundry" : each.key].name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  operation_id        = azurerm_api_management_api_operation.submit[each.key].operation_id
  xml_content = templatefile("${local.policy_root}/policies/ai.xml.tftpl", merge(local.shared, {
    service          = contains(["foundry", "responses", "anthropic"], each.key) ? "foundry" : each.key
    api_protocol     = each.value.api_protocol
    model            = each.value.model
    endpoint         = each.value.endpoint
    ai_audience      = each.value.audience
    api_version      = each.value.api_version
    price_version    = each.value.price_version
    backend_path     = local.backend_paths[each.key]
    version_policy   = each.key == "anthropic" ? "" : "<set-query-parameter name=\"api-version\" exists-action=\"override\"><value>${each.value.api_version}</value></set-query-parameter>"
    provider_headers = each.key == "anthropic" ? "<set-header name=\"anthropic-version\" exists-action=\"override\"><value>${each.value.anthropic_version}</value></set-header>" : ""
    backend_query    = each.key == "document-intelligence" ? "<set-query-parameter name=\"pages\" exists-action=\"override\"><value>@((string)context.Variables[\"document-pages\"])</value></set-query-parameter>" : (each.key == "language" ? "<set-query-parameter name=\"showStats\" exists-action=\"override\"><value>true</value></set-query-parameter>" : "")
    admission        = local.admission[each.key]
    settlement       = local.settlement[each.key]
    llm_policy       = each.key == "foundry" && var.config.enable_optional_llm_policy ? templatefile("${local.policy_root}/policies/llm-limit.xml.tftpl", local.shared) : ""
  }))
  depends_on = [azurerm_api_management_policy_fragment.this]
}
resource "azurerm_api_management_api_operation" "poll" {
  count               = contains(keys(var.ai), "document-intelligence") ? 1 : 0
  operation_id        = "document-poll"
  api_name            = azurerm_api_management_api.ai["document-intelligence"].name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  display_name        = "Read owned document analysis"
  method              = "GET"
  url_template        = "/analyzeResults/{operationId}"
  template_parameter {
    name     = "operationId"
    required = true
    type     = "string"
  }
}
resource "azurerm_api_management_api_operation_policy" "poll" {
  count               = contains(keys(var.ai), "document-intelligence") ? 1 : 0
  api_name            = azurerm_api_management_api.ai["document-intelligence"].name
  api_management_name = azapi_resource.this.name
  resource_group_name = var.resource_group_name
  operation_id        = azurerm_api_management_api_operation.poll[0].operation_id
  xml_content = templatefile("${local.policy_root}/policies/document-poll.xml.tftpl", merge(local.shared, {
    model       = var.ai["document-intelligence"].model
    endpoint    = var.ai["document-intelligence"].endpoint
    ai_audience = var.ai["document-intelligence"].audience
    api_version = var.ai["document-intelligence"].api_version
  }))
  depends_on = [azurerm_api_management_policy_fragment.this]
}
resource "azurerm_api_management_api" "portal" {
  name                  = "portal"
  resource_group_name   = var.resource_group_name
  api_management_name   = azapi_resource.this.name
  revision              = "1"
  display_name          = "Limiter control plane"
  path                  = "portal"
  protocols             = ["https"]
  subscription_required = false
  service_url           = "${var.function_url}/api"
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
  for_each                  = setunion(toset(keys(local.api_backends)), toset(["portal"]))
  identifier                = "applicationinsights"
  resource_group_name       = var.resource_group_name
  api_management_name       = azapi_resource.this.name
  api_name                  = each.key == "portal" ? azurerm_api_management_api.portal.name : azurerm_api_management_api.ai[each.key].name
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
    headers_to_log = ["X-Correlation-ID", "X-RateLimit-Reservation", "X-RateLimit-Estimated"]
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
