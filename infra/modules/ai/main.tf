locals {
  enabled         = { for key, value in var.config : key => value if value.enabled }
  created         = { for key, value in local.enabled : key => value if value.create }
  kinds           = { foundry = "OpenAI" }
  created_foundry = { for key, value in local.created : key => value if key == "foundry" }
  created_endpoints = {
    for key, account in azurerm_cognitive_account.this : key => (
      key == "foundry" ?
      "https://${account.custom_subdomain_name}.openai.${var.azure_cloud == "government" ? "azure.us" : "azure.com"}" :
      account.endpoint
    )
  }
  protocol_backends = {
    for key, protocol in {
      responses = {
        enabled     = var.protocols.responses.enabled, id = var.protocols.responses.resource_id,
        endpoint    = var.protocols.responses.endpoint, audience = var.protocols.responses.audience,
        model       = var.protocols.responses.deployment_name, price_version = var.protocols.responses.price_version,
        api_version = var.protocols.responses.api_version, api_protocol = "openai-responses",
        role        = var.protocols.responses.role_definition_name
      }
    } : key => protocol if protocol.enabled
  }
  existing_role_pairs = [for key, backend in local.enabled :
    lower("${backend.resource_id}|${key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"}")
    if backend.resource_id != ""
  ]
  gateway_role_groups = {
    for key, backend in local.enabled :
    (backend.create ? "create:${key}" : lower("${backend.resource_id}|${key == "foundry" ? "Cognitive Services OpenAI User" : "Cognitive Services User"}")) => key...
  }
  gateway_backends = {
    for keys in values(local.gateway_role_groups) : sort(keys)[0] => local.enabled[sort(keys)[0]]
  }
  reference_resource_groups = {
    for key, backend in local.enabled : backend.resource_id => key... if !backend.create
  }
  protocol_role_groups_by_scope = {
    for key, backend in local.protocol_backends : lower("${backend.id}|${backend.role}") => key...
    if !contains(local.existing_role_pairs, lower("${backend.id}|${backend.role}"))
  }
  protocol_role_groups = {
    for keys in values(local.protocol_role_groups_by_scope) :
    "${local.protocol_backends[sort(keys)[0]].id}|${local.protocol_backends[sort(keys)[0]].role}" =>
    local.protocol_backends[sort(keys)[0]]
  }
  additional_role_groups = {
    for key, model in var.llm_models : "${lower(model.resource_id)}|${lower(model.role_definition_name)}" => {
      id   = model.resource_id
      role = model.role_definition_name
    }...
    if !contains([for pair in local.existing_role_pairs : lower(pair)], "${lower(model.resource_id)}|${lower(model.role_definition_name)}") &&
    !contains([for pair in keys(local.protocol_role_groups) : lower(pair)], "${lower(model.resource_id)}|${lower(model.role_definition_name)}")
  }
  gateway_additional_roles = {
    for key, bindings in local.additional_role_groups : key => bindings[0]
  }
  stream_role_groups = {
    for backend in concat(
      contains(keys(local.enabled), "foundry") ? [{
        id   = local.enabled["foundry"].create ? azurerm_cognitive_account.this["foundry"].id : local.enabled["foundry"].resource_id
        role = "Cognitive Services OpenAI User"
        key  = local.enabled["foundry"].resource_id == "" ? "create:foundry" : lower("${local.enabled["foundry"].resource_id}|Cognitive Services OpenAI User")
      }] : [],
      [for backend in values(local.protocol_backends) : { id = backend.id, role = backend.role, key = lower("${backend.id}|${backend.role}") }],
      [for model in values(var.llm_models) : { id = model.resource_id, role = model.role_definition_name, key = lower("${model.resource_id}|${model.role_definition_name}") }]
    ) : backend.key => backend... if var.streaming_enabled
  }
}
resource "azurerm_role_assignment" "stream" {
  for_each             = local.stream_role_groups
  name                 = uuidv5("dns", "${each.value[0].id}/${var.function_principal_id}/${each.value[0].role}")
  scope                = each.value[0].id
  role_definition_name = each.value[0].role
  principal_id         = var.function_principal_id
}
resource "azurecaf_name" "this" {
  for_each      = local.created
  name          = var.resource_token
  resource_type = "azurerm_cognitive_account"
  suffixes      = [each.key]
  random_length = 0
  clean_input   = true
}
resource "azurecaf_name" "foundry_identity" {
  for_each      = local.created_foundry
  name          = var.resource_token
  resource_type = "azurerm_user_assigned_identity"
  suffixes      = ["foundry"]
  random_length = 0
  clean_input   = true
}
resource "azurerm_user_assigned_identity" "foundry" {
  for_each            = local.created_foundry
  name                = azurecaf_name.foundry_identity[each.key].result
  resource_group_name = var.resource_group_name
  location            = each.value.location
  tags                = var.tags
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
  project_management_enabled    = false
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = var.tags
  dynamic "identity" {
    for_each = each.key == "foundry" ? [azurerm_user_assigned_identity.foundry[each.key].id] : []
    content {
      type         = "UserAssigned"
      identity_ids = [identity.value]
    }
  }
  lifecycle {
    postcondition {
      condition     = each.value.resource_id == "" || lower(each.value.resource_id) == lower(self.id)
      error_message = "A created backend's supplied resource_id must identify that same account."
    }
  }
}
resource "azurerm_cognitive_deployment" "foundry" {
  for_each             = local.created_foundry
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
resource "azurerm_cognitive_deployment" "managed" {
  for_each = var.managed_deployments
  name     = each.key
  cognitive_account_id = var.config.foundry.create ? (
    azurerm_cognitive_account.this["foundry"].id
  ) : var.config.foundry.resource_id
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
  name                 = uuidv5("dns", "${each.value.id}/${var.gateway_principal_id}/${each.value.role}")
  scope                = each.value.id
  role_definition_name = each.value.role
  principal_id         = var.gateway_principal_id
}
resource "azurerm_role_assignment" "additional_gateway" {
  for_each             = local.gateway_additional_roles
  name                 = uuidv5("dns", "${each.value.id}/${var.gateway_principal_id}/${each.value.role}")
  scope                = each.value.id
  role_definition_name = each.value.role
  principal_id         = var.gateway_principal_id
}
