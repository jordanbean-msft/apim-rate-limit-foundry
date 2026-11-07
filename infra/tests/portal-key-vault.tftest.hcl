mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.KeyVault/vaults/sample-portal"
      vault_uri = "https://sample-portal.vault.azure.net/"
    }
  }
  mock_resource "azurerm_key_vault_secret" {
    defaults = {
      versionless_id = "https://sample-portal.vault.azure.net/secrets/portal-apim-subscription-key"
    }
  }
  mock_data "azurerm_monitor_diagnostic_categories" {
    defaults = {
      log_category_types = ["AuditEvent", "AzurePolicyEvaluationDetails"]
      metrics            = ["AllMetrics"]
    }
  }
}
mock_provider "azurecaf" {
  override_during = plan
  mock_resource "azurecaf_name" {
    defaults = { result = "sample-portal" }
  }
}
mock_provider "time" {}

variables {
  resource_token                = "sample"
  resource_group_name           = "sample-rg"
  location                      = "eastus2"
  tags                          = {}
  tenant_id                     = "00000000-0000-0000-0000-000000000002"
  deployer_principal_id         = "00000000-0000-0000-0000-000000000003"
  web_principal_id              = "00000000-0000-0000-0000-000000000009"
  public_network_access_enabled = false
  private_endpoint_subnet_id    = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/endpoints"
  workspace_id                  = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.OperationalInsights/workspaces/sample"
  portal_subscription_key       = "mock-native-portal-key"
  config = {
    sku_name = "standard", soft_delete_retention_days = 90, purge_protection_enabled = true, propagation_wait_duration = "60s"
  }
}
run "private_portal_secret_is_identity_scoped_and_audited" {
  command = plan
  module {
    source = "./modules/portal_key_vault"
  }
  assert {
    condition = (
      !azurerm_key_vault.this.public_network_access_enabled &&
      azurerm_key_vault.this.rbac_authorization_enabled &&
      azurerm_key_vault.this.purge_protection_enabled &&
      azurerm_role_assignment.deployer.role_definition_name == "Key Vault Secrets Officer" &&
      azurerm_role_assignment.deployer.principal_id == var.deployer_principal_id &&
      azurerm_role_assignment.web.role_definition_name == "Key Vault Secrets User" &&
      azurerm_role_assignment.web.principal_id == var.web_principal_id &&
      azurerm_key_vault_secret.portal.value == var.portal_subscription_key &&
      output.secret_uri == "https://sample-portal.vault.azure.net/secrets/portal-apim-subscription-key"
    )
    error_message = "The native APIM key must be stored only in the portal vault with least-privilege identity access and a versionless reference."
  }
  assert {
    condition = (
      length(azurerm_private_endpoint.this) == 1 &&
      toset(azurerm_private_endpoint.this[0].private_service_connection[0].subresource_names) == toset(["vault"]) &&
      azurerm_monitor_diagnostic_setting.this.log_analytics_workspace_id == var.workspace_id &&
      azurerm_monitor_diagnostic_setting.this.log_analytics_destination_type == "Dedicated"
    )
    error_message = "Private vault access requires the existing subnet and shared resource-specific diagnostic destination."
  }
}
run "explicit_public_portal_vault_does_not_create_private_endpoint" {
  command = plan
  module {
    source = "./modules/portal_key_vault"
  }
  variables {
    public_network_access_enabled = true
  }
  assert {
    condition = (
      azurerm_key_vault.this.public_network_access_enabled &&
      length(azurerm_private_endpoint.this) == 0 &&
      azurerm_key_vault.this.rbac_authorization_enabled
    )
    error_message = "Explicit public mode retains Entra RBAC without inventing private networking."
  }
}
