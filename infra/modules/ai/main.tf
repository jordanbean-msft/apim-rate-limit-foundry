locals {
  enabled = { for key, value in var.config : key => value if value.enabled }
  created = { for key, value in local.enabled : key => value if value.create }
  kinds   = { foundry = "OpenAI", document-intelligence = "FormRecognizer", language = "TextAnalytics" }
  protocol_backends = {
    for key, protocol in {
      responses = {
        enabled           = var.protocols.responses.enabled, id = var.protocols.responses.resource_id,
        endpoint          = var.protocols.responses.endpoint, audience = var.protocols.responses.audience,
        model             = var.protocols.responses.deployment_name, price_version = var.protocols.responses.price_version,
        api_version       = var.protocols.responses.api_version, api_protocol = "openai-responses", context_input_tokens = 0,
        anthropic_version = "", role = var.protocols.responses.role_definition_name
      }
      anthropic = {
        enabled           = var.protocols.anthropic.enabled, id = var.protocols.anthropic.resource_id,
        endpoint          = var.protocols.anthropic.endpoint, audience = var.protocols.anthropic.audience,
        model             = var.protocols.anthropic.deployment_name, price_version = var.protocols.anthropic.price_version,
        api_version       = "", api_protocol = "anthropic-messages", context_input_tokens = var.protocols.anthropic.context_input_tokens,
        anthropic_version = var.protocols.anthropic.anthropic_version, role = var.protocols.anthropic.role_definition_name
      }
    } : key => protocol if protocol.enabled
  }
  existing_role_pairs = [for key, backend in local.enabled :
    "${backend.resource_id}|${key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"}"
    if backend.resource_id != ""
  ]
  gateway_role_groups = {
    for key, backend in local.enabled :
    (backend.create ? "create:${key}" : "${backend.resource_id}|${key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"}") => key...
  }
  gateway_backends = {
    for keys in values(local.gateway_role_groups) : sort(keys)[0] => local.enabled[sort(keys)[0]]
  }
  reference_resource_groups = {
    for key, backend in local.enabled : backend.resource_id => key... if !backend.create
  }
  protocol_role_groups = {
    for key, backend in local.protocol_backends : "${backend.id}|${backend.role}" => backend...
    if !contains(local.existing_role_pairs, "${backend.id}|${backend.role}")
  }
}
resource "azurecaf_name" "this" {
  for_each      = local.created
  name          = var.resource_token
  resource_type = "azurerm_cognitive_account"
  suffixes      = [each.key]
  random_length = 0
  clean_input   = true
}
resource "azurerm_cognitive_account" "this" {
  for_each                      = local.created
  name                          = azurecaf_name.this[each.key].result
  custom_subdomain_name         = azurecaf_name.this[each.key].result
  resource_group_name           = var.resource_group_name
  location                      = each.value.location
  kind                          = local.kinds[each.key]
  sku_name                      = each.value.sku_name
  local_auth_enabled            = false
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = var.tags
  lifecycle {
    postcondition {
      condition     = each.value.resource_id == "" || lower(each.value.resource_id) == lower(self.id)
      error_message = "A created backend's supplied resource_id must identify that same account."
    }
  }
}
resource "azurerm_cognitive_deployment" "foundry" {
  for_each             = { for key, value in local.created : key => value if key == "foundry" }
  name                 = each.value.deployment_name
  cognitive_account_id = azurerm_cognitive_account.this[each.key].id
  model {
    format  = "OpenAI"
    name    = each.value.model_name
    version = each.value.model_version
  }
  sku {
    name     = each.value.deployment_sku
    capacity = each.value.deployment_capacity
  }
}
resource "azurerm_role_assignment" "gateway" {
  for_each = local.gateway_backends
  name = uuidv5("dns",
    each.value.create || each.key == sort(try(local.reference_resource_groups[each.value.resource_id], [each.key]))[0] ?
    "${each.value.create ? azurerm_cognitive_account.this[each.key].id : each.value.resource_id}/${var.gateway_principal_id}/ai" :
    "${each.value.resource_id}/${var.gateway_principal_id}/${each.key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"}"
  )
  scope                = each.value.create ? azurerm_cognitive_account.this[each.key].id : each.value.resource_id
  role_definition_name = each.key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"
  principal_id         = var.gateway_principal_id
}
resource "azurerm_role_assignment" "protocol" {
  for_each             = local.protocol_role_groups
  name                 = uuidv5("dns", "${each.value[0].id}/${var.gateway_principal_id}/${each.value[0].role}")
  scope                = each.value[0].id
  role_definition_name = each.value[0].role
  principal_id         = var.gateway_principal_id
}
