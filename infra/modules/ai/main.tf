locals {
  enabled = { for key, value in var.config : key => value if value.enabled }
  created = { for key, value in local.enabled : key => value if value.create }
  kinds   = { foundry = "OpenAI", document-intelligence = "FormRecognizer", language = "TextAnalytics" }
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
  for_each             = local.enabled
  name                 = uuidv5("dns", "${each.value.create ? azurerm_cognitive_account.this[each.key].id : each.value.resource_id}/${var.gateway_principal_id}/ai")
  scope                = each.value.create ? azurerm_cognitive_account.this[each.key].id : each.value.resource_id
  role_definition_name = each.key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"
  principal_id         = var.gateway_principal_id
}
