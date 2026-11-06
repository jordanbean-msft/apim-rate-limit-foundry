resource "azurecaf_name" "workload" {
  for_each      = toset(["function", "gateway", "web"])
  name          = var.resource_token
  resource_type = "azurerm_user_assigned_identity"
  suffixes      = [each.key]
  random_length = 0
  clean_input   = true
}
resource "azurerm_user_assigned_identity" "workload" {
  for_each            = toset(["function", "gateway", "web"])
  name                = azurecaf_name.workload[each.key].result
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}
locals {
  roles = {
    Gateway = ["Application"]
    Admin   = ["User", "Application"]
    Reader  = ["User", "Application"]
  }
  role_ids = { for key, _ in local.roles : key => uuidv5("dns", "${var.tenant_id}/${var.resource_token}/RateLimit.${key}") }
  scope_id = uuidv5("dns", "${var.tenant_id}/${var.resource_token}/access_as_user")
}
resource "azuread_application" "api" {
  display_name     = "${var.resource_token}-limiter-api"
  sign_in_audience = "AzureADMyOrg"
  lifecycle {
    ignore_changes = [identifier_uris]
  }
  api {
    requested_access_token_version = 2
    oauth2_permission_scope {
      id                         = local.scope_id
      value                      = "access_as_user"
      type                       = "User"
      admin_consent_display_name = "Access limiter portal"
      admin_consent_description  = "Read scoped usage and manage configuration according to assigned roles."
      user_consent_display_name  = "Read limiter usage"
      user_consent_description   = "Read usage allowed by your assigned roles."
      enabled                    = true
    }
  }
  dynamic "app_role" {
    for_each = local.roles
    content {
      id                   = local.role_ids[app_role.key]
      value                = "RateLimit.${app_role.key}"
      display_name         = "RateLimit.${app_role.key}"
      description          = "Limiter ${app_role.key} permissions."
      allowed_member_types = app_role.value
      enabled              = true
    }
  }
}
resource "azuread_application_identifier_uri" "api" {
  application_id = azuread_application.api.id
  identifier_uri = "api://${azuread_application.api.client_id}"
}
resource "azuread_service_principal" "api" {
  client_id                    = azuread_application.api.client_id
  app_role_assignment_required = true
}
resource "azuread_application" "web" {
  display_name     = "${var.resource_token}-limiter-portal"
  sign_in_audience = "AzureADMyOrg"
  single_page_application {
    redirect_uris = ["${trimsuffix(var.portal_redirect_uri, "/")}/"]
  }
  required_resource_access {
    resource_app_id = azuread_application.api.client_id
    resource_access {
      id   = local.scope_id
      type = "Scope"
    }
  }
}
resource "azuread_service_principal" "web" {
  client_id = azuread_application.web.client_id
}
resource "azuread_application_pre_authorized" "web" {
  application_id       = azuread_application.api.id
  authorized_client_id = azuread_application.web.client_id
  permission_ids       = [local.scope_id]
}
resource "azuread_service_principal_delegated_permission_grant" "web" {
  service_principal_object_id          = azuread_service_principal.web.object_id
  resource_service_principal_object_id = azuread_service_principal.api.object_id
  claim_values                         = ["access_as_user"]
}
resource "time_sleep" "propagation" {
  create_duration = var.config.propagation_wait_duration
  depends_on      = [azurerm_user_assigned_identity.workload]
}
resource "azuread_app_role_assignment" "gateway" {
  app_role_id         = local.role_ids.Gateway
  principal_object_id = azurerm_user_assigned_identity.workload["gateway"].principal_id
  resource_object_id  = azuread_service_principal.api.object_id
  depends_on          = [time_sleep.propagation]
}
resource "azuread_app_role_assignment" "admin" {
  for_each            = setunion(var.config.admin_object_ids, toset([var.deployer_object_id]))
  app_role_id         = local.role_ids.Admin
  principal_object_id = each.key
  resource_object_id  = azuread_service_principal.api.object_id
}
resource "azuread_app_role_assignment" "reader" {
  for_each            = var.config.reader_object_ids
  app_role_id         = local.role_ids.Reader
  principal_object_id = each.key
  resource_object_id  = azuread_service_principal.api.object_id
}
