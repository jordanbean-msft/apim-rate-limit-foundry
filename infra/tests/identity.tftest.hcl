mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      principal_id = "00000000-0000-0000-0000-000000000004"
    }
  }
}
mock_provider "azuread" {
  override_during = plan
  mock_data "azuread_service_principal" {
    defaults = {
      object_id                   = "00000000-0000-0000-0000-000000000008"
      oauth2_permission_scope_ids = { "User.Read" = "e1fe6dd8-ba31-4d61-89e7-88639da4683d" }
    }
  }
  mock_resource "azuread_application" {
    defaults = {
      id        = "/applications/00000000-0000-0000-0000-000000000005"
      client_id = "00000000-0000-0000-0000-000000000006"
    }
  }
  mock_resource "azuread_service_principal" {
    defaults = {
      object_id = "00000000-0000-0000-0000-000000000007"
    }
  }
}
mock_provider "azurecaf" {}
mock_provider "time" {}

variables {
  resource_token      = "sample"
  resource_group_name = "sample-rg"
  location            = "eastus2"
  tags                = {}
  tenant_id           = "00000000-0000-0000-0000-000000000002"
  deployer_object_id  = "00000000-0000-0000-0000-000000000003"
  authority           = "https://login.microsoftonline.com"
  portal_redirect_uri = "https://portal.azurewebsites.net"
  config = {
    admin_object_ids          = []
    reader_object_ids         = []
    propagation_wait_duration = "60s"
  }
}

run "commercial_portal_federation" {
  command = plan
  module {
    source = "./modules/identity"
  }
  assert {
    condition = (
      azuread_app_role_assignment.usage_callback.app_role_id == local.role_ids.Gateway &&
      azuread_app_role_assignment.usage_callback.principal_object_id == azurerm_user_assigned_identity.workload["function"].principal_id &&
      azuread_app_role_assignment.usage_callback.resource_object_id == azuread_service_principal.api.object_id
    )
    error_message = "The internal APIM callback needs the existing Gateway API role granted specifically to the Function workload."
  }
  assert {
    condition = (
      azuread_service_principal_delegated_permission_grant.graph_profile.claim_values == toset(["User.Read"]) &&
      azuread_service_principal_delegated_permission_grant.graph_profile.resource_service_principal_object_id == data.azuread_service_principal.graph.object_id &&
      length([for access in azuread_application.web.required_resource_access : access
        if access.resource_app_id == "00000003-0000-0000-c000-000000000000" &&
        alltrue([for scope in access.resource_access :
          scope.type == "Scope" && scope.id == data.azuread_service_principal.graph.oauth2_permission_scope_ids["User.Read"]
        ])
      ]) == 1
    )
    error_message = "Own-photo access requires only Graph delegated User.Read with explicit tenant consent, separate from the API token."
  }
  assert {
    condition = (
      contains(azuread_application.web.single_page_application[0].redirect_uris, "${var.portal_redirect_uri}/") &&
      contains(azuread_application.web.web[0].redirect_uris, "${var.portal_redirect_uri}/.auth/login/aad/callback") &&
      contains(azuread_application.web.web[0].redirect_uris, "${var.portal_redirect_uri}/.auth/logout") &&
      azuread_application.web.web[0].implicit_grant[0].id_token_issuance_enabled &&
      !azuread_application.web.web[0].implicit_grant[0].access_token_issuance_enabled &&
      azuread_application_federated_identity_credential.web.subject == azurerm_user_assigned_identity.workload["web"].principal_id &&
      azuread_application_federated_identity_credential.web.issuer == "${var.authority}/${var.tenant_id}/v2.0" &&
      toset(azuread_application_federated_identity_credential.web.audiences) == toset(["api://AzureADTokenExchange"])
    )
    error_message = "Reuse the SPA registration for a separate native callback and trust only the web workload identity."
  }
}

run "government_portal_federation" {
  command = plan
  module {
    source = "./modules/identity"
  }
  variables {
    authority           = "https://login.microsoftonline.us"
    portal_redirect_uri = "https://portal.azurewebsites.us"
  }
  assert {
    condition = (
      contains(azuread_application.web.web[0].redirect_uris, "https://portal.azurewebsites.us/.auth/login/aad/callback") &&
      azuread_application_federated_identity_credential.web.issuer == "https://login.microsoftonline.us/${var.tenant_id}/v2.0" &&
      toset(azuread_application_federated_identity_credential.web.audiences) == toset(["api://AzureADTokenExchangeUSGov"])
    )
    error_message = "Government must never federate portal credentials through the Commercial authority or audience."
  }
}
