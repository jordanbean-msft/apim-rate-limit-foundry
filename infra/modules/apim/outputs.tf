output "id" {
  description = "Gateway resource."
  value       = azapi_resource.this.id
}
output "gateway_url" {
  description = "Cloud-aware gateway URL supplied by ARM."
  value       = azapi_resource.this.output.properties.gatewayUrl
}
output "ai_backends" {
  description = "Managed-identity APIM backend entities for AI endpoints."
  value = { for key, backend in azurerm_api_management_backend.ai : key => {
    id       = backend.id
    name     = backend.name
    url      = backend.url
    protocol = backend.protocol
  } }
}
output "llm_routes" {
  description = "Only enabled LLM operations and their pinned protocol/model contracts."
  value = { for key, backend in local.route_backends : key => {
    path         = "/${key == "responses" ? "foundry" : key}${local.ai_paths[key]}"
    api_protocol = backend.api_protocol
    model        = try(var.legacy_defaults[key], "")
    backend_path = try(var.legacy_defaults[key], "") == "" ? "" : local.backend_paths[key]
    api_version  = try(var.legacy_defaults[key], "") == "" ? "" : backend.api_version
    models = { for model_key, model in var.model_registry : trimprefix(model_key, "${model.api_protocol}:") => {
      deployment_name   = model.model
      price_version     = model.price_version
      max_input_tokens  = model.max_input_tokens
      max_output_tokens = model.max_output_tokens
    } if model.api_protocol == backend.api_protocol }
  } if backend.api_protocol != "" }
}
output "portal_subscription_key" {
  description = "Server-only portal product key for Key Vault; never expose through root outputs or browser configuration."
  value       = azurerm_api_management_subscription.portal.primary_key
  sensitive   = true
}
output "subscription_contract" {
  description = "Safe operational product/API associations; no key values are exported."
  value = {
    products = { for key, product in azurerm_api_management_product.this : key => {
      subscription_required = product.subscription_required
    } }
    inference_apis = { for key, api in azurerm_api_management_api.ai : key => {
      subscription_required = api.subscription_required
      product_id            = azurerm_api_management_product_api.inference[key].product_id
    } }
    portal_api = {
      subscription_required = azurerm_api_management_api.portal.subscription_required
      product_id            = azurerm_api_management_product_api.portal.product_id
    }
    application_ids        = [for subscription in values(azurerm_api_management_subscription.application) : subscription.subscription_id]
    portal_subscription_id = azurerm_api_management_subscription.portal.subscription_id
  }
}
output "usage_telemetry_contract" {
  description = "Secretless logger and Function-only callback wiring for deployment verification."
  value = {
    logger = {
      hub_id             = azurerm_api_management_logger.usage.resource_id
      identity_client_id = azurerm_api_management_logger.usage.eventhub[0].user_assigned_identity_client_id
      endpoint_address   = azurerm_api_management_logger.usage.eventhub[0].endpoint_uri
    }
    callback = {
      subscription_required = azurerm_api_management_api.internal.subscription_required
      policy                = azurerm_api_management_api_operation_policy.usage_events.xml_content
    }
  }
}
